# Changelog

All notable changes to RIN — Record It Now.

## v0.3.2 — Fluent 2 calibration pass

A second look at the UI revealed several layout flaws that didn't match
modern Fluent 2 guidance. Per-pane before/after screenshots in
`docs/screenshots/`.

### Improved
- **Form layout** — labels are now *above* inputs (Fluent 2 standard),
  not beside them. Inputs have explicit max widths instead of stretching
  the full row. Implemented via `QFormLayout.RowWrapPolicy.WrapAllRows`.
- **Page headings** — every Settings page now has a clear `h1` title.
  Field labels use a small muted caption style (Fluent's 12 px / 500 weight).
- **Settings footer** — Cancel + Save sit in a real footer bar with a
  1 px top border, instead of floating below empty space.
- **Type ramp** — calibrated to Fluent 2: Body 14 px, Caption 12 px,
  Subtitle 16 px Semibold, Title 24 px Semibold. Previously h1 was too
  shouty.
- **Corner radius** — buttons 4 px, cards 8 px (was 6 px / 10 px) — matches
  Fluent 2.
- **Nav rail** — denser rows (28 px min-height vs ~70 px), 16 px icons
  inline with the label (was awkwardly large).
- **List cards in Reports** — single-line date+kind layout instead of
  two stacked rows; tighter padding.
- **Empty states everywhere they were missing** —
  - Reports right pane: "Select a report" with helpful hint.
  - Search results: "No searches yet" + tip.
  - Ask chat: "Ask anything about your captures" + example query.
- **Window heading text** in Search + Reports describes the section's
  purpose at a glance.

### Added
- `ui/theme.Theme` now exposes a full **type ramp** (caption / body /
  subtitle / title sizes in pt) and **spacing scale** (`space_xs` … `space_xl`).
- New QSS roles: `[role="field-label"]`, `[role="caption"]`,
  `[role="empty-state-title"]`, `[role="empty-state-hint"]`,
  `[role="divider"]`, `[role="cards"]`.

### Tested
176/176 pass, ruff clean. Before/after screenshots checked in to
`docs/screenshots/{before,after}/`.

---

## v0.3.1 — Pre-release code review pass

Fixes uncovered by a final pre-release review (independent `code-review`
sub-agent + manual review). None visible to users on the happy path, but
each would bite under real-world conditions.

### Fixed
- **Video analysis tempdir leak** (`analysis/video_analyzer.py`). Each
  call to `analyze_video()` was creating `%TEMP%/rin-vid-XXXX/` for
  keyframe PNGs but never removing it. After weeks of usage, hundreds of
  MB of orphaned PNGs accumulated. Now wrapped in a try/finally that
  `shutil.rmtree`s the internally allocated dir.
- **FFmpeg stderr deadlock risk** (`capture/recorder.py`). The recorder
  pipelined `stderr=subprocess.PIPE` but never drained it. On
  long-running recordings (>5 min in a noisy session), the ~64 KB
  Windows pipe buffer would fill, ffmpeg would block on its next stderr
  write, and the recording would hang silently. Switched to
  `stderr=subprocess.DEVNULL`.
- **Tray thread-safety on analysis progress** (`ui/tray.py`). The
  APScheduler worker was calling `QSystemTrayIcon.setToolTip()` directly
  — Qt requires GUI calls to happen on the main thread. Now bounces
  through a `Qt.QueuedConnection` Signal.
- **Orphaned ffmpeg on Quit while recording** (`ui/tray.py`). If the
  user picked Quit (or Ctrl+C) while a recording was in progress, the
  ffmpeg subprocess survived as an orphan and kept writing to disk.
  `TrayApp.stop()` now calls `capture_service.stop_recording()` first.
- **Concurrent analysis race** (`analysis/scheduler.py`). A manual
  *🧠 Analyze now* click could overlap with the hourly scheduled tick,
  both seeing the same `status="captured"` rows and both running the
  pipeline, doubling LLM costs. Now guarded by a non-blocking
  `threading.Lock` — overlapping ticks skip with a log line.

### Documented
- `scripts/install.ps1`: clarified that the "no admin needed" claim
  applies to RIN itself, but winget may surface a UAC prompt when
  installing Python/FFmpeg system-wide.
- `storage/migrations.py`: documented the naive `;` split limitation
  in `MIGRATIONS` (future entries with semicolons in string literals
  should use a callable instead of raw SQL).

### Tests
176/176 pass (+ 4 new: video tempdir cleanup, video user-dir preservation,
recorder stderr = DEVNULL, scheduler concurrent-tick lock).

---

## v0.3.0 — Fluent-inspired UI refresh

### Added
- **Fluent design system** (`src/rin/ui/theme.py` + `style.py`). All colors,
  fonts, radii, and spacing live in a single `Theme` dataclass with `LIGHT`
  and `DARK` presets and four accent options (blue / purple / teal / orange).
  Stylesheet rendered into Qt via `palette_to_qss()`.
- **Auto-follow Windows theme.** Reads `HKCU\…\Personalize\AppsUseLightTheme`
  and picks light or dark on boot; user can override in Settings →
  Appearance.
- **Appearance settings tab** with Theme, Accent color, and Density controls.
- **Settings dialog redesigned**: horizontal tabs → left-nav rail
  (`QListWidget[role="nav"]`) + `QStackedWidget`. 200 px wider dialog.
- **Reports window redesigned**: card-styled list on the left, themed
  Markdown rendered to HTML in `QTextBrowser` on the right (headings,
  code blocks, accent blockquote border).
- **Search window redesigned**: result cards instead of dense rows, plus a
  chat-bubble panel for the RAG agent's Q&A history (user bubbles
  right-aligned, agent bubbles left-aligned with citation strips).
- **Bundled Fluent UI System Icons** (Microsoft, MIT) under
  `src/rin/ui/assets/` — 20 SVGs at 24 px regular weight (record, camera,
  play, pause, settings, search, document, lightbulb, clock, mic, color,
  dismiss, calendar, keyboard, save, folder, chat, send, info, checkmark).
- **Tray icon refresh**: camera glyph on accent-colored background. A
  pulsing red dot overlay animates while recording (`PulseIconAnimator`).
- **Live theme switching** — Save in Appearance applies the new look
  immediately, no restart.
- **2 new test files**: `tests/test_ui_theme.py` (WCAG AA contrast checks)
  and `tests/test_ui_qss_renders.py` (QSS round-trip).

### Changed
- `recorder.stop()` is now robust to ffmpeg exiting early — catches
  `OSError(EINVAL)` from a closed stdin pipe (real RDP regression caught
  by the v0.2.0 end-to-end simulation).
- Default theme is `auto`; accent is `blue`; density is `comfortable`.
- `RinConfig` now has a `ui` section persisting the three new fields.

### License
All new assets are MIT (Microsoft Fluent UI System Icons). NOTICE updated.

---

## v0.2.0 — Publish to GitHub Releases

### Added
- **`scripts/install.ps1`** — end-to-end Windows installer. Provisions
  Python 3.12, FFmpeg, GitHub Copilot CLI, uv, and all Python deps. Flags:
  `-InstallDir`, `-Prefetch`, `-Autostart`, `-SkipDeps`, `-Force`,
  `-WhatIf`. Honors `$env:HTTPS_PROXY`. Creates a Start Menu shortcut.
- **`scripts/prefetch_models.py`** — opt-in download of every ML model
  (sentence-transformers ~90 MB, RapidOCR bundled ONNX, Whisper small
  ~470 MB) so the first analyze/search runs offline.
- **`scripts/build_release.ps1`** — author-side build script. Runs
  `ruff` + `pytest`, stages a minimal source tree, zips it as
  `dist\RIN-v{version}-windows.zip` (~100 KB).
- **`NOTICE`** — full third-party license audit + attributions.
- **Bilingual `README.md` / `README.zh-CN.md`** updates: new top-level
  Installation section drives users to `install.ps1`. Added Uninstall +
  Updating sections. Documented every installer flag.
- **10 new tests**: 4 for `prefetch_models.py`, 6 for `install.ps1`
  (drift detection vs `__version__`, flag presence checks).

### Changed
- Project version bumped to `0.2.0` in `src/rin/__init__.py` and
  `pyproject.toml`.
- Test suite grew from 151 → 161 (all passing).

### Notes
- The PyInstaller path (`scripts/package.py`) is kept as a starting point
  for a future v0.3.0 standalone-exe release but is **not** part of this
  release.

---

## v0.1.1 — Hardening

### Fixed
- **Ctrl+C / SIGTERM clean exit.** Qt's event loop normally swallows
  SIGINT; RIN now installs a Python signal handler + a 200 ms wake-up
  QTimer so both Ctrl+C and `Stop-Process` cleanly shut down the tray.
- **Subprocess UTF-8 safety.** FFmpeg stderr and Copilot CLI Chinese
  output used to crash the subprocess reader thread with
  `UnicodeDecodeError` (Windows cp1252 default). Both `subprocess.run`
  call sites in `analysis/keyframes.py` and `llm/copilot_cli.py` now use
  `encoding="utf-8", errors="replace"`.
- **Settings → Save no longer crashes** (`notify("Settings saved")` was
  missing a required `body` argument). `body` is now optional.
- **Reports / Search windows are now their real Phase 7/8
  implementations.** The Phase 4 stubs had been silently shadowing them.

### Added
- **Live analysis progress.** *🧠 Analyze now* emits per-capture toasts
  (every Nth + last), a final `Analysis complete — N/N captures` summary,
  and live `Analyzing K/N (cap-X)` in the tray tooltip.
- **Manual *Analyze now* bypasses the working-hours/idle gate** so the
  user can always force a run.
- **`Capture` settings tab** with a DirectShow audio-device picker
  (Refresh devices button, sample rate, channels). New
  `list_dshow_audio_devices()` helper parses both legacy and modern
  FFmpeg device-listing formats.
- **Default LLM model changed** to `claude-opus-4.7-1m-internal` with
  `reasoning_effort = "high"`. Settings dialog gained a *Reasoning
  effort* dropdown.

---

## v0.1.0 — Initial release

All 10 phases shipped: Scaffold · Storage · Capture · Input · UI · LLM
providers · Analysis pipeline · Reports · RAG search agent · Packaging.
End-to-end pipeline verified: capture → OCR → vision LLM → SQLite +
ChromaDB → semantic search → RAG Q&A with citations.
