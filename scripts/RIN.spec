# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import PySide6
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

SPEC_DIR = Path(globals().get("SPECPATH", Path.cwd() / "scripts")).resolve()
PROJECT_ROOT = SPEC_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
MAIN_SCRIPT = SRC_ROOT / "rin" / "__main__.py"
PYSIDE_PLUGIN_ROOT = Path(PySide6.__file__).resolve().parent / "plugins"

chromadb_datas, chromadb_binaries, chromadb_hiddenimports = collect_all(
    "chromadb",
    include_py_files=False,
    on_error="ignore",
)
sentence_transformers_datas, sentence_transformers_binaries, sentence_transformers_hiddenimports = collect_all(
    "sentence_transformers",
    include_py_files=False,
    on_error="ignore",
)
faster_whisper_datas, faster_whisper_binaries, faster_whisper_hiddenimports = collect_all(
    "faster_whisper",
    include_py_files=False,
    on_error="ignore",
)
rapidocr_datas, rapidocr_binaries, rapidocr_hiddenimports = collect_all(
    "rapidocr_onnxruntime",
    include_py_files=False,
    on_error="ignore",
)
mss_datas, mss_binaries, mss_hiddenimports = collect_all(
    "mss",
    include_py_files=False,
    on_error="ignore",
)
pynput_datas, pynput_binaries, pynput_hiddenimports = collect_all(
    "pynput",
    include_py_files=False,
    on_error="ignore",
)

metadata_packages = [
    "chromadb",
    "sentence-transformers",
    "faster-whisper",
    "rapidocr-onnxruntime",
    "mss",
    "pynput",
    "hidapi",
    "PySide6",
]

datas = []
for group in (
    chromadb_datas,
    sentence_transformers_datas,
    faster_whisper_datas,
    rapidocr_datas,
    mss_datas,
    pynput_datas,
):
    datas += group
for package in metadata_packages:
    datas += copy_metadata(package)
datas += [
    (str(SRC_ROOT / "rin" / "storage" / "migrations.py"), "rin/storage"),
]


def _walk_as_datas(src_dir: Path, dest_prefix: str) -> list[tuple[str, str]]:
    """Walk every file under ``src_dir`` and emit ``(src, dst_dir)`` tuples
    suitable for :class:`Analysis`'s ``datas`` parameter.

    PyInstaller's :func:`Tree` returns 3-tuples designed for ``COLLECT``,
    so feeding it into ``Analysis.datas`` raises
    ``ValueError: too many values to unpack``. This helper builds the
    flat 2-tuple form ``Analysis`` actually expects.
    """

    out: list[tuple[str, str]] = []
    for f in src_dir.rglob("*"):
        if not f.is_file():
            continue
        rel_dir = f.parent.relative_to(src_dir)
        dst = dest_prefix if str(rel_dir) in (".", "") else f"{dest_prefix}/{rel_dir.as_posix()}"
        out.append((str(f), dst))
    return out


datas += _walk_as_datas(SRC_ROOT / "rin" / "ui" / "assets", "rin/ui/assets")
datas += _walk_as_datas(
    SRC_ROOT / "rin" / "skills" / "builtin" / "support_ticket",
    "rin/skills/builtin/support_ticket",
)
datas += _walk_as_datas(PYSIDE_PLUGIN_ROOT / "platforms", "PySide6/plugins/platforms")
datas += _walk_as_datas(PYSIDE_PLUGIN_ROOT / "styles", "PySide6/plugins/styles")

binaries = []
for group in (
    chromadb_binaries,
    sentence_transformers_binaries,
    faster_whisper_binaries,
    rapidocr_binaries,
    mss_binaries,
    pynput_binaries,
):
    binaries += group

hiddenimports = sorted(
    set(
        chromadb_hiddenimports
        + sentence_transformers_hiddenimports
        + faster_whisper_hiddenimports
        + rapidocr_hiddenimports
        + mss_hiddenimports
        + pynput_hiddenimports
        + collect_submodules("rin.skills.builtin")
        + collect_submodules("rin.llm")
        + [
            "chromadb",
            "sentence_transformers",
            "faster_whisper",
            "rapidocr_onnxruntime",
            "mss",
            "mss.tools",
            "pynput",
            "pynput.keyboard",
            "pynput.mouse",
            "hid",
            "PySide6.QtSvg",
        ]
    )
)

a = Analysis(
    [str(MAIN_SCRIPT)],
    pathex=[str(SRC_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim ~250 MB of GPU + distributed-training scaffolding that ships
    # with torch but is never touched by RIN's CPU-only inference path.
    # Documented in docs/build-exe.md. If users start reporting "module
    # not found" crashes, narrow this list rather than dropping it.
    excludes=[
        "torch.cuda",
        "torch.distributed",
        "torch.distributions",
        "torch.onnx",
        "torch.testing",
        "torch.utils.tensorboard",
        "torch.utils.benchmark",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RIN",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    a.zipfiles,
    strip=False,
    upx=False,
    name="RIN",
)
