"""Build a one-folder PyInstaller distribution of RIN.

Run from the repo root with the venv active:

    python scripts/package.py

The output lands in ``dist/RIN/`` (one-folder) with ``RIN.exe`` as the
entry point.

This script does not bundle FFmpeg or downloaded ML models — those are
prerequisites that the README documents. Bundling FFmpeg is a future
enhancement.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def _ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0"])


def main() -> int:
    _ensure_pyinstaller()

    if (ROOT / "build").exists():
        shutil.rmtree(ROOT / "build", ignore_errors=True)
    if (ROOT / "dist").exists():
        shutil.rmtree(ROOT / "dist", ignore_errors=True)

    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        "RIN",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--paths",
        str(SRC),
        "--collect-submodules",
        "rin",
        "--collect-data",
        "rapidocr_onnxruntime",
        "--hidden-import",
        "sentence_transformers",
        str(SRC / "rin" / "__main__.py"),
    ]
    print("Running:", " ".join(args))
    rc = subprocess.call(args, cwd=str(ROOT))
    if rc == 0:
        print(f"\nBuild succeeded: {ROOT / 'dist' / 'RIN'}")
    else:
        print(f"\nBuild failed (exit {rc})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
