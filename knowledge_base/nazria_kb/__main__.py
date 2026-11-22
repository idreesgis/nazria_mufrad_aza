"""CLI.

    python -m nazria_kb build  --csv urdu_book.csv --out output/
    python -m nazria_kb load   --csv urdu_book.csv [--dsn-env NAZRIA_DATABASE_URL]
    python -m nazria_kb verify [--dsn-env NAZRIA_DATABASE_URL]
    python -m nazria_kb consult [--dsn-env NAZRIA_DATABASE_URL] [--answers '["none","قبض",...]'] [--save]
    python -m nazria_kb review   --provider local [--model M] --limit 100 [--weights | --weights-only]
    python -m nazria_kb evaluate --provider local,openai:<model> [--judge-provider local] [--csv book.csv]
    python -m nazria_kb export-training --mode human_or_ai|human_only [--include-hazardous] --out train.jsonl

Engine and provider come from NAZRIA_* environment variables (see .env.example); API keys are read from the
environment variable named by NAZRIA_LLM_API_KEY_ENV and are never printed.

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
        sys.exit(f"error: {type(e).__name__}: {redact(e, os.environ.get('NAZRIA_DATABASE_URL'))}")


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
    c.add_argument("--answers", nargs="+", help="answers for a scripted run: a JSON list, or plain values separated by "
                                     "commas or | (e.g. 10,قبض,3,2,3,1,1,1,1,1,1,2,2,4)")
    c.add_argument("--save", action="store_true", help="store the session in nazria.consultation_sessions")
    c.add_argument("--debug", action="store_true",
                   help="print the model's raw answers and the citation/safety checks (development only)")
    r = sub.add_parser("review", help="AI review (LLM-as-judge) of generated conversations / questionnaire weights")
    r.add_argument("--dsn-env", default="NAZRIA_DATABASE_URL")
    r.add_argument("--provider", help="provider id (default NAZRIA_LLM_PROVIDER)")
    r.add_argument("--model", help="model name (default NAZRIA_LLM_MODEL)")
    r.add_argument("--limit", type=int, default=50, help="max conversations to review in this run")
    r.add_argument("--weights", action="store_true", help="also write the questionnaire-weights report")
    r.add_argument("--weights-only", action="store_true", help="only the questionnaire-weights report")
    r.add_argument("--out", default="output", help="directory for the weights report")
    e = sub.add_parser("evaluate", help="compare providers on a fixed question set; writes a markdown report")
    e.add_argument("--dsn-env", default="NAZRIA_DATABASE_URL")
    e.add_argument("--provider", default="gemini",
                   help="comma list of provider[:model] (default gemini, i.e. gemini-3.5-flash)")
    e.add_argument("--judge-provider", default="gemini",
                   help="provider[:model] that scores groundedness and fluency (default gemini); 'none' to skip")
    e.add_argument("--csv", help="retrieve from a freshly built dataset instead of the database")
    e.add_argument("--out", default="output/EVALUATION_REPORT.md")
    t = sub.add_parser("export-training", help="write approved conversations as chat JSONL for fine-tuning")
    t.add_argument("--dsn-env", default="NAZRIA_DATABASE_URL")
    t.add_argument("--mode", choices=["human_only", "human_or_ai"],
                   default=os.environ.get("NAZRIA_TRAINING_REVIEW_MODE", "human_or_ai"))
    t.add_argument("--include-hazardous", action="store_true", help="include hazard-flagged conversations")
    t.add_argument("--out", default="output/training.jsonl")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if getattr(args, "debug", False):
        logging.getLogger("nazria_kb").setLevel(logging.DEBUG)

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
    if args.cmd == "review":
        return _review(args)
    if args.cmd == "evaluate":
        return _evaluate(args)
    if args.cmd == "export-training":
        return _export_training(args)
    return 1


def _provider(spec: str | None = None, model: str | None = None):
    """Build a provider from 'name[:model]' + NAZRIA_* env; exits with a clear message if it cannot run."""
    from .providers import ProviderConfig, ProviderError, build_provider
    name, _, m = (spec or "").partition(":")
    cfg = ProviderConfig.from_env(name or None, model or m or None)
    if name and name != (os.environ.get("NAZRIA_LLM_PROVIDER") or "").strip().lower() and name != "local":
        cfg.base_url = None      # NAZRIA_LLM_BASE_URL belongs to the configured provider only
    try:
        return build_provider(cfg)
    except ProviderError as e:
        sys.exit(f"cannot use provider: {e}")


def _review(args) -> int:
    from .db import connect, load_questions
    from .reviewer import PostgresReviewStore, fetch_pages_pg, review_conversations, review_weights
    provider = _provider(args.provider, args.model)
    with connect(_dsn(args)) as conn:
        conn.autocommit = True
        if not args.weights_only:
            def progress(n, item, status):
                print(f"[{n}] {item.uid} {item.conv_type} {'HAZ ' if item.hazard_flags else ''}-> {status}")
            stats = review_conversations(PostgresReviewStore(conn), provider, args.limit, progress=progress)
            print(json.dumps(stats, ensure_ascii=False, indent=2))
        if args.weights or args.weights_only:
            path = review_weights(load_questions(conn), lambda b, p: fetch_pages_pg(conn, b, p), provider,
                                  os.path.join(args.out, "QUESTIONNAIRE_WEIGHTS_REVIEW.md"))
            print(f"weights report (nothing changed): {path}")
    return 0


def _evaluate(args) -> int:
    from .evaluate import evaluate
    providers = [_provider(s.strip()) for s in args.provider.split(",") if s.strip()]
    judge = _provider(args.judge_provider) if args.judge_provider and args.judge_provider.lower() != "none" else None
    if args.csv:
        from .engine import DatasetRetriever
        from .pipeline import build
        path, summary = evaluate(providers, DatasetRetriever(build(args.csv)), args.out, judge)
    else:
        from .db import connect
        from .engine import PostgresRetriever
        with connect(_dsn(args)) as conn:
            path, summary = evaluate(providers, PostgresRetriever(conn), args.out, judge)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"report: {path}")
    return 0


def _export_training(args) -> int:
    from .db import connect
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    n = 0
    with connect(_dsn(args)) as conn, open(args.out, "w", encoding="utf-8") as fh:
        for (rec,) in conn.execute("SELECT record FROM nazria.training_messages(%s, %s)",
                                   (args.mode, args.include_hazardous)):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"{n} conversations ({args.mode}{', incl. hazard-flagged' if args.include_hazardous else ''}) -> {args.out}")
    return 0


def _consult(args) -> int:
    from .db import connect, load_questions, save_session
    from .engine import EngineConfig, PostgresRetriever, Session, build_engine
    try:
        # nargs="+": without quotes the shell splits an answer at its spaces; join the words back
        scripted = parse_answers(" ".join(args.answers)) if args.answers else None
    except ValueError as e:
        sys.exit(f"--answers: {e}")
    with connect(_dsn(args)) as conn:
        cfg = EngineConfig.from_env()
        engine = build_engine(cfg, PostgresRetriever(conn), load_questions(conn))
        if getattr(engine, "fallback_reason", None):
            print(f"[AI provider unavailable – using the questionnaire engine: {engine.fallback_reason}]")
        session = Session()
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


def parse_answers(text: str) -> list[str]:
    """--answers as a JSON list, or plain values separated by '|' or ',' (with or without [ ]).
    IDEs on Windows often strip the double quotes from parameters, which breaks JSON."""
    text = text.strip()
    try:
        value = json.loads(text)
        items = [str(v) for v in value] if isinstance(value, list) else None
    except json.JSONDecodeError:
        items = None
    if items is None:
        inner = text[1:-1] if text.startswith("[") and text.endswith("]") else text
        sep = "|" if "|" in inner else ","
        items = [x.strip().strip("\"'") for x in inner.split(sep)]
    items = [x for x in items if x]
    if not items:
        raise ValueError("no answers found; use e.g. 10,قبض,3,2,3,1,1,1,1,1,1,2,2,4")
    return items


def _report(checks) -> int:
    ok = True
    for name, passed, detail in checks:
        ok &= passed
        print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
