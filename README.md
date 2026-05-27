# RIN — Record It Now

> **Languages:** **English** · [中文](README.zh-CN.md)

A Windows background app that captures, analyzes, and searches your screen
activity with a single configurable button.

- **Tap** a button → full-resolution PNG of every monitor.
- **Hold** (> 500 ms) → MP4 + audio recording of every monitor until release.
- During non-working time, RIN analyzes captures with an LLM, summarizes
  them, and indexes the summaries into a local RAG so you can ask things
  like *"what was that error I saw on Tuesday afternoon?"* later.
- Daily / weekly markdown reports.
- 100 % local storage: SQLite for metadata, ChromaDB for vectors, the file
  system for raw captures.

> **Status:** v0.3.0 — Fluent-inspired UI refresh. End-to-end pipeline
> verified: capture → OCR → vision LLM → SQLite + ChromaDB → semantic search
> → RAG Q&A with citations. **172 tests passing**, ruff clean. Hardened
> against common Windows runtime issues (Ctrl+C exit, cp1252 subprocess
> decoding, RDP recorder edge cases, in-progress analysis feedback).

## What's new in v0.3.0

- **Fluent-inspired design system.** Every color, font, radius, and
  spacing lives in `theme.py` with light + dark presets, four accent
  colors (blue / purple / teal / orange), and two density modes
  (comfortable / compact). All WCAG AA verified.
- **Auto-follow Windows theme.** RIN reads your light/dark preference
  from the registry and matches; you can override in
  Settings → Appearance.
- **Settings redesigned** with a left navigation rail + a new
  Appearance tab.
- **Reports window** now shows card-styled report list on the left and
  themed Markdown rendering on the right.
- **Search window** uses result cards and chat-bubble Q&A.
- **Tray icon** is a Fluent camera glyph with a pulsing red dot while
  recording.
- **20 bundled Fluent UI System Icons** (Microsoft, MIT).
- **Live theme switching** with no restart.

## What's new in v0.2.0

- **One-click installer.** Download the release zip, right-click `install.ps1`
  → *Run with PowerShell*. The script provisions Python, FFmpeg, the Copilot
  CLI, and all Python deps — no manual setup.
- **Optional `-Prefetch` flag** downloads the ~1 GB of ML model weights
  (sentence-transformers + RapidOCR + Whisper) at install time so the first
  *Analyze now* runs offline.
- **Optional `-Autostart` flag** wires RIN into Windows' login start-up.
- **Start Menu shortcut** launches RIN with no console window
  (`pythonw.exe -m rin`).
- **`NOTICE` file** documents every third-party dependency and its license.
- All v0.1.1 hardening (Ctrl+C exit, UTF-8 subprocess safety, analysis
  progress toasts, settings save fix, real Reports/Search windows) is
  carried forward.

## Install (end users) — recommended

1. Download the latest `RIN-vX.Y.Z-windows.zip` from
   [GitHub Releases](https://github.com/dengyanbo/RecordItNow/releases).
2. Right-click the zip → *Extract All* → pick any folder.
3. Right-click `install.ps1` → *Run with PowerShell*.
   (Or open PowerShell in that folder and run `.\install.ps1`.)

```powershell
# Quick variants:
.\install.ps1                       # default install
.\install.ps1 -Prefetch             # also pre-download ML models (~1 GB)
.\install.ps1 -Autostart            # also start on Windows login
.\install.ps1 -InstallDir D:\Apps\RIN
.\install.ps1 -SkipDeps             # skip Python/FFmpeg/Copilot CLI install
.\install.ps1 -Force                # overwrite without prompting
```

The installer puts everything in `%LOCALAPPDATA%\Programs\RIN` (no admin
needed). After it finishes, launch **RIN** from the Start Menu.

### Updating

Re-run `install.ps1` over the existing install — it will prompt for overwrite
(use `-Force` to skip the prompt). Your data under `%LOCALAPPDATA%\RIN` is
preserved.

### Uninstalling

```powershell
# 1. Disable autostart (if it was enabled)
& "$env:LOCALAPPDATA\Programs\RIN\.venv\Scripts\python.exe" -c "from rin.utils.autostart import disable; disable()"

# 2. Remove the program
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Programs\RIN"

# 3. (Optional) wipe your captures + database + ML model cache
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\RIN"

# 4. (Optional) remove the Start Menu shortcut
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\RIN.lnk"
```

## How it works

```
┌────────────────────────────────────────────────────────────────────────┐
│  System tray (PySide6)                                                 │
│   Capture · Record · Reports · Search · Settings · Pause · Quit        │
└──────────────────────────────┬─────────────────────────────────────────┘
                               │
   ┌───────────────────────────┼───────────────────────────┐
   ▼                           ▼                           ▼
 Input gesture            Capture service              Schedulers
 (tap / hold)             (mss + ffmpeg)               (analysis + reports)
   │                           │                           │
   └──────────────► SQLite + ChromaDB + filesystem ◄───────┘
                               │
                  ┌────────────┴────────────┐
                  ▼                         ▼
              Analysis                    RAG agent
              (OCR + Whisper + LLM)       (embed + retrieve + chat)
```

## Features

| Area | Capabilities |
| --- | --- |
| **Trigger** | Bind any keyboard key, mouse button, or HID / Bluetooth button via a "learn next press" flow |
| **Capture** | Multi-monitor PNG screenshots (mss) and per-monitor MP4 video with system + mic audio (ffmpeg + WASAPI loopback) |
| **Storage** | SQLite (WAL + foreign keys) for metadata, ChromaDB for vectors, dated file tree for raw media, configurable retention |
| **LLM providers** | GitHub Copilot CLI (default, no API key needed) · OpenAI · Azure OpenAI — pluggable, picked from Settings |
| **Analysis** | Hourly background job gated by working hours OR idle detection; runs RapidOCR + faster-whisper + vision LLM |
| **Reports** | Daily or weekly markdown summaries with Highlights / Apps / Topics / Action items sections |
| **RAG search** | Semantic search across captures with cited answers from a retrieval-augmented agent |
| **Privacy** | Panic-pause hotkey (Ctrl+Alt+Shift+P), no network calls unless you pick a cloud LLM, all data lives under `%LOCALAPPDATA%\RIN\` |

## Requirements

| Tool | Version | Notes |
| --- | --- | --- |
| Windows | 10 or 11 | Phase 0 is portable, capture / input / panic-pause are Windows-only |
| Python | 3.11 or 3.12 | |
| FFmpeg | latest | Required for video recording (Phase 2) and keyframe extraction (Phase 6). On Windows: `winget install --id Gyan.FFmpeg -e`. After install, **open a fresh PowerShell** to pick up the updated PATH. |
| GitHub Copilot CLI | latest | Default LLM provider. Alternatives: OpenAI API key, Azure OpenAI |

## Development

If you're contributing or running from source:

```powershell
# 1. Install uv (fast Python package manager)
winget install --id=astral-sh.uv -e

# 2. Create a virtual environment and install RIN with dev extras
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[all,dev]"

# 3. Boot the tray app
python -m rin
```

Smaller install (only what you need):

| Extra | Purpose | Phase |
| --- | --- | --- |
| `storage` | SQLAlchemy + ChromaDB | 1 |
| `capture` | mss, sounddevice, pywin32 | 2 |
| `input` | keyboard, pynput, hidapi | 3 |
| `llm` | openai, keyring | 5 |
| `analysis` | APScheduler, rapidocr, faster-whisper | 6 |
| `reports` | Jinja2, markdown | 7 |
| `rag` | sentence-transformers | 8 |
| `dev` | pytest, ruff | always |
| `all` | everything except `dev` | full install |

```powershell
uv pip install -e ".[storage,capture,dev]"
```

## Runtime data

```
%LOCALAPPDATA%\RIN\
├── config.toml      # user-mutable settings
├── rin.db           # SQLite (metadata)
├── chroma\          # ChromaDB persist dir
├── captures\        # raw PNG / MP4 / WAV captures
├── reports\         # generated markdown reports
├── models\          # cached ONNX / Whisper / embedding models
└── logs\
    └── rin.log      # rotated 10 MB / 14 days
```

Set `RIN_DATA_DIR` to override the root (used by tests).

## Testing

```powershell
pytest          # full suite (144 tests)
ruff check src tests
python -m rin --smoke   # boot and exit cleanly
```

## Smoke-test checklist

After installing, run through this manual sequence:

1. **Boot.** `python -m rin --smoke` → exits 0, `logs\rin.log` shows startup.
2. **Launch tray.** `python -m rin` → tray icon appears; right-click shows the menu.
   Press **Ctrl+C** in the terminal to confirm clean shutdown works.
3. **Learn trigger.** Settings → Trigger → *Learn new button* → tap any key. Label updates.
4. **Take a screenshot.** Tray → *📸 Capture now*. PNG appears under `captures\YYYY\MM\DD\<ts>-shot\`.
5. **Analyze.** Tray → *🧠 Analyze now*. Progress toasts appear; tray tooltip shows
   `Analyzing K/N (cap-X)`; final toast confirms `Analysis complete — N/N captures analyzed`.
6. **Search.** Tray → *Search…* → type a query. Hits show; ask a question, agent answers with `cap-N` citations.
7. **Generate a report.** Tray → *Reports…* → *Generate today's report*. Markdown saves to `reports\daily-YYYYMMDD.md`.
8. **Panic-pause.** Press `Ctrl+Alt+Shift+P`. Pause checkbox flips, toast confirms.
9. **Record (optional).** Hold the trigger key > 500 ms. Recording starts, tray icon
   gains a red dot. Release → MP4 saved. Requires FFmpeg.
10. **Autostart.**
    ```powershell
    python -c "from rin.utils.autostart import enable, default_command; enable(default_command())"
    ```
    Sign out + in. RIN starts automatically.

## Building a standalone executable

```powershell
python scripts/package.py
```

Output: `dist\RIN\RIN.exe`. The build does **not** bundle FFmpeg or the ML models — those download at first use.

## Repository layout

```
RecordItNow/
├── pyproject.toml
├── README.md            (this file, English)
├── README.zh-CN.md      (Chinese version)
├── LICENSE
├── scripts/
│   ├── package.py       PyInstaller one-folder build
│   └── dev_run.ps1      Dev launcher
├── src/rin/
│   ├── app.py           QApplication wiring
│   ├── config.py        Pydantic-settings + TOML
│   ├── paths.py         %LOCALAPPDATA%\RIN helpers
│   ├── storage/         SQLAlchemy + ChromaDB
│   ├── capture/         mss + sounddevice + ffmpeg
│   ├── input/           pynput + hidapi + gesture FSM
│   ├── llm/             Copilot CLI / OpenAI / Azure providers
│   ├── analysis/        OCR + Whisper + analyzers + scheduler
│   ├── reports/         Daily / weekly markdown generator
│   ├── rag/             sentence-transformers + RAG agent
│   ├── ui/              Tray + Settings / Reports / Search windows
│   └── utils/           logging, autostart, panic hotkey
└── tests/               20 test files, 144 tests
```

## Building a release (for maintainers)

```powershell
# Run pytest + ruff and produce dist\RIN-vX.Y.Z-windows.zip
.\scripts\build_release.ps1

# Then publish:
gh release create v0.2.0 dist\RIN-v0.2.0-windows.zip --title 'RIN v0.2.0' --notes-file CHANGELOG.md
```

The legacy `scripts\package.py` (PyInstaller one-folder build) remains as
a starting point for a future v0.3.0 standalone .exe distribution but is
not part of the v0.2.0 release flow.

## License

MIT — see [`LICENSE`](LICENSE).
