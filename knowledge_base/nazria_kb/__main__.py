"""CLI.

    python -m nazria_kb build  --csv urdu_book.csv --out output/
    python -m nazria_kb load   --csv urdu_book.csv [--dsn-env NAZRIA_DATABASE_URL]
    python -m nazria_kb verify [--dsn-env NAZRIA_DATABASE_URL]

The DSN is read from an environment variable (never pass passwords on the command line).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys


def _dsn(args) -> str:
    dsn = os.environ.get(args.dsn_env)
    if not dsn:
        sys.exit(f"environment variable {args.dsn_env} is not set (format: postgresql://user:pass@host:5432/db?sslmode=require)")
    return dsn


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nazria_kb")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build dataset and write JSONL exports + quality report")
    b.add_argument("--csv", required=True)
    b.add_argument("--out", default="output")
    l = sub.add_parser("load", help="build and load into PostgreSQL (full refresh, single transaction)")
    l.add_argument("--csv", required=True)
    l.add_argument("--dsn-env", default="NAZRIA_DATABASE_URL")
    l.add_argument("--out", help="also write exports to this directory")
    v = sub.add_parser("verify", help="run integrity checks against the database")
    v.add_argument("--dsn-env", default="NAZRIA_DATABASE_URL")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.cmd in ("build", "load"):
        from .pipeline import build
        ds = build(args.csv)
        if args.cmd == "build" or args.out:
            from .export import export
            print(json.dumps(export(ds, args.out), ensure_ascii=False, indent=2))
        if args.cmd == "build":
            print(json.dumps(ds.stats(), ensure_ascii=False, indent=2))
            return 0
        from .db import connect, load, verify
        with connect(_dsn(args)) as conn:
            stats = load(conn, ds)
            print(json.dumps(stats["db_counts"], ensure_ascii=False, indent=2))
            return _report(verify(conn))
    if args.cmd == "verify":
        from .db import connect, verify
        with connect(_dsn(args)) as conn:
            return _report(verify(conn))
    return 1


def _report(checks) -> int:
    ok = True
    for name, passed, detail in checks:
        ok &= passed
        print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
