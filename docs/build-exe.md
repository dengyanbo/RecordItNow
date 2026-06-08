# Building the standalone Windows `.exe` bundle

RIN now ships a PyInstaller **onedir** bundle so end users do not need Python on the target machine. We intentionally do **not** use `--onefile`; ChromaDB, Torch, faster-whisper, and Qt plugins are more reliable when they stay unpacked in a directory layout.

## Build

From an activated project venv:

```powershell
uv pip install -e ".[all,dev]"
.\scripts\build_exe.ps1
```

The script runs `ruff` + `pytest`, reads `src\rin\__init__.py`, builds with `scripts\RIN.spec`, stages an installer layout, and writes a single zip:

- PyInstaller onedir bundle: `dist\RIN\` (intermediate)
- release asset: `dist\RIN-vX.Y.Z-windows-installer.zip` (this is the end-user download)

## What's in the bundle

- `RIN.exe` plus the embedded Python runtime
- PySide6 platform/style plugins and SVG support
- ChromaDB runtime files via `collect_all("chromadb")`
- `sentence-transformers`, `faster-whisper`, `rapidocr-onnxruntime`, `mss`, `pynput`, and `hidapi` dependencies
- bundled UI assets, `rin.storage.migrations`, and the built-in `support_ticket` skill package

Not included:

- `ffmpeg.exe` (still external; install separately if you need MP4 recording)
- downloaded model caches (`%LOCALAPPDATA%\RIN\models\...` are populated on first use)

## Expected size

Target the extracted onedir bundle to stay **under 1 GB**. In practice, expect roughly **750-950 MB unpacked**, with Torch + Whisper accounting for about **700 MB** of that footprint. The zip is smaller, but the installed folder is the size that matters on the target machine.

## Installer zip layout

`build_exe.ps1` stages the following layout under `build\installer\` and zips it as `dist\RIN-vX.Y.Z-windows-installer.zip`:

```
RIN-vX.Y.Z-windows-installer.zip
├─ Install.bat              # end-user double-clicks this
├─ install.ps1              # called by Install.bat; copies bundle into %LOCALAPPDATA%\Programs\RIN
├─ prefetch_models.py       # optional sentence-transformer + whisper model warm-up
├─ README-INSTALL.txt       # one-page install instructions
├─ version.txt              # stamped version string read by Get-RinVersion
└─ bundle\
    ├─ RIN.exe              # PyInstaller launcher
    └─ _internal\           # Python runtime, PySide6, ChromaDB, etc. (the whole onedir)
```

## Installing the prebuilt bundle locally

After `dist\RIN-vX.Y.Z-windows-installer.zip` exists, the end-user flow is:

1. Right-click the zip → **Extract All**
2. Double-click `Install.bat`

That's it — `Install.bat` invokes `install.ps1 -FromBundle bundle -Force` under the hood, copies the bundle into `%LOCALAPPDATA%\Programs\RIN\`, registers the Start Menu shortcut, and (if missing) installs FFmpeg via `winget install Gyan.FFmpeg`.

For developer testing without re-running PyInstaller:

```powershell
.\scripts\install.ps1 -FromBundle .\dist\RIN -Force
```

## Troubleshooting

### ChromaDB fails to load inside the bundle

Keep `collect_all("chromadb")` in `scripts\RIN.spec`. ChromaDB pulls in non-trivial package data and binary payloads; using `collect_all` is the cleanest way to avoid the usual missing-module / missing-binary failures in frozen apps.

### Whisper downloads models to an unexpected place

RIN caches faster-whisper models under `%LOCALAPPDATA%\RIN\models\whisper` (see `rin.paths.models_cache_dir()`). The first transcription run can therefore spend time downloading weights even though the `.exe` itself is already bundled.

### Bundle size suddenly jumps

PyInstaller can sometimes pull in Torch CUDA/distributed pieces even for CPU-only usage. If the extracted folder blows past the size target, try `excludes=["torch.cuda", "torch.distributed"]` in `scripts\RIN.spec` and then smoke-test transcription + embeddings on a clean Windows machine. That trim helps size, but it is a compatibility trade-off because some upstream code probes `torch.cuda` at runtime.
