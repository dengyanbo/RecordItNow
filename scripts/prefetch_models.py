"""Pre-download every machine-learning model RIN uses at runtime.

After running this script, the first ``Analyze now`` / ``Search`` / ``Ask`` will
not need internet access — the sentence-transformers, RapidOCR, and Whisper
weights are already on disk under ``%LOCALAPPDATA%\\RIN\\models\\``.

Each download is wrapped so a single failure (no internet, mirror flake)
doesn't abort the install — partial pre-fetch is still useful.

Usage
-----
    python scripts\\prefetch_models.py
    python scripts\\prefetch_models.py --whisper medium    # bigger Whisper

Run from the repo root with the venv active (``install.ps1 -Prefetch``
does this for you).
"""
from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path

# Allow running as ``python scripts\prefetch_models.py`` from the repo root
# without a prior ``pip install -e .``.
REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if SRC_DIR.exists() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return total / (1024 * 1024)


def _run(name: str, fn: Callable[[], object], cache_dir: Path) -> bool:
    print(f"\n→ {name} …", flush=True)
    before = _dir_size_mb(cache_dir)
    t0 = time.monotonic()
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - we want any failure to be non-fatal
        print(f"  ✗ {name} failed: {exc}", flush=True)
        return False
    after = _dir_size_mb(cache_dir)
    delta = after - before
    elapsed = time.monotonic() - t0
    print(
        f"  ✓ {name} ready in {elapsed:5.1f}s "
        f"(+{delta:5.1f} MB → {cache_dir})",
        flush=True,
    )
    return True


def prefetch_sentence_transformer() -> None:
    from rin.rag.embedder import get_embedder

    embedder = get_embedder()
    embedder.embed("warm up")


def prefetch_rapidocr() -> None:
    from rin.analysis.ocr import _get_engine

    engine = _get_engine()
    if engine is None:
        raise RuntimeError("rapidocr_onnxruntime not installed")


def prefetch_whisper(model_name: str) -> None:
    from rin.analysis.transcribe import _get_model

    model = _get_model(model_name)
    if model is None:
        raise RuntimeError("faster-whisper not installed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pre-download ML models so RIN's first run is offline-capable.",
    )
    parser.add_argument(
        "--whisper",
        default="small",
        help="Whisper model size to fetch (tiny / base / small / medium / large-v3).",
    )
    parser.add_argument(
        "--skip",
        choices=["embedder", "ocr", "whisper"],
        action="append",
        default=[],
        help="Skip a specific loader. May be given multiple times.",
    )
    args = parser.parse_args(argv)

    from rin.paths import models_cache_dir

    cache_root = Path(models_cache_dir())
    print(f"Cache root: {cache_root}", flush=True)

    plan: list[tuple[str, Callable[[], object], Path]] = []
    if "embedder" not in args.skip:
        plan.append(
            (
                "Sentence-transformers (all-MiniLM-L6-v2, ~90 MB)",
                prefetch_sentence_transformer,
                cache_root / "sentence-transformers",
            )
        )
    if "ocr" not in args.skip:
        plan.append(("RapidOCR ONNX (bundled)", prefetch_rapidocr, cache_root))
    if "whisper" not in args.skip:
        plan.append(
            (
                f"faster-whisper {args.whisper!r} (~50 MB to ~3 GB depending on size)",
                lambda: prefetch_whisper(args.whisper),
                cache_root / "whisper",
            )
        )

    results = [_run(name, fn, path) for name, fn, path in plan]
    ok = sum(results)
    total = len(results)
    print(f"\nDone: {ok}/{total} prefetches succeeded.")
    if ok < total:
        print(
            "Some prefetches failed — RIN will retry on first use.\n"
            "Re-run this script when you have a stable network."
        )
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
