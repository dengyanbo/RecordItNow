"""Entry point for ``python -m rin``.

Uses relative imports — the canonical style for a package's
``__main__`` module. Python sets ``__package__='rin'`` when invoking
via ``python -m rin``, so the relative imports resolve cleanly.

For the standalone PyInstaller .exe bundle we use a separate entry
script (``scripts/rin_entry.py``) that does ``from rin.__main__
import main``. PyInstaller bundles this module via the spec's
``collect_submodules('rin')`` plumbing, so the absolute import
resolves through the PYZ archive at runtime.
"""
from __future__ import annotations

import argparse
import sys

from .app import run
from .config import RinConfig
from .llm import make_provider
from .llm.base import ProviderUnavailable
from .poi import discover, persist_candidates
from .utils import single_instance
from .utils.logging import get_logger

log = get_logger(__name__)


def _cmd_poi_discover(args: argparse.Namespace) -> int:
    try:
        from .storage import db, init_db

        init_db()
        db.engine()
        cfg = RinConfig.load()

        provider = None
        if args.use_llm:
            try:
                provider = make_provider(cfg.llm)
            except ProviderUnavailable as exc:
                print(
                    f"Warning: LLM provider unavailable: {exc}",
                    file=sys.stderr,
                )

        drafts = discover(
            cfg,
            days=args.days,
            use_llm=args.use_llm,
            provider=provider,
            max_candidates=args.max_candidates,
        )
        if not drafts:
            print("No PoI candidates found.")
        for draft in drafts:
            evidence_count = len(draft.evidence_capture_ids)
            print(
                f"[{draft.score:0.2f}] [{draft.kind}] {draft.suggested_name} "
                f"(evidence: {evidence_count} captures)"
            )
        if args.persist:
            inserted_ids = persist_candidates(drafts)
            print(f"Saved {len(inserted_ids)} new candidates to DB.")
        return 0
    except Exception as exc:
        log.exception(f"poi-discover failed: {exc}")
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rin", description="Record It Now")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Boot the application and immediately exit (used by smoke tests).",
    )

    subparsers = parser.add_subparsers(dest="command")

    disc = subparsers.add_parser(
        "poi-discover",
        help="Mine captures for candidate Points of Interest.",
    )
    disc.add_argument("--days", type=int, default=14)
    disc.add_argument(
        "--use-llm",
        action="store_true",
        help="Include LLM batch extraction (1 LLM call).",
    )
    disc.add_argument(
        "--persist",
        action="store_true",
        help="Save results to poi_candidates table (default: dry-run).",
    )
    disc.add_argument("--max", type=int, default=30, dest="max_candidates")

    args = parser.parse_args(argv)

    if args.command == "poi-discover":
        return _cmd_poi_discover(args)

    # Single-instance gate: a second RIN tray would duplicate icons,
    # global hotkey listeners, and SQLite writers. Skipped under
    # --smoke so smoke tests never collide with a running tray.
    if not args.smoke and not single_instance.acquire():
        single_instance.notify_already_running()
        return 0

    try:
        return run(smoke=args.smoke)
    finally:
        single_instance.release()


if __name__ == "__main__":
    sys.exit(main())
