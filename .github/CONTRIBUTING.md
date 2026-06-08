# Contributing to RIN

Thanks for considering a contribution! RIN is a personal-data tool
(everything stays on the user's machine) and we keep the bar for
correctness high. Please read this whole file before sending a PR.

## TL;DR

1. Fork → branch off `main` → commit with a Copilot co-author trailer →
   open a PR.
2. `ruff check src tests scripts` **and** `pytest -q` must be green.
3. Don't add GPL dependencies, don't bundle FFmpeg, don't break the
   subprocess UTF-8 rules.
4. UI changes need a before/after screenshot.

---

## 1. Development setup

```powershell
git clone https://github.com/<you>/RecordItNow.git
cd RecordItNow

# Install uv (fastest Python manager on Windows). If you prefer venv,
# the install.ps1 script also works for development.
winget install --id=astral-sh.uv -e

uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[all,dev]"

pytest -q          # should print "306 passed" (or higher)
python -m rin --smoke
```

If `pytest` is red on `main`, that is a bug — please open an issue.

## 2. Branching and commit style

- Branch from `main`. Suggested naming:
  `feat/<short-name>`, `fix/<short-name>`, `docs/<short-name>`,
  `ci/<short-name>`, `refactor/<short-name>`.
- Commit messages should be in the imperative ("Add … ", "Fix … ", not
  "Added"). Reference an issue when relevant.
- **Co-author your commits with Copilot** when you used AI assistance
  (almost every commit in RIN's history does this):

  ```
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
  ```

- Squash-merge is the default; PR title becomes the commit subject.

## 3. Tests

- Every behaviour change adds, modifies, or deletes a test. PRs that
  only touch source code and not the test suite get extra scrutiny.
- `tests/` mirrors the `src/rin/` layout — put a test for
  `src/rin/X/Y.py` in `tests/test_X_Y.py`.
- Tests must not require an internet connection, FFmpeg, Copilot CLI,
  or a GPU. Mock or skip when the dependency is missing.

  ```python
  pytest.importorskip("hidapi")
  ```

- Qt tests that need a `QApplication` use the `qapp` fixture in
  `tests/conftest.py` (creates one with `QT_QPA_PLATFORM=minimal`).

## 4. Linting and formatting

```powershell
ruff check src tests scripts
ruff format src tests scripts    # optional but recommended
```

`ruff` rules are in `pyproject.toml` (`tool.ruff`). Please do not relax
them in your PR; if a rule is genuinely wrong for a single file, add an
inline `# noqa: <code>` comment with a one-line justification.

> The current baseline is **306 passed**; PRs must not regress that count.

## 5. The five hard rules

Each one of these has bitten us before and is enforced manually in
review:

### 5.1 No GPL dependencies

RIN ships MIT. LGPL is fine via dynamic linking (PySide6, pynput).
Anything copyleft (`PySide6-Fluent-Widgets`, `keyboard` on Linux when
it bundles modules differently, …) is rejected.

### 5.2 Don't bundle FFmpeg

`scripts/install.ps1` installs it via `winget install Gyan.FFmpeg`.
The binary is found via `PATH`. Bundling it ourselves would balloon the
release zip and create a re-distribution headache.

### 5.3 Subprocesses that decode output must be UTF-8

Windows defaults to `cp1252`, which crashes on Chinese characters or
emoji. Every `subprocess.run` and `subprocess.Popen` that reads text:

```python
subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
```

### 5.4 Qt widgets are touched only on the main thread

If you are inside an APScheduler job, a `QRunnable`, or any non-Qt
thread, marshal back through a signal:

```python
class MyThing(QObject):
    progress = Signal(int)

    def __init__(self):
        super().__init__()
        self.progress.connect(self._on_progress, Qt.QueuedConnection)

    def _on_progress(self, value): ...
```

### 5.5 Don't hard-code colours / fonts / radii

Everything visual flows through `src/rin/ui/theme.py` (design tokens)
and `src/rin/ui/style.py` (QSS template). Reach for a `[role="…"]`
selector instead of `setStyleSheet("color: red")` on a widget.

## 6. UI changes

Attach a before/after screenshot in the PR description. We keep the
canonical reference images in `docs/screenshots/after/` — you can drop
new ones there if your PR meaningfully changes the look.

Run the WCAG AA test (`pytest tests/test_ui_theme.py`) after any palette
change — every accent × theme combination must clear 4.5:1 contrast.

## 7. Releasing

You probably don't need to release; the maintainer handles tagging.
But the recipe is in [README.md → 🤖 For AI agents working on this
codebase → Common tasks → Ship a release](README.md#ship-a-release).

## 8. Code of Conduct

By participating, you agree to abide by [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

## 9. Where to ask

- Question / discussion: open a [GitHub Discussion](https://github.com/dengyanbo/RecordItNow/discussions).
- Bug: file an issue using the **🐛 Bug report** template.
- Security: see [`SECURITY.md`](SECURITY.md).
- Deeper dev guide (architecture, decision log, common-task recipes, glossary): see [`DEVELOPING.md`](../docs/DEVELOPING.md).
