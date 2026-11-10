"""Command line entry points.

    python -m ev_platform.cli migrate          # apply database migrations
    python -m ev_platform.cli ingest [source]  # run ingestion (what the Railway cron service runs)
"""

import argparse
import logging
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]


def migrate() -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")


def ingest(sources: list[str] | None) -> int:
    from .db import session_scope
    from .pipeline import run_ingest

    with session_scope() as db:
        runs = run_ingest(db, sources or None)
    for r in runs:
        print(f"{r.source:15} {r.status:8} {r.stats}")
    return 1 if any(r.status == "failed" for r in runs) else 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="ev_platform")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    ing = sub.add_parser("ingest")
    ing.add_argument("sources", nargs="*")
    args = p.parse_args()
    if args.cmd == "migrate":
        migrate()
    elif args.cmd == "ingest":
        migrate()  # cheap no-op when up to date; keeps a fresh cron service safe
        sys.exit(ingest(args.sources))


if __name__ == "__main__":
    main()
