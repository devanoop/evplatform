"""Command line entry points.

    python -m ev_platform.cli migrate          # apply database migrations
    python -m ev_platform.cli ingest [source]  # run ingestion, then refresh photos (the Railway cron)
    python -m ev_platform.cli photos [--force] # refresh car photos from Wikimedia Commons only
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
    from .pipeline import run_full_update

    with session_scope() as db:
        runs = run_full_update(db, sources or None)
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
    ph = sub.add_parser("photos")
    ph.add_argument("--force", action="store_true", help="re-check every model, not just stale ones")
    args = p.parse_args()
    if args.cmd == "migrate":
        migrate()
    elif args.cmd == "ingest":
        migrate()  # cheap no-op when up to date; keeps a fresh cron service safe
        sys.exit(ingest(args.sources))
    elif args.cmd == "photos":
        from .db import session_scope
        from .photos import refresh_photos

        migrate()
        with session_scope() as db:
            print(refresh_photos(db, force=args.force))


if __name__ == "__main__":
    main()
