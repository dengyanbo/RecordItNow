# Troubleshooting

This page collects every real-world failure we have already debugged in
the RIN codebase, plus the fix or workaround for each. If you hit one,
please refer to the section below before opening an issue — chances are
it is already covered.

If you cannot find your issue, please run
**Tray → 🩺 Generate diagnostic report** (or
`python -m rin.utils.diagnostics`) and attach the resulting zip to your
GitHub issue.

---

## Install / first run

### `winget` is not recognised

`scripts/install.ps1` provisions Python, FFmpeg, and Copilot CLI via
`winget`. If `winget --version` fails:

- On Windows 11, install **App Installer** from the Microsoft Store.
- On Windows 10 (1809+), install
  [Microsoft.DesktopAppInstaller](https://aka.ms/getwinget) manually.
- If you cannot use `winget` at all, the script accepts `-SkipDeps` and
  you can install Python 3.11+, FFmpeg, and (optionally) Copilot CLI
  yourself.

### `install.ps1` claims it needs no admin, but the install prompts for UAC

The script does not require admin **for RIN itself**. The UAC prompt
comes from `winget`'s per-machine install of Python / FFmpeg. If you
prefer no UAC at all:

```powershell
.\scripts\install.ps1 -SkipDeps  # then install Python + FFmpeg per-user
```

### `pip install -e .[all,dev]` complains about Python version

RIN requires Python ≥ 3.11. Check:

```powershell
python --version
```

If you have multiple Pythons, ensure the right one is on PATH inside
the `.venv` you created with `uv venv`.

---

## Capture

### Screenshot succeeds but the PNG is blank or 0×0

Most often happens on **Remote Desktop sessions** with multiple
monitors. Windows reports the RDP "client" monitor at 0×0 to `mss`. We
work around this by capturing each monitor whose size > 0×0; sometimes
RDP also fakes a phantom monitor that exists in `mss.monitors[0]`
(virtual desktop) but is reported with wrong bounds.

Workarounds:

- Reconnect with `mstsc /multimon` or set
  `Use all my monitors for the remote session` in the RDP options.
- If running headless on a server, set
  `RinConfig.capture.audio_device = None` so the recorder does not try
  to bind dshow audio that is missing.

### Recording stops immediately after start

This was a real bug (R2 in v0.3.1): ffmpeg's stderr pipe filled up after
~64 KB and the recorder hung. Fixed by setting `stderr=DEVNULL`. If you
still see this on `main`, capture `rin.log` while reproducing and open
a bug.

### Recording stops with a `BrokenPipeError` on RDP

Specific to `gdigrab` over RDP. We catch `BrokenPipeError, ValueError,
OSError` in `Recorder.stop()` and close stdin explicitly to suppress
the GC finalizer's secondary error. If you see this on a current
release, please attach the diagnostic zip.

### FFmpeg processes orphaned after Quit

Was R4 in v0.3.1. `TrayApp.stop()` now calls
`capture_service.stop_recording()` before tearing down. If you see
orphans:

```powershell
Get-Process ffmpeg
```

Kill them with `Stop-Process -Id <pid>` and report the conditions.

---

## Input / triggers

### Pressing my chosen trigger does nothing

Possible causes:

1. **Trigger is unbound.** Open Settings → Trigger and click *Learn
   new button*. After this you should see the binding string change.
2. **RIN is paused.** The tray icon does not show a "Pause" badge but
   the menu item *⏸ Pause captures* is checked. Click to uncheck.
3. **The bound key is reserved by Windows.** `Win+L`, `Ctrl+Alt+Del`,
   `Alt+Tab`, and a few others will never reach RIN because Windows
   intercepts them. Pick another key (RIN v0.4.0+ warns you in learn
   mode).
4. **HID device disconnected.** If you bound a Bluetooth presenter and
   it timed out, re-pair it; the listener re-binds on the next event.

### Learn mode captured the wrong key

Press *Learn new button* again. The newest binding always wins.

### `pynput` install failed with permission errors

Some corporate environments block low-level keyboard hooks. RIN will
still capture screenshots when triggered from a HID device; you just
lose keyboard / mouse triggers.

---

## Analysis / reports

### "Nothing new to analyse" but I have captures

Either:

- All captures are already summarised (check `status='summarized'`
  rows in SQLite).
- The analyser is gated. Manual *🧠 Analyze now* bypasses the
  working-hours / idle gate; the hourly scheduler does not.

### Analysis fails with `UnicodeDecodeError` on Windows

This was v0.1.1's fix. Subprocesses default to `cp1252` on Windows.
Anywhere RIN reads stdout from a subprocess (`copilot`, `ffprobe`,
`ffmpeg`) we pass `encoding="utf-8", errors="replace"`. If you see
this on a current release, the subprocess is third-party — please
report it.

### Whisper transcripts are full of nonsense Chinese / English

The default model is `small`, which trades quality for speed. For
zh-cn / ja content prefer `medium` or `large-v3`. v0.4 added a model
picker; until then, edit `config.toml`:

```toml
[analysis]
whisper_model = "medium"
```

### Daily report says "no captures today"

The capture day is computed in **local time**. If you are in UTC+13
working at midnight you may straddle two days. Until v0.4 adds a
timezone option, your "day" starts at midnight local.

### `keyring` raises on Linux / WSL

We default to the Windows backend. On other OSes install
`keyrings.alt` for a file-backed fallback, or set the LLM provider to
`none` and use Copilot CLI (no key needed).

---

## RAG / Search

### Search returns nothing relevant

Either the corpus is too small (you ran RIN for one hour, then asked a
question) or the embedding model has not loaded. First run downloads
~90 MB to `%LOCALAPPDATA%\RIN\models\`; if you blocked that download,
search remains keyword-only.

### "Embedding model not found" on a brand-new install

Run `python -m rin.scripts.prefetch_models` once with internet, or pass
`-Prefetch` to `install.ps1`.

### Copilot CLI auth required

The default LLM provider is **Copilot CLI** (`claude-opus-4.7-1m-internal`
at high reasoning effort). You need:

```powershell
copilot --version       # ≥ 1.0.51
copilot auth login      # one-time GitHub OAuth
```

If you do not have a Copilot subscription, switch to `openai` or
`azure` in Settings → LLM provider.

---

## UI / theme

### Settings dialog shows up with no styling

The QSS stylesheet failed to render. Check `rin.log` for a `palette_to_qss`
exception. Most common cause: a custom theme TOML that does not match
the dataclass shape. Reset by deleting the `[ui]` section in
`config.toml`.

### Dark theme looks oddly bright after a Windows theme change

Live theme swap works for new windows, but some `QTextBrowser` widgets
need a window re-open. Close and reopen the Reports / Search window.

### Bright accents fail WCAG AA

We pre-check every accent × theme combination in
`tests/test_ui_theme.py`. If you add a new accent in `theme.py` and the
test fails, darken the accent (target 4.5:1 minimum on the lighter
background).

---

## Packaging / release

### `build_release.ps1` complains about ruff or pytest

It refuses to build a zip with red checks. Either fix the failure or
pass `-SkipChecks` (only for emergency hot-fixes).

### GitHub release upload says "tag already exists"

Use `gh release create <tag> --target main` only after `git push --tags`.
If you re-cut the same tag, delete the old release first or move the
tag with `git tag -f`.

### Pre-built zip won't extract

The zip is `dist/RIN-v<version>-windows.zip` and only contains source
plus install script. There is no portable .exe yet — you still need
Python on the target machine. The v0.4 todo `v0.4-pyinstaller-exe`
tracks a future portable build.

---

## Generating a diagnostic report

When you cannot reproduce a problem, run:

```powershell
python -m rin.utils.diagnostics
```

The script writes
`%LOCALAPPDATA%\RIN\rin-diagnostic-YYYYMMDD-HHMMSS.zip` containing:

- `config.toml` (with API keys scrubbed)
- last 7 days of `rin.log`
- environment summary (Python, OS, ffmpeg version, monitor list)
- `pip freeze` output
- counts of captures / summaries / reports (NOT their contents)

No screenshot, video, or LLM response is ever included.
