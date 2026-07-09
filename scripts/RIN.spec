# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import re
import tempfile
from pathlib import Path

import PySide6
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

SPEC_DIR = Path(globals().get("SPECPATH", Path.cwd() / "scripts")).resolve()
PROJECT_ROOT = SPEC_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
# Entry script lives OUTSIDE the rin package so it can use clean
# absolute imports. PyInstaller's bootloader runs whatever Analysis
# points at without setting __package__, so an in-package __main__.py
# entry breaks all relative imports. See scripts/rin_entry.py.
MAIN_SCRIPT = SPEC_DIR / "rin_entry.py"
PYSIDE_PLUGIN_ROOT = Path(PySide6.__file__).resolve().parent / "plugins"


def _read_rin_version() -> str:
    """Read ``__version__`` from src/rin/__init__.py so the .exe metadata
    never drifts from the package version."""

    init = SRC_ROOT / "rin" / "__init__.py"
    match = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text(encoding="utf-8"))
    return match.group(1) if match else "0.0.0"


def _make_version_file() -> str:
    """Generate a Windows VS_VERSION_INFO resource file and return its path.

    Without this, RIN.exe reports a blank FileVersion / ProductVersion,
    which makes version verification (e.g. ``(Get-Item RIN.exe).VersionInfo``)
    impossible. Written to a temp file (not committed).
    """

    version = _read_rin_version()
    parts = [int(p) for p in re.findall(r"\d+", version)][:4]
    while len(parts) < 4:
        parts.append(0)
    vtuple = tuple(parts)
    text = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vtuple},
    prodvers={vtuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'RIN Contributors'),
        StringStruct('FileDescription', 'RIN \u2014 Record It Now'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'RIN'),
        StringStruct('LegalCopyright', 'MIT License'),
        StringStruct('OriginalFilename', 'RIN.exe'),
        StringStruct('ProductName', 'RIN \u2014 Record It Now'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    out = Path(tempfile.gettempdir()) / "rin_version_info.txt"
    out.write_text(text, encoding="utf-8")
    return str(out)


VERSION_FILE = _make_version_file()

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
        + collect_submodules("rin")
        + collect_submodules("rin.skills.builtin")
        + collect_submodules("rin.llm")
        + [
            "rin",
            "rin.__main__",
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
    version=VERSION_FILE,
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
