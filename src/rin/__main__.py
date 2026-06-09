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


def _cmd_reindex(args: argparse.Namespace) -> int:
    """Re-index captures into the vector store (Phase 1-C, v0.12.0).

    Existing entries are overwritten so the new ``bucket_keys`` metadata
    introduced in v0.12.0 is populated for old captures and search's
    ``pois=`` filter works retroactively.
    """

    try:
        from .rag import index_pending
        from .storage import init_db

        init_db()
        indexed = index_pending(limit=args.limit)
        print(f"Re-indexed {len(indexed)} capture(s) into the vector store.")
        return 0
    except Exception as exc:
        log.exception(f"reindex failed: {exc}")
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_skill_scaffold(args: argparse.Namespace) -> int:
    """Create a starter ``skill.py`` template (Phase 3-A, v0.17.0)."""

    from pathlib import Path as _Path

    from .skills.scaffold import scaffold_skill

    try:
        target_dir = _Path(args.dir).expanduser() if args.dir else None
        path = scaffold_skill(
            name=args.name,
            display_name=args.display_name,
            description=args.description or "",
            version=args.version,
            skills_dir=target_dir,
            overwrite=args.force,
        )
        print(f"Created skill template at: {path}")
        print(
            "Next steps:\n"
            f"  1. Edit {path}\n"
            "  2. Run 'rin skill validate' on it to smoke-test\n"
            "  3. Enable the skill in Settings → Skills (restart RIN first)"
        )
        return 0
    except (ValueError, FileExistsError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        log.exception(f"skill scaffold failed: {exc}")
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_skill_validate(args: argparse.Namespace) -> int:
    """Smoke-test a user skill (Phase 3-A, v0.17.0)."""

    from pathlib import Path as _Path

    from .skills.scaffold import _resolve_skill_path, validate_skill

    try:
        skill_py = _resolve_skill_path(_Path(args.path).expanduser())
        report = validate_skill(skill_py)
        print(report.format())
        return 0 if report.passed else 1
    except Exception as exc:
        log.exception(f"skill validate failed: {exc}")
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

    reix = subparsers.add_parser(
        "reindex",
        help=(
            "Re-index captures into the vector store. Required once after "
            "upgrading to v0.12.0 so search's --pois filter works for "
            "captures embedded before the upgrade."
        ),
    )
    reix.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum number of captures to re-index in one run (default: 1000).",
    )

    skill_p = subparsers.add_parser(
        "skill",
        help="Scaffold + validate user-installable skills (v0.17.0+).",
    )
    skill_sub = skill_p.add_subparsers(dest="skill_command")

    sc = skill_sub.add_parser(
        "scaffold",
        help="Create a starter skill.py template under the user skills dir.",
    )
    sc.add_argument("name", help="Skill name (a-z, digits, underscore).")
    sc.add_argument("--display-name", dest="display_name", default=None)
    sc.add_argument("--description", default="")
    sc.add_argument("--version", default="0.1.0")
    sc.add_argument(
        "--dir",
        default=None,
        help=(
            "Override the user skills directory "
            "(default: %%LOCALAPPDATA%%\\RIN\\skills on Windows)."
        ),
    )
    sc.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing skill.py at the target path.",
    )

    val = skill_sub.add_parser(
        "validate",
        help="Smoke-test a skill.py (load + detect/should_close/render_archive).",
    )
    val.add_argument(
        "path",
        help=(
            "Path to a skill folder or its skill.py. Returns exit code 0 on "
            "PASS, 1 on FAIL."
        ),
    )

    args = parser.parse_args(argv)

    if args.command == "poi-discover":
        return _cmd_poi_discover(args)
    if args.command == "reindex":
        return _cmd_reindex(args)
    if args.command == "skill":
        if args.skill_command == "scaffold":
            return _cmd_skill_scaffold(args)
        if args.skill_command == "validate":
            return _cmd_skill_validate(args)
        skill_p.print_help()
        return 2

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
