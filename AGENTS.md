# AGENTS.md

> Quick redirect for AI coding agents (Copilot, Claude, GPT, etc.) that
> open RIN's repository.

**Read this first → [README.md → "🤖 For AI agents working on this codebase"](README.md#-for-ai-agents-working-on-this-codebase)**

That section is the canonical entry point. It contains:

- **Repository at a glance** — one-line description of every `src/rin/<subpackage>/`.
- **Data flow** — step-by-step trace from one button tap to a searchable RAG answer.
- **Decision log** — the *why* behind every meaningful trade-off (PySide6 vs alternatives, GPL libraries we rejected, why we use Copilot CLI by default, why ffmpeg stderr is `DEVNULL`, etc.).
- **Common tasks** — recipes for adding an LLM provider, adding a settings field, adding an analysis step, changing the theme, shipping a release.
- **Glossary** — `capture`, `cap-N`, `analysis`, `trigger`, `gate`, `provider`, `role`.
- **Files an agent should rarely touch.**
- **"What to read first when starting a task"** — a small lookup table mapping intents to source files.

The rest of [`README.md`](README.md) is intended for human end users
(installation, screenshots, feature list).

For changelog + release history see [`CHANGELOG.md`](CHANGELOG.md).
For third-party attributions see [`NOTICE`](NOTICE).

## Conventions an agent should follow

- **Run `ruff check src tests scripts` and `pytest -q` before declaring a
  task done.** Both must be green. Test count is 233 and growing.
- **Don't introduce GPL dependencies.** RIN is MIT. The decision log
  explicitly rejects `PySide6-Fluent-Widgets` (GPL-3.0). LGPL is OK via
  dynamic linking (we use PySide6, pynput).
- **Don't bundle FFmpeg.** It's installed by `scripts/install.ps1` via
  `winget install Gyan.FFmpeg`. RIN invokes it only as a subprocess.
- **All `subprocess.run`/`Popen` that decode output must set
  `encoding="utf-8", errors="replace"`.** Windows cp1252 default
  crashes on Chinese / emoji output. (v0.1.1 / v0.3.1 lessons.)
- **All callbacks that touch Qt widgets must run on the Qt main thread.**
  Use `Signal` with `Qt.QueuedConnection` to marshal from worker threads.
  (v0.3.1 lesson.)
- **Themes/colors flow from `theme.py` through `style.py` only.** No
  hard-coded colors in window code. The WCAG AA contrast tests will
  catch new accessibility regressions.
- **Co-author commits with Copilot:**
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
pytest -q
python -m rin --smoke
```
