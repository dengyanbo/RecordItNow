# RIN — Record It Now

> **Languages:** **English** · [中文](README.zh-CN.md)

[![tests](https://img.shields.io/badge/tests-203%20%2F%20203-brightgreen)](#testing)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](#requirements)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-0078D4)](#requirements)
[![CI](https://github.com/dengyanbo/RecordItNow/actions/workflows/ci.yml/badge.svg)](https://github.com/dengyanbo/RecordItNow/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/dengyanbo/RecordItNow?display_name=tag)](https://github.com/dengyanbo/RecordItNow/releases)

A Windows tray app that **captures your screen with a single button, then
lets an LLM make it searchable**.

- **Tap** your trigger → full-resolution PNG of every monitor.
- **Hold** (> 500 ms) → MP4 + audio recording until you release.
- During idle / off-hours, RIN runs **OCR + Whisper + a vision LLM** on each
  capture, persists the summary, and indexes it into a local vector store.
- Ask `RIN — Search & Ask` in natural language ("what was that error I saw
  on Tuesday?"); a RAG agent answers with `cap-N` citations.
- Generates daily / weekly Markdown reports.
- 100 % local storage. Cloud LLM only if you pick one (`copilot_cli` default
  needs no API key).

---

## 📑 Table of contents

- [Screenshots](#screenshots)
- [Install (end users)](#install-end-users)
- [Quick tour](#quick-tour)
- [Features](#features)
- [How it works (architecture)](#how-it-works-architecture)
- 🤖 **[For AI agents working on this codebase](#-for-ai-agents-working-on-this-codebase)** — module map, data flow, decision log, common tasks
- [Requirements](#requirements)
- [Development](#development)
- [Testing](#testing)
- [Smoke-test checklist](#smoke-test-checklist)
- [Building a release (maintainers)](#building-a-release-maintainers)
- [Updating / Uninstalling](#updating--uninstalling)
- [Project status & changelog](#project-status--changelog)
- [License](#license)

---

## Screenshots

| Settings (light) | Reports (light) | Search & Ask (light) |
| :--- | :--- | :--- |
| ![](docs/screenshots/after/settings_light.png) | ![](docs/screenshots/after/reports_light.png) | ![](docs/screenshots/after/search_light.png) |
| **Settings (dark)** | **Reports (dark)** | **Search & Ask (dark)** |
| ![](docs/screenshots/after/settings_dark.png) | ![](docs/screenshots/after/reports_dark.png) | ![](docs/screenshots/after/search_dark.png) |

> Auto-follows Windows light / dark mode by default. Manually overridable in
> Settings → Appearance, along with four accent colors and two density modes.

---

## Install (end users)

1. Download the latest `RIN-vX.Y.Z-windows.zip` from
   [GitHub Releases](https://github.com/dengyanbo/RecordItNow/releases).
2. Right-click → *Extract All*.
3. Right-click `install.ps1` → **Run with PowerShell**.

That single script provisions Python 3.12, FFmpeg, the GitHub Copilot CLI,
and every Python dependency RIN needs.

```powershell
.\install.ps1                       # default install
.\install.ps1 -Prefetch             # also pre-download ~1 GB of ML models
.\install.ps1 -Autostart            # also start on Windows login
.\install.ps1 -InstallDir D:\Apps\RIN
.\install.ps1 -SkipDeps             # assume Python/FFmpeg/Copilot already on PATH
.\install.ps1 -Force                # overwrite an existing install
```

After install:
- **Launch:** Start Menu → type `RIN`, or run `pythonw.exe -m rin`.
- **Data lives under:** `%LOCALAPPDATA%\RIN\`.
- **Logs:** `%LOCALAPPDATA%\RIN\logs\rin.log` (rolling 10 MB).
- **Update:** re-run `install.ps1`.
- **Quit cleanly:** tray menu → *Quit*, or **Ctrl+C** in the launching terminal.

---

## Quick tour

| Step | Action | What happens |
| --- | --- | --- |
| 1 | **Settings → Trigger → Learn new button**, press any key (e.g. F12) | Binding is saved to `config.toml` |
| 2 | Tap that key from anywhere in Windows | A multi-monitor PNG is captured to `captures\YYYY\MM\DD\<ts>-shot\` |
| 3 | Hold the key > 500 ms | An MP4 video starts; a red dot pulses on the tray icon. Release to stop. |
| 4 | Tray → 🧠 *Analyze now* | RapidOCR + Copilot CLI (or your LLM provider) read every recent capture; toasts report progress. |
| 5 | Tray → 🔎 *Search…* | Type a query → semantic hits appear as cards. Ask a question → agent answers with `cap-N` citations. |
| 6 | Tray → 📄 *Reports…* → *Generate today's report* | Daily Markdown report saved to `reports\daily-YYYYMMDD.md`, rendered with theme-aware HTML. |
| 7 | `Ctrl + Alt + Shift + P` | Panic-pause toggle: ignores triggers until you press it again. |

---

## Features

| Area | Capabilities |
| --- | --- |
| **Trigger** | Bind any keyboard key, mouse button, or HID / Bluetooth button via a "learn next press" flow |
| **Capture** | Multi-monitor PNG screenshots (mss) and per-monitor MP4 video (ffmpeg `gdigrab`), optional DirectShow audio mux |
| **Storage** | SQLite (WAL + foreign keys) for metadata, ChromaDB for vectors, dated file tree for raw media, configurable retention |
| **LLM providers** | GitHub Copilot CLI (default, no API key needed) · OpenAI · Azure OpenAI — pluggable, picked from Settings |
| **Analysis** | Hourly background job gated by working hours OR idle detection; runs RapidOCR + faster-whisper + a vision LLM |
| **Reports** | Daily / weekly Markdown summaries with Highlights / Apps / Topics / Action items sections |
| **RAG search** | Semantic search across captures with cited answers from a retrieval-augmented agent |
| **Privacy** | Panic-pause hotkey, no network calls unless you pick a cloud LLM, all data lives under `%LOCALAPPDATA%\RIN\` |
| **Theming** | Fluent-2-calibrated UI; light / dark / auto-follow-Windows; four accent colors; two density modes |

---

## How it works (architecture)

> Looking for a deeper dive (sequence diagrams, process model, design rationale)?
> See [`docs/architecture.md`](docs/architecture.md). Hit a problem? See
> [`docs/troubleshooting.md`](docs/troubleshooting.md).

```
┌─────────────────────────────────────────────────────────────────────────┐
│  System tray (PySide6)                                                  │
│  Capture · Record · Reports · Search · Settings · Pause · Quit          │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
   ┌───────────────────────────┼───────────────────────────────┐
   ▼                           ▼                               ▼
 Input gesture            Capture service                  Schedulers
 (tap / hold FSM,         (mss + ffmpeg)                   (APScheduler:
  pynput + hidapi)             │                            hourly analysis,
   │                           │                            daily reports)
   └──────────────► SQLite + ChromaDB + dated file tree ◄────┘
                               │
                  ┌────────────┴────────────┐
                  ▼                         ▼
             Analysis pipeline           RAG agent
             OCR + Whisper +             sentence-transformers +
             vision LLM call             retrieve + chat
                  │                         │
                  └───────► Markdown report generator ◄──┘
```

---

## 🤖 For AI agents working on this codebase

> If you are an LLM or coding agent helping a user maintain RIN, **this
> section is your entry point**. Read it first — the rest of the README is
> mostly for end users.

### Repository at a glance

| Path | Size | What it does |
| --- | --- | --- |
| `src/rin/app.py` | tiny | `QApplication` bootstrap + SIGINT handler + theme apply |
| `src/rin/config.py` | medium | `pydantic` schema for `%LOCALAPPDATA%\RIN\config.toml`. All user-mutable settings live here. |
| `src/rin/paths.py` | tiny | `%LOCALAPPDATA%\RIN\*` directory helpers. Override root via `RIN_DATA_DIR` env var (used by tests). |
| `src/rin/storage/` | 439 L | SQLAlchemy models + Chroma client + retention. **Do not write raw SQL** unless you add a migration via `migrations.py`. |
| `src/rin/capture/` | 710 L | `mss` screenshots, `ffmpeg` subprocess recorder, `sounddevice` audio, `CaptureService` orchestrator. |
| `src/rin/input/` | 590 L | Pure-Python gesture state machine + Qt recognizer + pynput / hidapi listeners + learn-mode. |
| `src/rin/llm/` | 482 L | `Provider` ABC + `copilot_cli` / `openai` / `azure` providers + `factory.make_provider(cfg)`. |
| `src/rin/analysis/` | 727 L | OCR (rapidocr) + Whisper (faster-whisper) + keyframe extraction + summarizer + scheduler. |
| `src/rin/rag/` | 273 L | sentence-transformers embedder + ChromaDB indexer + search + Q&A agent. |
| `src/rin/reports/` | 308 L | Daily / weekly Markdown generator + APScheduler. |
| `src/rin/ui/` | 2094 L | PySide6 tray + settings + reports + search windows. `theme.py` + `style.py` own the QSS design tokens. |
| `src/rin/utils/` | 188 L | Logging (loguru), autostart (HKCU registry), panic hotkey, Windows helpers. |
| `tests/` | 40 files | 195 tests, all green. Run with `pytest -q`. |
| `scripts/` | 4 files | `install.ps1` (user installer), `build_release.ps1` (maintainer packaging), `prefetch_models.py`, `dev_run.ps1`. |

### Data flow: one tap to a searchable answer

```
1. User taps F12
   ↓
2. pynput listener thread emits InputEvent
   ↓ (Qt.QueuedConnection)
3. InputManager → GestureStateMachine (pure Python)
   ↓ shot_requested Qt signal
4. TrayApp queues _on_shot_requested on QThreadPool
   ↓
5. CaptureService.take_screenshot()
   ↓
6. mss grabs every monitor → PNGs in captures\YYYY\MM\DD\<ts>-shot\
   ↓
7. SQLAlchemy commits Capture row (status="captured")

   (later, hourly or via "Analyze now")

8. AnalysisScheduler._tick acquires non-blocking Lock
   ↓
9. analyze_pending iterates Capture rows with status="captured"
   ↓
10. For each: RapidOCR extracts text → Copilot CLI vision summary
    ↓
11. build_summary asks LLM for a final paragraph
    ↓
12. SQLAlchemy commits Analysis row + flips status to "analyzed"
    ↓
13. sentence-transformers embedder writes vector to ChromaDB

   (later, user opens Search & Ask)

14. User types question
    ↓
15. RAGAgent.ask embeds question → top-k ChromaDB hits
    ↓
16. Constructs [SYSTEM]/[USER] prompt with snippets
    ↓
17. Copilot CLI generates answer with cap-N citations
    ↓
18. SearchWindow renders chat bubble with citation strip
```

### Decision log (why things are the way they are)

| Decision | Why | Where to verify |
| --- | --- | --- |
| **PySide6**, not PyQt6 / Tkinter / Tauri | LGPL allows binary redistribution of an MIT app via dynamic linking; mature; one tool covers tray + windows | `pyproject.toml`, `NOTICE` |
| **No `PySide6-Fluent-Widgets`** | It is GPL-3.0 — would force RIN into GPL. We hand-rolled a Fluent-inspired stylesheet in `ui/style.py` instead. | `ui/style.py`, plan.md decision table |
| **Bundle Microsoft Fluent UI System Icons (MIT)** as SVGs in `src/rin/ui/assets/` | MIT-clean, ship with the wheel, no runtime download | `NOTICE`, `src/rin/ui/assets/` |
| **GitHub Copilot CLI** as default LLM provider, not OpenAI | No API key required for the typical user; vision via `--attachment`; you can switch in Settings | `src/rin/llm/copilot_cli.py` |
| **Claude Opus 4.7 1M-internal at high reasoning** as default model | Best quality + 1M context for long videos; user can change in Settings | `src/rin/config.py:LLMProviderConfig` |
| **ChromaDB**, not pinecone / qdrant / pgvector | Local-only by default, zero server, embeds in our process | `src/rin/storage/vector_store.py` |
| **sentence-transformers all-MiniLM-L6-v2** | 90 MB; fast on CPU; good enough for our small corpus | `src/rin/rag/embedder.py` |
| **faster-whisper small** | int8 quantized; runs on CPU at real-time-ish speeds for audio transcripts | `src/rin/analysis/transcribe.py` |
| **RapidOCR ONNX**, not Tesseract / PaddleOCR | Bundled ONNX models, no native install needed, MIT/Apache | `src/rin/analysis/ocr.py` |
| **SQLAlchemy 2.0 + Alembic-less migrations** | Migrations are rare and small; we track `PRAGMA user_version` manually | `src/rin/storage/migrations.py` |
| **`ffmpeg` invoked as subprocess**, not via `av` / `imageio-ffmpeg` | Long-running recordings work best with ffmpeg's own gdigrab+dshow muxing; we send `q` for graceful stop | `src/rin/capture/recorder.py` |
| **`stderr=DEVNULL`** on ffmpeg | Without this, a long recording fills the 64 KB Windows pipe buffer and deadlocks ffmpeg. Reviewed in v0.3.1. | `src/rin/capture/recorder.py` |
| **Subprocesses use `encoding="utf-8", errors="replace"`** | Windows default is cp1252, blows up on Chinese / emoji ffmpeg output. Fixed in v0.1.1. | `src/rin/llm/copilot_cli.py`, `src/rin/analysis/keyframes.py` |
| **APScheduler `BackgroundScheduler`**, gated by `threading.Lock` | Manual "Analyze now" can race with the hourly tick; non-blocking lock skips duplicates. Reviewed in v0.3.1. | `src/rin/analysis/scheduler.py` |
| **No PyInstaller exe in v0.3.x** | install.ps1 keeps the zip < 200 KB and we avoid Qt-in-onefile pain | `scripts/install.ps1`, `scripts/package.py` (legacy) |
| **Bilingual docs (en / zh)** | Author + many users are bilingual Chinese / English | `README.md`, `README.zh-CN.md` |

### Common tasks for an agent

These are the most common changes; each links to the file that contains the
canonical example.

#### Add a new LLM provider

1. Add a new module under `src/rin/llm/` that subclasses
   `rin.llm.base.Provider` (see `openai_provider.py` for a complete example).
2. Implement `analyze_image`, `analyze_text`, `chat`, and `capabilities`.
3. Register it in `src/rin/llm/factory.py:make_provider`.
4. Add a `Literal` choice to `LLMProviderConfig.name` in `src/rin/config.py`.
5. Add the provider name to `LLM_NAMES` in `src/rin/ui/settings_dialog.py`.
6. Write a unit test that injects a fake client (see `tests/test_llm_openai.py`).

#### Add a new settings field

1. Edit the relevant `BaseModel` in `src/rin/config.py` (e.g. `CaptureConfig`).
   Use `pydantic.Field` defaults so old `config.toml` files keep working.
2. Add a control to the matching `_build_*_tab` in
   `src/rin/ui/settings_dialog.py` using `self._label(...)` for the label and
   `self._form()` for the layout.
3. Wire load + save in `load_from_config` and `_on_save`.
4. Extend `tests/test_ui_settings.py:test_dialog_save_round_trip` to cover the new field.

#### Add a new analysis step

1. Create a module under `src/rin/analysis/` that exposes a pure function.
2. Plug it into the orchestrator in
   `src/rin/analysis/summarizer.py:analyze_capture` (screenshot path) or
   `src/rin/analysis/video_analyzer.py:analyze_video` (video path).
3. Add a unit test using the dependency-injection points already wired up
   (`analyze_image_fn`, `extract_keyframes_fn`, `transcribe_fn`).

#### Change the look / theme

- Colors live in `src/rin/ui/theme.py`. Edit `LIGHT` / `DARK` dataclasses or
  `ACCENTS`. The `tests/test_ui_theme.py` suite enforces WCAG AA contrast.
- Sizes + selectors live in `src/rin/ui/style.py:palette_to_qss`. The `[role="..."]`
  Qt properties are how widgets opt into styling (e.g. `widget.setProperty("primary", True)`).

#### Ship a release

```powershell
# 1. Bump version in src/rin/__init__.py + pyproject.toml
# 2. Append a section to CHANGELOG.md
# 3. Verify
ruff check src tests scripts
pytest -q

# 4. Build the zip
.\scripts\build_release.ps1

# 5. Tag + release
git add -A
git commit -m "vX.Y.Z — <one-line summary>"
git tag -a vX.Y.Z -m "RIN vX.Y.Z"
git push origin main vX.Y.Z
gh release create vX.Y.Z dist\RIN-vX.Y.Z-windows.zip --notes-file CHANGELOG.md
```

### Glossary

| Term | Meaning |
| --- | --- |
| **capture** | A row in the `captures` table — one user-triggered event (screenshot or recording) with its files |
| **cap-N** | A capture identifier rendered in RAG citations (`cap-7` = `captures.id == 7`) |
| **analysis** | The `analyses` table row containing the OCR + LLM-generated summary of a capture |
| **trigger** | The user's bound input — keyboard key, mouse button, or HID / Bluetooth button |
| **gate** | The conditional that lets the hourly analysis tick run: outside working hours OR idle |
| **provider** | An LLM backend implementing `rin.llm.base.Provider`. Three ship today: copilot_cli (default), openai, azure |
| **role** | A Qt property on a widget that opts it into stylesheet rules. Examples: `primary`, `flat`, `muted`, `field-label`, `caption`, `nav`, `cards`, `empty-state-title` |

### Files an agent should rarely touch

- `src/rin/ui/assets/*.svg` — Microsoft Fluent System Icons; replacements must come from the upstream MIT repo
- `LICENSE` — MIT, unchanged
- `NOTICE` — needs an update only when a new bundled asset / dep introduces an attribution requirement
- `.gitignore` — already excludes `.venv`, `dist`, `build`, `__pycache__`, sqlite working files, `logs`

### What to read first when starting a task

| If you want to … | Read |
| --- | --- |
| Understand the runtime entry point | `src/rin/app.py` and `src/rin/__main__.py` |
| Trace one captured screenshot end-to-end | the **Data flow** diagram above, then `src/rin/capture/screenshot.py` + `src/rin/analysis/summarizer.py` |
| Reason about subprocess lifecycles | `src/rin/capture/recorder.py` and `src/rin/llm/copilot_cli.py` |
| Reason about threading + Qt signals | `src/rin/input/manager.py` and `src/rin/ui/tray.py` |
| See past design choices | `CHANGELOG.md` (especially v0.3.1's review notes) |

---

## Requirements

| Tool | Version | Notes |
| --- | --- | --- |
| Windows | 10 or 11 | Phase 0 is portable, capture / input / panic-pause are Windows-only |
| Python | 3.11 / 3.12 / 3.13 | Installer fetches Python 3.12 via winget |
| FFmpeg | latest | Required for video recording + keyframe extraction. `winget install Gyan.FFmpeg`. Open a fresh PowerShell after install to pick up the updated PATH. |
| GitHub Copilot CLI | latest | Default LLM provider. Alternatives: OpenAI API key, Azure OpenAI. |

---

## Development

```powershell
# 1. Install uv (fast Python package manager)
winget install --id=astral-sh.uv -e

# 2. Create a virtual environment and install RIN with dev extras
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[all,dev]"

# 3. Boot the tray app
python -m rin

# Smoke / lint / tests
python -m rin --smoke
ruff check src tests scripts
pytest -q
```

Optional extras (declared in `pyproject.toml`):

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

---

## Testing

```powershell
pytest -q           # all 195 tests, ~60-90 s on a warm cache
ruff check src tests scripts
python -m rin --smoke
```

Tests live under `tests/` and are organized one file per subsystem
(`test_capture_recorder.py`, `test_rag_agent.py`, …). Heavy I/O is mocked
via dependency-injection points already wired into each module.

CI runs on every push and PR via [`.github/workflows/ci.yml`](.github/workflows/ci.yml)
(ruff + pytest + smoke on Python 3.11 and 3.12 on `windows-latest`). Tagged
releases (`v*.*.*`) build the release zip automatically via
[`.github/workflows/release.yml`](.github/workflows/release.yml).

---

## Smoke-test checklist

After installing, walk this sequence in order:

1. **Boot.** `python -m rin --smoke` → exits 0, `logs\rin.log` shows startup.
2. **Launch tray.** `python -m rin` → tray icon appears. Press **Ctrl+C** in the terminal to confirm clean shutdown.
3. **Learn trigger.** Settings → Trigger → *Learn new button* → tap any key.
4. **Take a screenshot.** Tray → *📸 Capture now*. PNG appears under `captures\YYYY\MM\DD\<ts>-shot\`.
5. **Analyze.** Tray → *🧠 Analyze now*. Progress toasts; final toast confirms `Analysis complete — N/N`.
6. **Search.** Tray → *🔎 Search…* → type a query. Hits show; ask a question, agent answers with `cap-N` citations.
7. **Generate a report.** Tray → *📄 Reports…* → *Generate today's report*. Markdown saves to `reports\daily-YYYYMMDD.md`.
8. **Panic-pause.** Press `Ctrl + Alt + Shift + P`. Pause toggles, toast confirms.
9. **Record (optional).** Hold the trigger key > 500 ms; release → MP4 saved. Requires FFmpeg.
10. **Autostart.**
    ```powershell
    python -c "from rin.utils.autostart import enable, default_command; enable(default_command())"
    ```
    Sign out + in. RIN starts automatically. Disable with `disable()`.

---

## Building a release (maintainers)

```powershell
.\scripts\build_release.ps1        # produces dist\RIN-vX.Y.Z-windows.zip
```

The legacy `scripts\package.py` (PyInstaller one-folder build) remains as
a starting point for a future v0.4.0+ standalone `.exe` distribution but
is not part of the current release flow.

---

## Updating / Uninstalling

### Updating

Re-run `install.ps1` over the existing install. It prompts before overwriting
(use `-Force` to skip). Data under `%LOCALAPPDATA%\RIN` is preserved.

### Uninstalling

```powershell
# 1. Disable autostart (if it was enabled)
& "$env:LOCALAPPDATA\Programs\RIN\.venv\Scripts\python.exe" -c "from rin.utils.autostart import disable; disable()"

# 2. Remove the program
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Programs\RIN"

# 3. (Optional) wipe captures + database + ML model cache
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\RIN"

# 4. (Optional) remove the Start Menu shortcut
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\RIN.lnk"
```

---

## Project status & changelog

- Current: **v0.4.1** (released 2026-05-28)
- Test totals: **203 / 203 pytest pass**, ruff clean
- Build / lint: green on Windows 10 / 11 + Python 3.11 / 3.12
- CI runs on every push: [`.github/workflows/ci.yml`](.github/workflows/ci.yml)
- Full release history: [`CHANGELOG.md`](CHANGELOG.md)
- Want to contribute? See [`CONTRIBUTING.md`](CONTRIBUTING.md) and
  [`AGENTS.md`](AGENTS.md). Security concerns: [`SECURITY.md`](SECURITY.md).

---

## License

MIT — see [`LICENSE`](LICENSE).

Third-party attributions are listed in [`NOTICE`](NOTICE). The most notable
runtime dependencies and their licenses:

- PySide6 / shiboken6 — LGPL-3.0 (dynamic link)
- ChromaDB · sentence-transformers · transformers · rapidocr-onnxruntime · openai — Apache-2.0
- SQLAlchemy · mss · faster-whisper · loguru · keyboard · pyqt-keyring · Pillow · APScheduler — MIT or BSD
- Fluent UI System Icons (`src/rin/ui/assets/*.svg`) — Microsoft, MIT
- FFmpeg — LGPL / GPL, **not bundled**; installed separately by `install.ps1` via winget

RIN does not invoke any cloud service unless you explicitly configure an
LLM provider that needs network access. With the default `copilot_cli`
provider, all traffic is mediated by GitHub Copilot CLI under your existing
GitHub authentication.
