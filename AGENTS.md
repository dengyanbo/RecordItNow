# AGENTS.md

> One-page redirect for AI coding agents (Copilot, Claude, GPT, etc.)
> that open RIN's repository.

## Read this first

**[`docs/DEVELOPING.md`](docs/DEVELOPING.md)** is the canonical entry point. It
contains:

- **Repository at a glance** — one-line description of every `src/rin/<subpackage>/`.
- **Data flow** — step-by-step trace from one button tap to a searchable RAG answer (plus the skills classification + archive path).
- **Decision log** — the *why* behind every meaningful trade-off (PySide6 vs alternatives, GPL libraries we rejected, why Copilot CLI default, why ffmpeg stderr is `DEVNULL`, why `SkipInfo` exists, why we pre-warm the tray menu, etc.).
- **Common tasks** — recipes for adding an LLM provider, adding a settings field, adding an analysis step, adding a bundled skill, changing the theme, shipping a release.
- **Glossary** — `capture`, `cap-N`, `analysis`, `trigger`, `gate`, `provider`, `skill`, `bucket`, `archive`, `SkipInfo`, `role`, `density`.
- **Files an agent should rarely touch.**
- **"What to read first when starting a task"** — a small lookup table mapping intents to source files.

End-user docs (install, screenshots, feature list) live in
[`README.md`](README.md). Architecture deep-dive lives in
[`docs/architecture.md`](docs/architecture.md). Custom-skill recipe
lives in [`docs/skills.md`](docs/skills.md). Release history is in
[`docs/CHANGELOG.md`](docs/CHANGELOG.md).

## Hard rules — these are non-negotiable

1. **Run `ruff check src tests scripts` AND `pytest -q` before declaring a task done.** Both must be green. Test count is 396 and growing — but signal matters more than count, so don't add trivial tests just to inflate it. Regressions are not acceptable.

2. **Do not introduce GPL dependencies.** RIN is MIT. The decision log explicitly rejects `PySide6-Fluent-Widgets` (GPL-3.0). LGPL is OK via dynamic linking (we use PySide6, pynput).

3. **Do not bundle FFmpeg.** It's installed by `scripts/install.ps1` via `winget install Gyan.FFmpeg`. RIN invokes it only as a subprocess.

4. **All `subprocess.run`/`Popen` that decode text must set `encoding="utf-8", errors="replace"`.** Windows cp1252 default crashes on Chinese / emoji output. (v0.1.1 / v0.3.1 / v0.4.0 lessons.)

5. **All callbacks that touch Qt widgets must run on the Qt main thread.** Use `Signal` with `Qt.QueuedConnection` to marshal from worker threads. (v0.3.1 lesson — R3.)

6. **Themes/colors flow from `theme.py` through `style.py` only.** No hard-coded colors in window code. The WCAG AA contrast tests will catch new accessibility regressions.

7. **No new TODO comments in source code.** If something is incomplete, file a SQL todo via the session DB or open an issue. v0.7.1 cleaned out the stale `TODO(Agent D)` comments left by parallel agents — don't reintroduce that pattern.

8. **Co-author commits with Copilot:**
   ```
   Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
   ```

## Quick start (development)

```powershell
git clone https://github.com/dengyanbo/RecordItNow.git
cd RecordItNow
winget install --id=astral-sh.uv -e
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[all,dev]"
pytest -q                              # should print "396 passed"
python -m rin --smoke
```

## When you're done

```powershell
ruff check src tests scripts
pytest -q
git add -A
git commit -m "<imperative summary>"   # include the Copilot co-author trailer
git push
```

If you bumped the version, also tag and push the tag — the release
workflow at `.github/workflows/release.yml` will build + publish the
source zip automatically.
