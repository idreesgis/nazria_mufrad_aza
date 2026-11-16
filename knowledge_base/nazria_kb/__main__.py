"""CLI.

    python -m nazria_kb build  --csv urdu_book.csv --out output/
    python -m nazria_kb load   --csv urdu_book.csv [--dsn-env NAZRIA_DATABASE_URL]
    python -m nazria_kb verify [--dsn-env NAZRIA_DATABASE_URL]
    python -m nazria_kb consult [--dsn-env NAZRIA_DATABASE_URL] [--answers '["none","قبض",...]'] [--save]

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
    try:
        return _main(argv)
    except Exception as e:  # DB errors are already redacted; keep tracebacks (which may hold DSNs) out of logs
        from .db import DatabaseError, redact
        if isinstance(e, DatabaseError):
            sys.exit(f"database error: {e}")
        raise RuntimeError(redact(e, os.environ.get("NAZRIA_DATABASE_URL"))) from None


def _main(argv=None) -> int:
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
    c = sub.add_parser("consult", help="run a questionnaire consultation in the terminal (uses the DB)")
    c.add_argument("--dsn-env", default="NAZRIA_DATABASE_URL")
    c.add_argument("--answers", help="JSON list of answers for a scripted, non-interactive run")
    c.add_argument("--save", action="store_true", help="store the session in nazria.consultation_sessions")
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
    if args.cmd == "consult":
        return _consult(args)
    if args.cmd == "verify":
        from .db import connect, verify
        with connect(_dsn(args)) as conn:
            return _report(verify(conn))
    return 1


def _consult(args) -> int:
    from .db import connect, load_questions, save_session
    from .engine import EngineConfig, PostgresRetriever, Session, build_engine
    scripted = list(json.loads(args.answers)) if args.answers else None
    with connect(_dsn(args)) as conn:
        cfg = EngineConfig.from_env()
        engine = build_engine(cfg, PostgresRetriever(conn), load_questions(conn))
        session = Session(provider=cfg.provider, model=cfg.model)
        reply = engine.start(session)
        while True:
            print("\n" + reply.text)
            if reply.options:
                for i, (_, label) in enumerate(reply.options, 1):
                    print(f"  {i}. {label}")
            if reply.done:
                break
            if scripted is not None:
                if not scripted:
                    print("\n[scripted answers exhausted]")
                    break
                msg = str(scripted.pop(0))
                print(f"> {msg}")
            else:
                try:
                    msg = input("> ")
                except EOFError:
                    break
            reply = engine.reply(session, msg)
        if args.save:
            save_session(conn, session)
            print(f"\n[saved session {session.session_uid}]")
        print("\n" + json.dumps(session.result, ensure_ascii=False))
    return 0


def _report(checks) -> int:
    ok = True
    for name, passed, detail in checks:
        ok &= passed
        print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
