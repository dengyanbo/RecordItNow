<!--
Thanks for contributing to RIN! Please skim CONTRIBUTING.md before submitting.
-->

## Summary

<!-- One sentence describing what this PR does. -->

## Motivation / context

<!-- Why is this change needed? Link to the issue if there is one. -->

Closes #

## Changes

- <!-- bullet list of what changed -->

## Validation

- [ ] `ruff check src tests scripts` is clean
- [ ] `pytest -q` is green (current baseline: **553/553**)
- [ ] If UI-visible, a before/after screenshot is included below

<!-- before / after screenshots here if relevant -->

## Checklist

- [ ] I read [CONTRIBUTING.md](../blob/main/.github/CONTRIBUTING.md)
- [ ] My commit messages include `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` when AI assistance was used
- [ ] I did **not** introduce a GPL-licensed dependency (RIN ships MIT)
- [ ] I did **not** add a hard requirement on bundled FFmpeg (we install it via `winget`)
- [ ] If I touched `subprocess.run` / `Popen` with text output, I set `encoding="utf-8", errors="replace"`
- [ ] If I touched Qt widgets from a worker thread, I marshalled through a `Signal(..., Qt.QueuedConnection)`

## Notes for the reviewer

<!-- Anything special the reviewer should focus on. -->
