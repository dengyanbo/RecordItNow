# Developing RIN

> This document is the deep guide for **humans contributing code** and
> **AI coding agents** working on the RIN codebase. If you only want to
> *use* RIN, [`README.md`](README.md) is enough; come here when you're
> about to read or change source files.
>
> 🤖 **AI agents:** read this whole file first. It is the canonical
> entry point. The conventions in [`AGENTS.md`](AGENTS.md) are
> non-negotiable.

## Table of contents

1. [Repository at a glance](#repository-at-a-glance)
2. [Data flow — one tap to a searchable answer](#data-flow--one-tap-to-a-searchable-answer)
3. [Decision log](#decision-log)
4. [Common tasks](#common-tasks)
   - [Add a new LLM provider](#add-a-new-llm-provider)
   - [Add a new settings field](#add-a-new-settings-field)
   - [Add a new analysis step](#add-a-new-analysis-step)
   - [Add a new bundled skill](#add-a-new-bundled-skill)
   - [Change the look / theme](#change-the-look--theme)
   - [Ship a release](#ship-a-release)
5. [Glossary](#glossary)
6. [Files an agent should rarely touch](#files-an-agent-should-rarely-touch)
7. [What to read first when starting a task](#what-to-read-first-when-starting-a-task)
8. [Development workflow](#development-workflow)
9. [Testing](#testing)
10. [Smoke-test checklist](#smoke-test-checklist)
11. [Building a release](#building-a-release)
12. [Deeper architectural reading](#deeper-architectural-reading)

---

## Repository at a glance

| Path | What it does |
| --- | --- |
| `src/rin/app.py` | `QApplication` bootstrap + SIGINT handler + theme apply + first-run wizard gate + telemetry install |
| `src/rin/config.py` | `pydantic` schema for `%LOCALAPPDATA%\RIN\config.toml`. All user-mutable settings live here. |
| `src/rin/paths.py` | `%LOCALAPPDATA%\RIN\*` directory helpers. Override root via `RIN_DATA_DIR` env var (used by tests). |
| `src/rin/storage/` | SQLAlchemy models + Chroma client + retention + FTS5-backed report search. **Do not write raw SQL** unless you add a migration via `migrations.py`. |
| `src/rin/capture/` | `mss` screenshots, `ffmpeg` subprocess recorder, `sounddevice` audio (incl. quick-note), `CaptureService` orchestrator, privacy blacklist + at-rest encryption hook. |
| `src/rin/input/` | Gesture state machine + Qt recognizer + pynput / hidapi listeners + learn-mode + reserved-key warnings. |
| `src/rin/llm/` | `Provider` ABC + `copilot_cli` / `openai` / `azure` providers + `factory.make_provider(cfg)`. |
| `src/rin/analysis/` | OCR (rapidocr) + Whisper (faster-whisper) + keyframe extraction + summarizer + scheduler. |
| `src/rin/skills/` | Pluggable categorization. `Skill` ABC + registry + pipeline + `BucketScheduler`. Bundled skills: `support_ticket`, `topic`. |
| `src/rin/skills/builtin/topic/` | Bundled generic PoI skill: declarative topics, keyword / regex / alias matching, optional LLM judge, auto-archive rules. |
| `src/rin/poi/` | PoI discovery + candidate persistence. Mines recent captures for suggested topics and writes to `poi_candidates`. |
| `src/rin/ui/poi_tab.py` | Settings tab for tracked PoIs + candidate accept/reject + manual add/edit/archive actions. |
| `src/rin/ui/poi_wizard.py` | First-run / on-demand PoI onboarding wizard: Welcome → Declare → Discovery → Confirm. |
| `src/rin/rag/` | sentence-transformers embedder + ChromaDB indexer + search + Q&A agent. |
| `src/rin/reports/` | Daily / weekly Markdown generator + APScheduler + FTS5 search + PDF/HTML export + Outlook/Google Calendar integrations. |
| `src/rin/ui/` | PySide6 tray + Settings shell/tabs + Reports + Search + first-run Wizard + Spinner/BusyOverlay progress widgets. `theme.py` + `style.py` own the QSS design tokens. |
| `src/rin/utils/` | Logging (loguru), autostart, panic hotkey, encryption (AES-256-GCM + DPAPI), thumbnail (PIL), data export, telemetry (Sentry), diagnostics, single-instance lock, platform_compat dispatcher. |
| `tests/` | 396 tests, all green. Run with `pytest -q`. Layout mirrors `src/rin/`. |
| `scripts/` | `install.ps1` (user installer), `build_release.ps1` (source zip), `build_exe.ps1` + `RIN.spec` (PyInstaller .exe), `prefetch_models.py`, `dev_run.ps1`, `capture_ui_screenshots.py`. |

## Data flow — one tap to a searchable answer

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
   ↓  (privacy + pause gates check here)
6. mss grabs every monitor → PNGs in captures\YYYY\MM\DD\<ts>-shot\
   plus a 240×135 JPG thumbnail sidecar
   ↓
7. SQLAlchemy commits Capture row (status="captured")

   (later, hourly or via "Analyze now")

8. AnalysisScheduler._tick acquires non-blocking Lock
   ↓
9. analyze_pending iterates Capture rows with status="captured"
   ↓
10. For each: RapidOCR extracts text → Copilot CLI vision summary
    ↓
11. build_summary asks LLM for a final paragraph; active topic names
    from `[skills.topic].topics` are prepended so tracked PoIs are
    called out explicitly when present
    ↓
12. SQLAlchemy commits Analysis row + flips status to "analyzed"
    ↓
13. sentence-transformers embedder writes vector to ChromaDB
    ↓
14. skills.pipeline.classify_capture runs every enabled Skill.detect()
    → upserts Bucket rows + inserts capture_bucket junction rows

   (later, on demand from Settings or the PoI wizard)

15. rin.poi.discovery.discover() mines recent analyses
    → repeated regex IDs / domains / title-case phrases (+ optional LLM
      batch) become `poi_candidates`
16. User accepts a candidate in Settings → it is copied into
    `[skills.topic].topics`; reject / merge decisions stay in
    `poi_candidates`

   (later, BucketScheduler tick — default every 6h)

17. Report generation consults `cfg.reports.layout`
    → `chronological` keeps the old flow
    → `per_poi` groups by tracked topic
    → `auto` flips to per-PoI when any topic touched the period
18. For each active bucket: skill.should_close(...)
    → if True: skill.render_archive(...) → reports/archives/<skill>/<key>.md
    → status='archived', closed_at + archive_path set

   (later, user opens Search & Ask)

19. User types question
    ↓
20. RAGAgent.ask embeds question → top-k ChromaDB hits
    ↓
21. Constructs [SYSTEM]/[USER] prompt with snippets
    ↓
22. Copilot CLI generates answer with cap-N citations
    ↓
23. SearchWindow renders chat bubble with citation strip
```

For sequence diagrams + the analysis pipeline's deeper "why", see
[`docs/architecture.md`](docs/architecture.md).

## Decision log

Why things are the way they are. Verify each at the cited file.

| Decision | Why | Where to verify |
| --- | --- | --- |
| **PySide6**, not PyQt6 / Tkinter / Tauri | LGPL allows binary redistribution of an MIT app via dynamic linking; mature; one tool covers tray + windows | `pyproject.toml`, `NOTICE` |
| **No `PySide6-Fluent-Widgets`** | It is GPL-3.0 — would force RIN into GPL. We hand-rolled a Fluent-inspired stylesheet in `ui/style.py` instead. | `ui/style.py` |
| **Bundle Microsoft Fluent UI System Icons (MIT)** as SVGs | MIT-clean, ship with the wheel, no runtime download. Tinted per theme via `ui/icon.tinted_icon`. | `src/rin/ui/assets/`, `NOTICE` |
| **GitHub Copilot CLI** as default LLM provider | No API key required for the typical user; vision via `--attachment`; switch in Settings | `src/rin/llm/copilot_cli.py` |
| **Claude Opus 4.7 (1M-internal, high reasoning)** as default model | Best quality + 1M context for long videos | `src/rin/config.py:LLMProviderConfig` |
| **ChromaDB** for vector store | Local-only by default, zero server, embeds in our process | `src/rin/storage/vector_store.py` |
| **sentence-transformers all-MiniLM-L6-v2** | 90 MB; fast on CPU; good enough for our small corpus | `src/rin/rag/embedder.py` |
| **faster-whisper small** (default) | int8 quantized; runs on CPU at real-time-ish speeds. User can change to large-v3 in Settings → Analysis. | `src/rin/analysis/transcribe.py` |
| **RapidOCR ONNX** | Bundled ONNX models, no native install, MIT/Apache | `src/rin/analysis/ocr.py` |
| **SQLAlchemy 2.0 + Alembic-less migrations** | Migrations are rare; we track `PRAGMA user_version` manually | `src/rin/storage/migrations.py` |
| **`ffmpeg` invoked as subprocess** | Long recordings work best with ffmpeg's own gdigrab+dshow muxing; we send `q` for graceful stop | `src/rin/capture/recorder.py` |
| **`stderr=DEVNULL` on ffmpeg** | Without this, a long recording fills the 64 KB Windows pipe buffer and deadlocks ffmpeg. Reviewed in v0.3.1. | `src/rin/capture/recorder.py` |
| **Subprocesses use `encoding="utf-8", errors="replace"`** | Windows default is cp1252, blows up on Chinese / emoji ffmpeg output. Reviewed in v0.1.1. | `src/rin/llm/copilot_cli.py`, `src/rin/analysis/keyframes.py` |
| **APScheduler `BackgroundScheduler` + `threading.Lock`** | Manual "Analyze now" can race with the hourly tick; non-blocking lock skips duplicates. Reviewed in v0.3.1. | `src/rin/analysis/scheduler.py` |
| **Skills are drop-in folders, not pip packages** | Lower friction for end-user customization; pip-installable skills (`rin-skill-*`) deferred | `src/rin/skills/registry.py`, `docs/skills.md` |
| **`SkipInfo` records every short-circuit reason** | Tray surfaces context-aware notifications (paused vs blacklist vs disk_full vs failed) instead of one generic "Screenshot failed". Reviewed in v0.7.1 (R22). | `src/rin/capture/service.py`, `src/rin/ui/tray.py` |
| **`TrayApp._prewarm_menu()` paid at boot** | Cold `sizeHint()` on an emoji-loaded `QMenu` is ~470 ms; pre-warming 250 ms after `tray.show()` drops first-click to ~4 ms. Reviewed in v0.7.1 (R21). | `src/rin/ui/tray.py` |
| **Pause moved from tray menu to Settings → Privacy** | The tray was getting cluttered; pause sits naturally next to privacy blacklist + encryption-at-rest. Panic hotkey remains. v0.7.1 (R23). | `src/rin/ui/settings_dialog.py:_build_privacy_tab` |
| **Bilingual READMEs (en / zh)** | Author + many users are bilingual Chinese / English | `README.md`, `README.zh-CN.md` |
| **R24 — New bundled `topic` skill instead of refactoring `support_ticket`** | Two different use cases — IDs are precise (regex), topics are fuzzy (keywords/LLM). Keep both. | `src/rin/skills/builtin/topic/`, `src/rin/skills/builtin/support_ticket/`, `docs/skills.md` |
| **R25 — `poi_candidates` as a separate table (not part of `buckets`)** | Buckets are confirmed by skills via `detect()`; candidates are suggestions awaiting human decision. Mixing would conflate states. | `src/rin/storage/models.py`, `src/rin/storage/migrations.py`, `src/rin/poi/` |
| **R26 — Discovery is on-demand, not in a scheduler** | Avoids unbidden LLM cost; user explicitly triggers via Settings or wizard. | `src/rin/poi/discovery.py`, `src/rin/ui/poi_tab.py`, `src/rin/ui/poi_wizard.py` |
| **R27 — `reports.layout = "auto"` default** | Backwards-compatible: users with no PoIs see no change; users with PoIs get the per-topic layout for free. | `src/rin/config.py`, `src/rin/reports/` |
| **R28 — PoI wizard auto-shown ONCE after FirstRunWizard** | Avoids nag-loop; `poi_wizard_seen=True` flag persisted; user can re-invoke from Settings. | `src/rin/app.py`, `src/rin/config.py`, `src/rin/ui/poi_wizard.py` |

## Common tasks

These are the most common changes; each links to the file that contains
the canonical example.

### Add a new LLM provider

1. Add a new module under `src/rin/llm/` that subclasses
   `rin.llm.base.Provider` (see `openai_provider.py` for a complete
   example).
2. Implement `analyze_image`, `analyze_text`, `chat`, and
   `capabilities`.
3. Register it in `src/rin/llm/factory.py:make_provider`.
4. Add a `Literal` choice to `LLMProviderConfig.name` in
   `src/rin/config.py`.
5. Add the provider name to `LLM_NAMES` in
   `src/rin/ui/settings_dialog.py`.
6. Write a unit test that injects a fake client (see
   `tests/test_llm_openai.py`).

### Add a new settings field

1. Edit the relevant `BaseModel` in `src/rin/config.py`. Use
   `pydantic.Field` defaults so old `config.toml` files keep working.
2. Add a control to the matching `_build_*_tab` in
   `src/rin/ui/settings_dialog.py` using `self._label(...)` for the
   label, `self._hint(...)` for sub-text, `self._form()` for layout,
   and `self._fixed(widget, width)` to constrain widget widths.
3. Wire load + save in `load_from_config` and `_on_save`.
4. Extend the existing settings test (or
   `tests/test_settings_new_fields.py`) to cover the new field.

### Add a new analysis step

1. Create a module under `src/rin/analysis/` that exposes a pure
   function.
2. Plug it into the orchestrator in
   `src/rin/analysis/summarizer.py:analyze_capture` (screenshot path)
   or `src/rin/analysis/video_analyzer.py:analyze_video` (video path).
3. Add a unit test using the dependency-injection points already
   wired up (`analyze_image_fn`, `extract_keyframes_fn`,
   `transcribe_fn`).

### Add a new bundled skill

1. Create a sub-package under `src/rin/skills/builtin/<name>/` with:
   - `__init__.py` that re-exports `SKILL`
   - `skill.py` containing your `Skill` subclass + a module-level
     `SKILL = MySkill()`
   - Optional Pydantic `Config` for `[skills.<name>]` TOML section
2. Implement `detect(ctx)` (mandatory), `should_close(...)`
   (optional), `render_archive(...)` (optional — default is a
   chronological dump).
3. If the skill is declarative / user-configurable, mirror the `topic`
   skill: keep the matching logic in `src/rin/skills/builtin/topic/`
   and any discovery / persistence helpers in a sibling package (for
   v0.8.0 that is `src/rin/poi/`). `support_ticket` is still the
   smallest regex-first example; `topic` is the better reference when
   you need keywords, aliases, optional LLM judging, or richer UI.
4. Add tests under `tests/test_skill_<name>.py`. Follow
   `tests/test_skills_base.py` for the patterns.
5. Document the skill in `docs/skills.md`; add a focused user guide in
   `docs/` too if the concept is end-user facing (as `topic` did with
   `docs/poi.md`).

### Change the look / theme

- Colors live in `src/rin/ui/theme.py`. Edit `LIGHT` / `DARK`
  dataclasses or `ACCENTS`. The `tests/test_ui_theme.py` suite
  enforces WCAG AA contrast.
- Sizes + selectors live in `src/rin/ui/style.py:palette_to_qss`. The
  `[role="..."]` Qt properties are how widgets opt into styling
  (e.g. `widget.setProperty("primary", True)`,
  `setProperty("role", "chip")`).
- Icons: use `ui.icon.tinted_icon(name, color)` to recolour bundled
  SVGs at render time; don't paint colors into icons.

### Ship a release

The release workflow at `.github/workflows/release.yml` runs the
source-zip build automatically on tag push. To produce the
`.exe` bundle that ships alongside it, you build manually.

```powershell
# 1. Bump version in src/rin/__init__.py + pyproject.toml
# 2. Append a section to CHANGELOG.md
# 3. Verify
ruff check src tests scripts
pytest -q

# 4. (Optional) build the standalone .exe bundle (~13 min, ~423 MB zip)
.\scripts\build_exe.ps1

# 5. Tag + push — CI publishes the source zip automatically
git add -A
git commit -m "vX.Y.Z — <one-line summary>"
git tag -a vX.Y.Z -m "RIN vX.Y.Z"
git push origin main vX.Y.Z

# 6. (Optional) upload the .exe zip as an additional asset
gh release upload vX.Y.Z dist\RIN-vX.Y.Z-windows-installer.zip
```

## Glossary

| Term | Meaning |
| --- | --- |
| **analysis** | The `analyses` table row containing OCR + LLM-generated summary of a capture |
| **archive** | A Markdown file under `reports/archives/<skill>/<key>.md` produced when a bucket closes |
| **bucket** | A row in the `buckets` table created by a skill's `detect()`; groups N captures under one `(skill_name, key)` |
| **candidate** | A PoI suggestion produced by the discovery service. Lives in the `poi_candidates` table with `status=pending|accepted|rejected|merged`. |
| **cap-N** | A capture identifier rendered in RAG / archive citations (`cap-7` = `captures.id == 7`) |
| **capture** | A row in the `captures` table — one user-triggered event (screenshot or recording) with its files |
| **density** | `comfortable` (default) vs `compact` — picks padding values in `palette_to_qss` |
| **discovery** | On-demand mining of recent captures for candidate PoIs. Runs from `rin.poi.discovery.discover()` or `python -m rin poi-discover`. |
| **gate** | The conditional that lets the hourly analysis tick run: outside working hours OR idle |
| **judge** | Optional LLM tier in `topic.detect()` (`llm_judge=true`) that asks the configured provider whether a capture is about a given topic. Cost-controlled by `llm_judge_max_chars`. |
| **PoI** | Point of Interest. A topic, project, customer, or entity the user wants captures grouped by. |
| **provider** | An LLM backend implementing `rin.llm.base.Provider`. Three ship today: copilot_cli (default), openai, azure |
| **role** | A Qt property on a widget that opts it into stylesheet rules. Examples: `primary`, `flat`, `chip`, `field-label`, `caption`, `nav`, `cards`, `empty-state-title`, `user-bubble`, `agent-bubble`, `search`, `search-attached`, `divider-vert` |
| **skill** | A drop-in plugin under `rin.skills.builtin.*` or `%LOCALAPPDATA%\RIN\skills\<name>\` that categorizes captures into buckets |
| **SkipInfo** | The `(reason, detail)` record `CaptureService.last_skip()` exposes after a falsy return so the tray can render context-aware toasts |
| **topic** | RIN's generic PoI skill (`rin.skills.builtin.topic`). Declarative; reads `[skills.topic].topics` from `config.toml`. |
| **trigger** | The user's bound input — keyboard key, mouse button, or HID / Bluetooth button |

## Files an agent should rarely touch

- `src/rin/ui/assets/*.svg` — Microsoft Fluent System Icons;
  replacements must come from the upstream MIT repo
- `LICENSE` — MIT, unchanged
- `NOTICE` — update only when a new bundled asset / dep introduces an
  attribution requirement
- `.gitignore` — already excludes `.venv`, `dist`, `build`,
  `__pycache__`, sqlite working files, `logs`, build artefacts. The
  `!/scripts/RIN.spec` line is intentional.

## What to read first when starting a task

| If you want to … | Read |
| --- | --- |
| Understand the runtime entry point | `src/rin/app.py` and `src/rin/__main__.py` |
| Trace one captured screenshot end-to-end | the **Data flow** diagram above, then `src/rin/capture/screenshot.py` + `src/rin/analysis/summarizer.py` |
| Reason about subprocess lifecycles | `src/rin/capture/recorder.py` and `src/rin/llm/copilot_cli.py` |
| Reason about threading + Qt signals | `src/rin/input/manager.py` and `src/rin/ui/tray.py` |
| Write a new skill | `docs/skills.md` + `src/rin/skills/builtin/support_ticket/skill.py` |
| See past design choices | `CHANGELOG.md` (especially v0.3.1, v0.6.0, v0.7.0, v0.7.1) and `review_findings` table notes in commit messages |
| Diagnose a runtime failure | `docs/troubleshooting.md` then `%LOCALAPPDATA%\RIN\logs\rin.log` |

## Development workflow

```powershell
# 1. Install uv (fast Python package manager)
winget install --id=astral-sh.uv -e

# 2. Create a virtual environment and install RIN with dev extras
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[all,dev]"

# 3. Boot the tray app
python -m rin

# 4. Iterate
ruff check src tests scripts
pytest -q
python -m rin --smoke   # boot + immediate exit; verifies import chain
```

Optional extras (declared in `pyproject.toml`):

| Extra | Purpose |
| --- | --- |
| `storage` | SQLAlchemy + ChromaDB |
| `capture` | mss, sounddevice, pywin32 |
| `input` | keyboard, pynput, hidapi |
| `llm` | openai, keyring |
| `analysis` | APScheduler, rapidocr, faster-whisper |
| `reports` | Jinja2, markdown |
| `rag` | sentence-transformers |
| `calendar` | msal, google-auth, googleapiclient |
| `telemetry` | sentry-sdk |
| `dev` | pytest, pytest-cov, pytest-benchmark, ruff, pyinstaller |
| `all` | every runtime extra (excludes `dev` + `telemetry` + `calendar`) |

## Testing

```powershell
pytest -q                              # all 396 tests, ~60-90 s on a warm cache
pytest -q --cov=rin --cov-report=term-missing  # with coverage
pytest tests/test_perf_*.py            # pytest-benchmark suite
ruff check src tests scripts
python -m rin --smoke
```

Tests live under `tests/` and are organized one file per subsystem
(`test_capture_recorder.py`, `test_rag_agent.py`, …). Heavy I/O is
mocked via dependency-injection points already wired into each module.

CI runs on every push and PR via
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) (ruff + pytest +
smoke on Python 3.11 and 3.12 on `windows-latest`). Tagged releases
(`v*.*.*`) build the release zip automatically via
[`.github/workflows/release.yml`](.github/workflows/release.yml).

## Smoke-test checklist

After installing, walk this sequence in order:

1. **Boot.** `python -m rin --smoke` → exits 0, `logs\rin.log` shows
   startup.
2. **Launch tray.** `python -m rin` → tray icon appears. Press
   **Ctrl+C** in the terminal to confirm clean shutdown.
3. **Learn trigger.** Settings → Trigger → *Learn new button* → tap
   any key.
4. **Take a screenshot.** Tray → *📸 Capture now*. PNG appears under
   `captures\YYYY\MM\DD\<ts>-shot\`. Confirm the
   `<name>.thumb.jpg` sidecar is also written.
5. **Analyze.** Tray → *🧠 Analyze now*. Progress toasts; final toast
   confirms `Analysis complete — N/N`.
6. **Search.** Tray → *🔎 Search…* → type a query. Hits show; ask a
   question, agent answers with `cap-N` citations.
7. **Generate a report.** Tray → *📄 Reports…* → *Generate today*. A
   `BusyOverlay` spinner appears while the LLM runs; daily Markdown
   saves to `reports\daily-YYYYMMDD.md`. Click **Export PDF** /
   **HTML** from the toolbar.
8. **Skills.** Settings → Skills → enable *Support tickets*. Take a
   capture mentioning a ticket ID; verify a `buckets` row appears
   (`sqlite3 %LOCALAPPDATA%\RIN\rin.db "SELECT * FROM buckets"`).
9. **Pause.** Settings → Privacy → *Pause for 15 minutes*. Press your
   trigger; toast says *"Captures paused · Resumes at HH:MM"*.
10. **Panic hotkey.** Press `Ctrl + Alt + Shift + P`. Pause toggles
    (RAM-only), toast confirms.
11. **Record (optional).** Hold the trigger key > 500 ms; release →
    MP4 saved. Requires FFmpeg.
12. **Diagnostic.** Tray → *🩺 Generate diagnostic report*. Explorer
    opens at the redacted zip.
13. **Data export.** Settings → Data → *Export everything*. Inspect
    the zip — config secrets must be scrubbed.
14. **Autostart.**
    ```powershell
    python -c "from rin.utils.autostart import enable, default_command; enable(default_command())"
    ```
    Sign out + in. RIN starts automatically. Disable with `disable()`.
15. **Topics & PoIs tab.** Open Settings → **Topics & PoIs** → verify
    the tab loads without errors.
16. **Manual PoI.** Add a PoI via the form → **Save** → verify
    `config.toml` now contains the new `[[skills.topic.topics]]` entry.
17. **Discover now.** From the same tab click *Discover now…* → verify
    candidates appear, or a clear *no suggestions* state appears when
    the DB is empty.
18. **PoI match.** Trigger a capture that mentions your manual PoI →
    after analysis, verify the bucket is created.
19. **Per-PoI report.** Generate a daily report → verify it contains a
    `## <PoI name>` section when a topic was touched, or falls back to
    chronological layout when none were.
20. **CLI discovery.** Run `python -m rin poi-discover --days 30` →
    verify it prints candidates (or a no-suggestions message) without
    crashing.

## Building a release

Two artefacts: a small **source zip** (~200 KB) and a large **PyInstaller
.exe bundle** (~423 MB zipped).

```powershell
# Source zip — what the release workflow does automatically on tag push
.\scripts\build_release.ps1       # → dist\RIN-vX.Y.Z-windows.zip

# Standalone .exe — build locally, then upload as a 2nd asset
.\scripts\build_exe.ps1           # → dist\RIN\ (1.1 GB) + dist\RIN-vX.Y.Z-windows-installer.zip
```

`scripts/RIN.spec` drives the PyInstaller build. Key conventions:

- `--onedir` (not `--onefile`) — ChromaDB and Torch need a directory
  layout to load their native libraries.
- `excludes` strips `torch.cuda` / `torch.distributed` / `torch.onnx`
  / testing + benchmark modules (~20 MB).
- `_walk_as_datas` helper produces 2-tuples that `Analysis.datas`
  expects (`Tree()` returns 3-tuples for `COLLECT` and crashes here —
  R20 in v0.7.1).
- `torch_cpu.dll` (294 MB) is the irreducible floor.

Full build guide: [`docs/build-exe.md`](docs/build-exe.md).

## Deeper architectural reading

- [`docs/architecture.md`](docs/architecture.md) — Mermaid sequence
  diagrams for the three core flows (tap → captured row, analysis tick
  → summary → vector, user asks → RAG answer).
- [`docs/skills.md`](docs/skills.md) — Skill plugin contract +
  bundled-skill catalogue + custom-skill recipe + security model.
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — Every known
  failure mode + workaround.
- [`docs/build-exe.md`](docs/build-exe.md) — PyInstaller bundle build
  + known pitfalls (ChromaDB native loading, Whisper model caching).
- [`CHANGELOG.md`](CHANGELOG.md) — Release-by-release rationale.
- [`SECURITY.md`](../.github/SECURITY.md) — What stays local, what leaves the
  machine, how to disclose vulnerabilities.
- [`CONTRIBUTING.md`](../.github/CONTRIBUTING.md) — Branch / commit / PR norms.
- [`AGENTS.md`](AGENTS.md) — Hard rules for AI agents working in this
  repo.
