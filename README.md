# RIN — Record It Now

> **Languages:** **English** · [中文](README.zh-CN.md) · **Building or contributing?** see [`docs/DEVELOPING.md`](docs/DEVELOPING.md)

[![tests](https://img.shields.io/badge/tests-553%20%2F%20553-brightgreen)](docs/DEVELOPING.md#testing)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](#requirements)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-0078D4)](#requirements)
[![CI](https://github.com/dengyanbo/RecordItNow/actions/workflows/ci.yml/badge.svg)](https://github.com/dengyanbo/RecordItNow/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/dengyanbo/RecordItNow?display_name=tag)](https://github.com/dengyanbo/RecordItNow/releases)

A Windows tray app that **captures your screen with a single button, then
lets an LLM make it searchable**.

- **Tap** your trigger → full-resolution PNG of every monitor + thumbnail
- **Hold** (> 500 ms) → MP4 + audio recording until you release
- During idle / off-hours, RIN runs **OCR + Whisper + a vision LLM** on each capture and indexes the summaries into a local vector store
- Ask **🔎 Search & Ask** in natural language (*"what was that error I saw on Tuesday?"*); a RAG agent answers with `cap-N` citations
- Generates daily / weekly Markdown reports, exportable to PDF / HTML / your Obsidian vault
- **Skills** plug in to categorize captures by your own rules — bundled defaults recognise 16-digit case IDs and 19-digit collab task IDs; auto-archive when done
- 100 % local storage. Cloud LLM only if you pick one (`copilot_cli` default needs no API key)

---

## Install

**One-click install** — single download, no Python required (~430 MB):

1. Download `RIN-vX.Y.Z-windows-installer.zip` from [GitHub Releases](https://github.com/dengyanbo/RecordItNow/releases).
2. Right-click the zip → **Extract All** (to anywhere).
3. **Double-click `Install.bat`** in the extracted folder.

That's it. The installer:

- Copies the standalone bundle to `%LOCALAPPDATA%\Programs\RIN\`
- Installs FFmpeg via winget if it isn't already on `PATH`
- Adds a Start Menu shortcut

**Common flags** — open PowerShell in the extracted folder for any of these:

```powershell
.\install.ps1 -FromBundle .\bundle -Force -Autostart            # also run on Windows login
.\install.ps1 -FromBundle .\bundle -Force -InstallDir "D:\Apps\RIN"
.\install.ps1 -FromBundle .\bundle -Force -SkipDeps             # skip FFmpeg auto-install
```

Building or contributing from source? See [`docs/DEVELOPING.md`](docs/DEVELOPING.md).

After install:

- **Launch:** Start Menu → type `RIN`, or run `%LOCALAPPDATA%\Programs\RIN\RIN.exe`.
- **Data lives under:** `%LOCALAPPDATA%\RIN\` (config, captures, reports, vector index, logs).
- **Quit:** tray menu → *Quit*, or **Ctrl+Alt+Shift+P** to pause.
- **One process at a time:** a second launch (double-clicked shortcut, autostart re-fire) detects the running instance and exits with a tray-pointer popup — no duplicate hotkeys or DB writers.

## Updating

1. Download the newest `RIN-vX.Y.Z-windows-installer.zip` from the
   [Releases page](https://github.com/dengyanbo/RecordItNow/releases).
2. Quit RIN from the tray (right-click the system-tray icon → Quit).
3. Extract the zip and double-click `Install.bat`.

Your captures, database, logs and downloaded models live in
`%LOCALAPPDATA%\RIN\` and are **kept across updates**.

---

## Screenshots

| Settings (light) | Reports (light) | Search & Ask (light) |
| :---: | :---: | :---: |
| ![](docs/screenshots/after/settings_light.png) | ![](docs/screenshots/after/reports_light.png) | ![](docs/screenshots/after/search_light.png) |
| **Settings (dark)** | **Reports (dark)** | **Search & Ask (dark)** |
| ![](docs/screenshots/after/settings_dark.png) | ![](docs/screenshots/after/reports_dark.png) | ![](docs/screenshots/after/search_dark.png) |

> Theme follows Windows by default; override at Settings → Appearance,
> along with four accent colors and two density modes.

---

## Quick tour

| Step | Action | What happens |
| --- | --- | --- |
| 1 | **Settings → Trigger → Learn new button**, press any key (e.g. F12) | Binding saved to `config.toml` |
| 2 | Tap that key from anywhere in Windows | Multi-monitor PNG + 240×135 thumbnail saved |
| 3 | Hold the key > 500 ms | MP4 video starts; red dot pulses on the tray icon. Release to stop. |
| 4 | Tray → 🧠 *Analyze now* | OCR + LLM summarise every recent capture; toasts report progress |
| 5 | Tray → 🔎 *Search…* | Type a query → semantic hits. Ask a question → agent answers with `cap-N` citations |
| 6 | Tray → 📄 *Reports…* → *Today* | Daily Markdown saved; export PDF / HTML from the toolbar |
| 7 | Settings → **Skills** → enable *Support tickets* | Auto-groups captures by 16-digit case ID / 19-digit collab task ID; archives when "Status: Closed" appears |
| 8 | `Ctrl + Alt + Shift + P` | Panic-pause hotkey (RAM-only; persistent pause lives in Settings → Privacy) |

---

## Features

| Area | Capabilities |
| --- | --- |
| **Trigger** | Bind any keyboard key, mouse button, or HID / Bluetooth button via "learn next press" |
| **Capture** | Multi-monitor PNG + thumbnail JPG sidecar, per-monitor MP4 video, optional DirectShow audio mux, optional 5-second voice quick-note |
| **Storage** | SQLite (WAL + foreign keys), ChromaDB for vectors, FTS5 for report search, dated file tree, configurable retention |
| **LLM providers** | GitHub Copilot CLI (default, no API key) · OpenAI · Azure OpenAI |
| **Analysis** | Hourly background job gated by working hours OR idle, with OCR + Whisper + vision LLM. Languages configurable. |
| **Skills** | Pluggable categorization. Bundled `support_ticket` recognises 16-digit case IDs + 19-digit collab task IDs out of the box, archives on resolution. Drop your own under `%LOCALAPPDATA%\RIN\skills\`. |
| **Topics & PoIs** | Track projects/customers/people as Points of Interest; reports grouped per PoI |
| **Reports** | Daily / weekly Markdown with FTS5 search across history. Export PDF / HTML. Optional Obsidian vault target with YAML front-matter. |
| **RAG search** | Semantic search across captures with cited answers from a RAG agent |
| **Privacy** | App blacklist (skip-capture by foreground window), pause toggle + timed pauses, optional AES-256 at-rest encryption via Windows DPAPI |
| **Theming** | Fluent-2-calibrated UI; light / dark / auto-follow-Windows; four accent colors; two density modes |
| **Calendar integration (optional)** | Outlook (MS Graph) + Google Calendar — daily reports gain a `## Calendar` section |
| **Diagnostics** | One-click redacted diagnostic zip (config + logs + env, no captures / no secrets) for support cases |

---

## Finding & creating Points of Interest (PoIs)

PoIs are the topics RIN groups your captures by (a project, a customer,
an incident, a person — anything you'd want a report section for).
You don't have to write them by hand — RIN now offers four layers of
help, in *Settings → Topics & PoIs* unless noted.

### 1. Passive — RIN watches for you

| Tool | Where | What it does |
| --- | --- | --- |
| **Suggested PoIs** table | Top of *Topics & PoIs* tab | Surfaces keywords / IDs / domains that keep recurring in your captures but aren't tracked yet. Click **Accept** to turn one into a real PoI (or **Reject** to dismiss it). |
| **Active-PoI decay + noise filter** | Background, automatic | PoIs that haven't matched in *N* days get demoted to "dormant" so the suggestion table stays focused on what you're actually working on now. |

### 2. Guided — a few clicks, RIN drafts the PoI

| Tool | Where | What it does |
| --- | --- | --- |
| **Create PoI from capture…** | Button on *Topics & PoIs* tab | Pick a recent capture → RIN extracts candidate regex / phrases / domain signals from its OCR text and **pre-fills the PoI editor**. You usually just rename and save. |
| **Persona starter packs** | Dropdown at the top of the PoI wizard | One-click templates for `Software Engineer`, `Customer Success`, `Researcher / Student`, `Engineering Manager / Lead`. Skips the blank-page paralysis. |
| **Live regex preview** | Right pane of the PoI editor | While you type a regex / phrase, RIN runs it against your recent captures **as you type** and shows hit counts + evidence snippets. Syntax errors and zero-hit patterns are flagged immediately. |
| **💬 Chat intake (LLM)** | Button in PoI wizard (requires an LLM provider) | Describe the PoI in plain language ("track every Incident ticket I touch"); the LLM proposes regex / phrases / domains and fills the editor for you. |
| **Diagnose…** | Per-row button in the My PoIs table | Tells you *why* a PoI isn't matching, *which captures* it did match, and suggests fixes. |

### 3. Expert — write code when declarative isn't enough

| Tool | Where | What it does |
| --- | --- | --- |
| `rin skill scaffold <name>` | Command line | Generates a complete `skill.py` template (with `Config`, `detect()`, metadata) under `%LOCALAPPDATA%\RIN\skills\<name>\`. |
| `rin skill validate <path>` | Command line | Pre-flights your skill without booting RIN: checks the `SKILL` instance, `Config` validity, `detect()` signature, name collisions. Reports ✓ / ✗ per check. |
| **Convert PoI to Skill** | *Convert…* column in the My PoIs table | Promotes a mature declarative PoI into a hand-written `skill.py` so you can add Python logic (API calls, NLP, DB lookups). The original PoI is removed from `[skills.topic]` automatically. |

> See [`docs/skills.md`](docs/skills.md) for the full Skill plugin recipe.

### Where the PoIs show up

PoIs aren't just labels — they drive the analysis and search pipeline:

- **Pre-classification** runs *before* summarization so captures matching
  a PoI aren't washed out by the general daily roll-up.
- **Reports** dedicate a structured section to each active PoI rather
  than mixing everything into one paragraph.
- **🔎 Search & Ask** uses PoI buckets as first-class filters; ask
  *"what did I do for INC0012345 last week?"* and the RAG agent
  retrieves and stitches the answer in temporal order.

**Suggested first run:** open the Suggested PoIs table → click *Accept* on
one or two → if you want more structure, pick a persona pack → tune with
the live regex preview → if a PoI underperforms, click *Diagnose…* before
reaching for *Convert to Skill*.

---

## How it works

```
┌─────────────────────────────────────────────────────────────────────────┐
│  System tray (PySide6) — Capture · Record · Reports · Search · Settings │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
   ┌───────────────────────────┼───────────────────────────────┐
   ▼                           ▼                               ▼
 Input gesture            Capture service                  Schedulers
 (tap / hold FSM,         (mss + ffmpeg)                   (APScheduler:
  pynput + hidapi)              │                            hourly analysis,
   │                            │                            daily reports,
   │                            │                            bucket archive)
   └──────────────► SQLite + ChromaDB + dated file tree ◄────┘
                                │
                  ┌─────────────┼─────────────┐
                  ▼             ▼             ▼
             Analysis        Skills      RAG agent
             OCR+Whisper    detect →     embed → retrieve
             vision LLM     bucket       → cited answer
                  │             │             │
                  └────► Markdown reports + archives ◄────┘
```

Pluggable everywhere: **LLM provider**, **skills** for categorization,
and **reports backends** (Markdown / PDF / HTML / Obsidian).

Want sequence diagrams + per-module rationale? See
[`docs/architecture.md`](docs/architecture.md). Hit a problem? See
[`docs/troubleshooting.md`](docs/troubleshooting.md).

---

## Requirements

- **Windows 10 (1809+) or Windows 11**
- ~2 GB free disk for Python + FFmpeg + ML model caches
- One of:
  - **GitHub Copilot CLI** (default; no API key needed) — `winget install GitHub.cli` + `gh extension install github/gh-copilot`
  - **OpenAI** or **Azure OpenAI** API key (configure in Settings)

---

## Project status

- Current: **v0.9.1** (released 2026-06-09)
- **553 / 553 pytest** pass · ruff clean
- CI green on Python 3.11 + 3.12 on `windows-latest`
- Full release history: [`docs/CHANGELOG.md`](docs/CHANGELOG.md)
- Want to contribute or extend? Read [`docs/DEVELOPING.md`](docs/DEVELOPING.md)
- Security concerns: [`.github/SECURITY.md`](.github/SECURITY.md)

## License

MIT — see [`LICENSE`](LICENSE). Third-party attributions in
[`NOTICE`](NOTICE). Notable runtime deps and licenses:

- **PySide6 / shiboken6** — LGPL-3.0 (dynamic link)
- **Microsoft Fluent UI System Icons** — MIT (bundled SVGs)
- **ChromaDB, sentence-transformers, faster-whisper, RapidOCR** — Apache 2.0 / MIT
- **mss, pynput, hidapi, ffmpeg** — Apache 2.0 / LGPL (subprocess only)
