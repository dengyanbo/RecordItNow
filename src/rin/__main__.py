"""Entry point for ``python -m rin``."""
from __future__ import annotations

import argparse
import sys

from .app import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rin", description="Record It Now")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Boot the application and immediately exit (used by smoke tests).",
    )
    args = parser.parse_args(argv)
    return run(smoke=args.smoke)


if __name__ == "__main__":
    sys.exit(main())
