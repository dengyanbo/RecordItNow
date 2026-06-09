# Changelog

All notable changes to RIN — Record It Now.

## v0.17.0 — Skill scaffold + validate CLI (Phase 3-A) (2026-06-09)

First "skill authoring" release in Part 3. Zero new runtime behaviour
— just dev ergonomics for the small fraction of users who outgrow the
declarative `topic` skill and want to write their own. Lays the
foundation for v0.18.0's "Convert PoI to skill" button.

### What changed
- **`rin skill scaffold <name>`** CLI command. Writes a curated
  `skill.py` template under `<user-skills-dir>/<name>/` (default
  `%LOCALAPPDATA%\RIN\skills\` on Windows). Validates that `<name>`
  matches `[a-z][a-z0-9_]*` so the result is importable. Accepts
  `--display-name`, `--description`, `--version`, `--dir`, `--force`
  options.
- **`rin skill validate <path>`** CLI command. Loads a `skill.py`
  via the same `importlib.util.spec_from_file_location` plumbing the
  registry uses, then runs the 7 most common authoring checks: file
  exists, imports cleanly, exposes a module-level `SKILL`, that
  `SKILL` is a `Skill` instance, metadata is non-empty, `Config` (if
  present) is a valid Pydantic schema with valid defaults, `detect()`
  returns `list[BucketRef]` on a synthetic context, `should_close()`
  doesn't raise on empty + populated capture lists, and
  `render_archive()` returns a string. Accepts either a folder or a
  direct `skill.py` path. Exit code: 0 on PASS, 1 on FAIL.
- **New `rin.skills.scaffold` module** (`scaffold_skill()`,
  `validate_skill()`, `ValidationReport`, `ValidationCheck`). Pure
  Python — no new dependencies. The scaffold template is a minimal
  but runnable skill (keyword-match detect + inactivity-based
  `should_close`) that passes `validate` immediately so users can
  iterate from a known-good starting point.

### Limits & safety
- The scaffold writes only under the user-supplied / default skills
  dir; no PATH modifications, no installs into site-packages, no
  registry edits.
- `validate` does NOT sandbox the skill — `exec_module()` runs the
  user's code in-process. Treat unfamiliar skills like any other
  Python you wouldn't run with `python file.py`.
- The validator uses synthetic captures (1 capture, dummy text); a
  passing skill is **import-safe** but may still misbehave on real
  data. Users should always test against real captures via the
  Skills tab's Enable toggle before relying on the bucket output.

### Schema / migrations
- No schema changes. No migrations. No backfill.

### Tests
- 20 new tests across `tests/test_skill_scaffold.py` and
  `tests/test_cli_skill.py`. Covers scaffold name validation,
  overwrite refusal, generated skill passes validator, every
  validator failure mode (file missing, broken import, missing
  `SKILL`, wrong type, `detect` returns non-list, `detect` raises,
  empty metadata), CLI integration (exit codes + output). Suite now
  at **562 passed** (was 542 in v0.16.0).

### Upgrade
- No action required. Existing skills continue to work unchanged.
  Try the new CLI: `python -m rin skill scaffold my_first_skill`
  then `python -m rin skill validate %LOCALAPPDATA%\RIN\skills\my_first_skill`.

## v0.16.0 — Conversational LLM intake + "Why didn't this match?" diagnostic (Phase 2-C) (2026-06-09)

Third and final "POI authoring assist" release in Part 2. Closes the
iteration loop on PoI definitions: users can describe a topic in plain
language (LLM converts to a `TopicSpec`), and any PoI that *should*
have matched a given capture but didn't can now be diagnosed step by
step. Both are opt-in and degrade gracefully when no LLM provider is
configured.

### What changed
- **Conversational intake** on the wizard's Manual page. A new
  "💬 Describe with chat…" button (hidden when no LLM provider is set
  up) opens a bounded 4-question chat — *what to track? what words
  appear? how do you know it's done? anything that looks similar but
  isn't?* — and converts the answers into a `TopicSpec` via a single
  LLM call. Skip / Finish / "edit manually" are always available so
  the user can exit at any point with whatever's been collected.
- **Heuristic fallback** for the chat synth when the LLM is
  unreachable, returns malformed JSON, or simply isn't configured —
  always returns a usable `TopicSpec` with at least 1 keyword (defaults
  to the name).
- **"Why didn't this match?" diagnostic** on Settings → Topics & PoIs.
  Each row in the *My PoIs* table gains a new "Diagnose" button (the
  table now has 9 columns instead of 8) that opens a dialog with a
  "Pick capture…" picker. After a capture is chosen, the diagnostic
  runs every step the engine would have run — regex, keyword, alias,
  optional `llm_judge` — and shows pass / fail per step with the
  matched substring on pass or a fuzzy closest-match hint on fail
  (powered by `difflib.get_close_matches`).
- **New modules**: `rin.poi.conversational` (chat state machine + LLM
  synth helper) and `rin.poi.diagnostic` (step-by-step matcher with
  closest-match hints). Both are pure Python; the LLM is consulted
  once per chat for synth, and only when `topic.llm_judge=true` for the
  diagnostic.
- **New dialogs**: `PoIChatDialog` (4-turn chat with scrollable
  history) and `PoIDiagnosticDialog` (step-by-step verdict rows with
  selectable snippets).

### Limits & safety
- Chat is bounded at 4 questions; "Skip" advances without recording
  the answer; "Finish" synthesises whatever has been collected so far.
- Diagnostic uses the cheap layered matcher (regex → keyword → alias)
  first; the LLM judge step only runs when `topic.llm_judge=true` AND
  a provider is configured. Cost is bounded to 1 LLM call per
  diagnostic run.
- Closest-match hints in the diagnostic use a 0.6 similarity cutoff
  and 60-character snippet windows to keep the UI readable and avoid
  leaking large OCR fragments.

### Schema / migrations
- No schema changes. No migrations. No backfill.

### Tests
- 31 new tests across `tests/test_poi_conversational.py`,
  `tests/test_poi_diagnostic.py`,
  `tests/test_ui_poi_chat_dialog.py`,
  `tests/test_ui_poi_diagnostic_dialog.py`. Suite now at **542 passed**
  (was 511 in v0.15.0).

### Upgrade
- No action required — the chat button is hidden when no LLM provider
  is configured, and existing workflows are untouched. Diagnose any
  PoI that's been quietly missing matches by clicking the new
  "Diagnose" column on Settings → Topics & PoIs.

## v0.15.0 — "Create PoI from capture" + persona starter packs (Phase 2-B) (2026-06-09)

Second "POI authoring assist" release. Lowers the friction of bootstrapping
a useful PoI set: pre-canned persona templates seed common patterns in
one click, and any recent capture can be promoted to a new PoI via the
strongest signal it contains.

### What changed
- **Persona starter packs** on the wizard's Manual page. Dropdown lets
  users pick "Software Engineer", "Customer Success", "Researcher", or
  "Engineering Manager" and pre-populates 3–4 sensible PoIs that they
  can then edit or remove. "Custom (start blank)" keeps the v0.14
  behaviour. Manual rows still work after a persona is applied — the
  combined cap is now 10 (was 3) so personas + personal additions
  coexist comfortably.
- **`PERSONA_TEMPLATES` module** (`rin.skills.builtin.topic.templates`)
  exposes the templates with helpers `list_templates()`,
  `template_by_key()`, and `merge_template_topics()` for dedupe-by-name.
- **"Create from capture…" button** on Settings → Topics & PoIs (next
  to "Discover now…"). Opens a picker showing the last 30 captures
  (cap-N, timestamp, kind, summary preview); selection mines the single
  capture for its strongest signal (regex → phrase → domain → fallback)
  and opens the existing editor dialog pre-filled with a `TopicSpec`
  that the user reviews + saves.
- **New `rin.poi.from_capture` module**. `mine_topic_from_capture(id)`
  reuses the discovery regex / phrase / domain primitives but skips the
  multi-capture `min_evidence` thresholds since the user is explicitly
  pointing at one capture. Returns a `CaptureSeed` bundle (capture id +
  TopicSpec + evidence quote).

### Limits & safety
- Picker scans only the most recent 30 captures by `started_at` to keep
  the dialog snappy and avoid leaking older OCR text into the UI.
- Mined `TopicSpec` is capped at 8 keywords / 4 regex patterns.
- If the mine returns `None` (capture deleted between picker render and
  click), the UI surfaces a clear "Capture not found" message.

### No schema changes
This release adds **no migrations** — it's a pure UX layer over the
existing discovery + topic-skill infrastructure.

### Tests
+19 tests (511 total): 16 unit tests for `mine_topic_from_capture` +
persona templates, plus 3 UI tests covering the persona dropdown, the
persona + manual coexistence flow, and the capture-seed → editor
flow.

## v0.14.0 — Live regex preview + evidence quotes in wizard (Phase 2-A) (2026-06-09)

First "POI authoring assist" release. Surfaces *why* a PoI was
suggested (the snippet of OCR/transcript text that triggered it) and
lets users sanity-check their regex/keywords against real captures
before saving.

### What changed
- **Evidence quotes on `poi_candidates`.** New `evidence_quote: TEXT`
  column (migration v7) stores a ±60-char snippet around the first
  occurrence of the match in real capture text. All four discovery
  strategies (regex / domain / phrase / LLM) populate it.
- **Wizard renders the quote** under each discovered PoI checkbox
  ("…Project Atlas review meeting…"). Existing PoIs without a quote
  fall back silently to the old "(seen in N captures)" label.
- **Settings → Topics & PoIs**: the Suggested table gains a "Quote"
  column showing the persisted snippet.
- **Live preview in the editor** — both the inline manual-add form and
  the Edit dialog. As you type regex or keywords, after a 300 ms
  debounce, a worker thread runs `preview_matches()` against the last
  7 days of captures and shows:
  - the matched-capture count + how many captures were scanned
  - up to 3 random example snippets (`cap-N: "…match…"`)
  - an inline error message for malformed regex.
  Scan is capped at 200 captures so the UI stays responsive.
- **New `rin.poi.preview` module**. Pure-Python, stdlib-only;
  importable from headless tests.

### Tests
- `tests/test_poi_evidence_quote_and_preview.py` (18 tests) — quote
  window math (ellipsis padding, whitespace collapsing, max-len cap,
  empty-text edge case), regex/domain/phrase miners all attach a
  quote, `_merge_candidates` keeps the non-empty quote when merging,
  `persist_candidates` writes None → NULL and string → TEXT,
  `preview_matches` returns count + examples, invalid regex returns
  error, empty inputs return zero, sample_limit caps the scan.
- `tests/test_ui_poi_tab.py` (+3 tests) — Suggested table renders the
  Quote column, preview panel hidden until input, preview panel
  shown after a keyword is typed.
- `tests/test_ui_poi_wizard.py` (+1 test) — Discovery page renders
  the evidence-quote label under each suggestion.
- Total: 492 passed (was 470).

### Compatibility
- Migration v7 adds `evidence_quote` idempotently; old rows have
  `NULL` and the UI falls back gracefully.
- No new mandatory features: editor live-preview is purely additive
  visual feedback; rejecting the snippet still works.

## v0.13.0 — Active-POI decay + noise filter (Phase 1-D) (2026-06-09)

Final POI-aware summarization release. Bounds the per-capture prompt
size on machines with many tracked topics and lets users hide
low-signal "light browsing" captures from the per_poi report layout.

### What changed
- **Active-POI decay.** Two new `[skills]` settings drive the
  fallback active-POI list passed into `build_summary` when the
  pre-classify step finds no detected POIs:
  - `active_window_days: int = 30` — only topics touched within this
    many days qualify (per `capture_buckets.created_at`).
  - `active_top_k: int = 5` — caps the list to the K most-recently
    touched topics within that window.
  Defaults preserve v0.10.0/v0.11.0/v0.12.0 prompt behavior. Setting
  `active_window_days = 0` disables the fallback entirely.
- **Noise filter (opt-in).** Two new `[reports]` settings collapse
  uncategorized captures with very little summary text into a single
  footer line in per_poi reports:
  - `skip_noise: bool = False` — off by default; zero behavior change.
  - `noise_min_ocr_chars: int = 100` — summaries shorter than this
    count as "light browsing" when `skip_noise=True`.
  Noise captures are NEVER deleted: they stay in the SQLite DB and
  stay searchable through RAG. They just collapse to
  `_Light browsing: N low-signal capture(s) hidden by the noise
  filter._` in the per_poi rendering (offline + LLM + Jinja paths).
  Set `noise_min_ocr_chars = 0` to neutralize the filter even with
  the toggle on.

### Tests
- `tests/test_active_pois_and_noise_filter.py` (13 tests) — window
  shrinks the fallback list, top-K=2 keeps only two newest topics,
  window=0 / limit=0 return empty, defaults match Phase 1-A
  constants, partition returns all captures when off, partitions
  short captures when on, threshold ≤ 0 disables, `None` summary
  treated as zero, offline renderer appends the footer when
  `noise_count > 0`, end-to-end report contains
  `"Light browsing: 2 low-signal"` when toggled on, default-off path
  still renders the short capture individually.
- Total: 470 passed (was 457).

### Compatibility
- No schema migration. All four new fields are pure config additions.
- All four defaults preserve v0.12.0 behavior — upgrading users see
  zero change until they opt in via `config.toml`.

## v0.12.0 — Bucket-aware RAG + per-POI narrative reports (Phase 1-C) (2026-06-09)

Third of four POI-aware summarization releases. Pushes detected POI
buckets into the vector store so the RAG agent can scope searches by
topic, and adds a cached LLM-generated narrative paragraph per topic
section in per_poi reports.

### What changed
- **Vector store metadata enrichment.** `rin.rag.indexer.index_capture`
  and the summarizer's `_push_to_index` now attach `bucket_keys` (pipe-
  padded string like `"|topic:Atlas|topic:Beacon|"`) and a
  `bucket_ids_csv` companion to every Chroma upsert. Captures with zero
  buckets emit neither field so existing readers stay untouched.
- **POI-filtered search.** `rin.rag.search.search()` gains an optional
  `pois: list[str] | None` kwarg. Bare names are treated as topic POIs
  (`Atlas` → `topic:Atlas`); pass `skill:key` strings to target another
  skill (e.g. `support_ticket:T-1`). Filtering happens in Python after
  an inflated Chroma fetch (`k * 4`, capped at 50) because Chroma
  metadata is scalar-only.
- **Per-POI narrative paragraphs.** New `populate_poi_narratives()` runs
  before per_poi rendering. For each section with ≥3 captures and a
  reachable provider, it asks the LLM for a 2-3 sentence cross-capture
  story and attaches it to the section. Sections below the threshold
  or without a provider skip silently.
- **Narrative caching.** Cached on `reports.poi_narratives_json`
  (new column). Re-rendering the same report period reuses cached
  paragraphs verbatim instead of re-calling the LLM.
- **New CLI** `python -m rin reindex` re-upserts analyzed captures
  through `index_pending()` so users upgrading from v0.11.x can
  backfill the new metadata for old captures (search filters use
  forward-compatible pipe-substring matching, so this is opt-in).
- **Migration v6** adds `reports.poi_narratives_json` idempotently.

### Tests
- `tests/test_rag_indexer_bucket_metadata.py` (7 tests) — bucket key
  encoding, capture→buckets lookup, indexer + summarizer both write
  the new metadata, captures without buckets stay clean.
- `tests/test_rag_search_poi_filter.py` (10 tests) — needle
  normalization, partial-name disambiguation (`Atlas` ≠ `AtlasFrontend`),
  k cap respected, candidate-set inflation keeps k populated.
- `tests/test_reports_poi_narratives.py` (10 tests) — narrative gate
  on ≥3 captures + provider, cache hit avoids LLM, LLMError handled,
  narrative rendered in offline and end-to-end paths, JSON persisted.
- Total: 457 passed (was 430).

### Compatibility
- Old vector-store rows survive: `pois` filter rejects them, but
  unfiltered queries return them as before.
- New `reports.poi_narratives_json` column is `NULL` for legacy reports
  and ignored by readers that don't know about it.
- `reindex` is opt-in; new captures pick up the metadata automatically.

### Known limitations
- Narrative generation adds one LLM call per qualifying section per
  fresh report (cached on subsequent re-renders). With 5 active topics
  and a 3-capture threshold, that's at most 5 extra calls per daily
  report.
- Chroma `where` clauses can't filter on substrings of a string field,
  so POI filtering is post-query Python with an inflated fetch. For
  very large vector stores this may pull more vectors than necessary;
  scope this with `kind=` whenever possible.

## v0.11.0 — Structured per-POI rollup (Phase 1-B) (2026-06-09)

Second of four POI-aware summarization releases. Adds a structured
per-POI block to each capture's analysis so reports / RAG can render
topic-specific narratives instead of extracting topics out of a
paragraph.

### What changed
- **New column** `analyses.analysis_json` (additive). Schema:
  ```json
  {
    "schema_version": 1,
    "general_summary": "2-4 sentence paragraph (mirrors analyses.summary)",
    "poi_blocks": [
      {"poi": "Atlas", "block": "1-2 sentences about Atlas in this capture"}
    ]
  }
  ```
  `analyses.entities_json` stays as a deprecated alias; nothing reads it.
- **New `build_structured_summary()`** asks the LLM for the JSON object
  in one call. Falls back to plain `build_summary` (Phase 1-A behavior)
  on: no provider, no detected POIs, parse failure, or `max_blocks <= 0`.
- **New config** `cfg.analysis.max_poi_blocks_per_capture = 2`. Caps how
  many per-POI blocks the structured ask will request, bounding LLM cost
  when a single capture touches many topics.
- **Reports** automatically substitute the per-POI block for the general
  summary inside each topic section (per_poi layout). Falls back to
  general summary when a block is missing (handles old captures, partial
  responses, and disabled-block configs).
- **Migration v5** adds `analyses.analysis_json` idempotently. Skips
  silently if the table doesn't exist yet (covers test fixtures that
  predate `Base.metadata.create_all`).

### Tests
- `tests/test_analysis_structured.py` (10 tests) — JSON parse, schema,
  fence stripping, prompt cap behavior.
- `tests/test_structured_summary_pipeline.py` (9 tests) — provider
  flow: structured ask, JSON parse, fallback to plain on failure,
  cap honored, persistence into `analyses.analysis_json`.
- `tests/test_reports_per_poi_block_render.py` (3 tests) — section
  shows per-POI block; falls back to general summary when missing;
  end-to-end markdown contains the block text.
- Total: 430 passed (was 408).

### Compatibility
- Zero break for existing captures: `analysis_json` column added but
  reads tolerate `NULL` (defaults to `StructuredAnalysis()` with empty
  poi_blocks → renderer falls back to general summary).
- No backfill required.
- `cfg.analysis.max_poi_blocks_per_capture` defaults to 2; set to 0 to
  disable the JSON ask and keep Phase 1-A plain-prompt behavior.

## v0.10.0 — POI-aware summaries (Phase 1-A) (2026-06-09)

First of four releases that turn the POI system from a flat list into a
signal that actually steers the per-capture summary.

### What was wrong before
- `analyze_capture` summarized **first**, then classified into POI
  buckets afterwards. The summary prompt got fed **every configured
  POI name** regardless of whether the capture had anything to do with
  it. A user with 30 POIs would see all 30 names in every prompt,
  drowning out the actual content.
- `TopicSkill.set_provider()` existed but was **never wired** in
  production. Topics with `llm_judge=true` silently fell through to
  "no provider attached" without ever calling the LLM.

### What changed
- `classify_capture` now runs **before** `build_summary`. The summary
  prompt only lists POIs actually detected in the current capture.
- When this capture matched no POIs, the prompt falls back to the
  user's **top-5 most recently touched topics** (last 14 days) so
  cross-capture continuity is preserved without flooding the prompt.
- Hard cap of 5 POI names in the prompt regardless of source.
- New prompt language: `"This capture touched the following tracked
  topics: …. Focus your summary on what happened with them."`
- `classify_capture(..., provider=...)` now wires the provider into
  every skill that exposes `set_provider` (notably `TopicSkill`), so
  `llm_judge` actually fires for opt-in topics.

### Compatibility
- Zero schema changes.
- `_active_topic_names` kept for callers that still want the full
  configured list (now mostly used by tests + Settings UI preview).

### Tests
- `tests/test_summarizer_poi_aware.py` rewritten to assert the new
  detected-not-configured contract + the 5-POI cap + recent-history
  fallback (16 tests, was 8).
- New `tests/test_classify_before_summarize_ordering.py` (2 tests).
- New `tests/test_classify_capture_provider_wiring.py` (2 tests).
- Total: 408 passed (was 396).

## v0.9.1 — Installer winget multi-user fix (2026-06-09)

Bugfix release. Same day as v0.9.0. Fixes a real install failure
reported on a shared Windows machine where two user profiles (`yanden`
and `Yanbo`) both had ever launched `winget`.

### What broke
On multi-user Windows machines the App Execution Alias for `winget.exe`
can resolve to **another** user's per-user shim under
`C:\Users\<other>\AppData\Local\Microsoft\WindowsApps\winget.exe`. The
current user can't launch that file, so the FFmpeg install step
crashed with:

```
Program 'winget.exe' failed to run: An error occurred trying to start
process 'C:\Users\<other>\AppData\Local\Microsoft\WindowsApps\winget.exe'
... The system cannot find the path specified.
```

Root cause: `Install-PackageViaWinget` was calling `& winget install …`
and trusting PATH resolution. On a multi-user box that resolution
isn't guaranteed to be the current user's shim.

### The fix
New `Resolve-WingetPath` helper in `scripts/install.ps1`:

1. Probes `$env:LOCALAPPDATA\Microsoft\WindowsApps\winget.exe` first —
   this is **per-user** by construction so it's always the right shim
   for the current process owner.
2. Falls back to `Get-Command winget` only if the per-user path doesn't
   exist.
3. **Verifies** the candidate actually launches via `--version` before
   returning — a stale alias from a different user fails this probe.
4. Returns the absolute resolved path so `Install-PackageViaWinget` can
   call `& $wingetPath install …` instead of relying on PATH.

If no runnable winget is found, the script now also surfaces an
actionable hint pointing the user at the Microsoft Store **App
Installer** package.

### Tests
- **404 / 404 pytest pass** (was 402; +2 new install-script tests
  asserting the helper exists, probes `$env:LOCALAPPDATA` first, and
  that `Install-PackageViaWinget` no longer contains the buggy
  `& winget install` form).
- Parse-verified under both PowerShell 5.1 and PowerShell 7 — see the
  encoding memory; this script must be parseable under both because
  Explorer's "Run with PowerShell" defaults to 5.1.

### Upgrade
Same flow as any update:
1. Download `RIN-v0.9.1-windows-installer.zip` from the
   [Releases page](https://github.com/dengyanbo/RecordItNow/releases).
2. Quit RIN from the tray.
3. Extract and double-click `Install.bat`.

If the v0.9.0 install never completed on your machine because of this
bug, just download v0.9.1 and run `Install.bat` — the hardening from
v0.9.0 will detect any half-installed state and clean it up.

## v0.9.0 — In-app update story (2026-06-08)

Five hours after v0.8.1, shipping the missing update story end-to-end:
an in-app version check, a hardened installer that handles upgrades on
top of a running RIN, and the documentation that explains the flow to
end users. **Zero new Python dependencies** — the updater is stdlib-only
(`urllib` + `json`) and the privacy posture is unchanged: RIN still
never auto-downloads or auto-installs anything; it just notifies and
opens the GitHub release page in your browser.

### New features
- **In-app updater (`src/rin/utils/updater.py`)** — single outbound
  HTTPS request to `api.github.com/repos/dengyanbo/RecordItNow/releases/latest`
  with a 5 s timeout, throttled to once per 24 h via
  `%LOCALAPPDATA%\RIN\.update-check.json`. Returns an `UpdateInfo` with
  the latest tag, release URL, installer asset URL + size, and publish
  date. Skips drafts and pre-releases. Silent on offline / 403 / parse
  errors so the call is always safe to make in the background.
- **Tray menu entry** — `🔄 Check for updates…` between the diagnostic
  report and Quit actions. Click bypasses the 24 h throttle and toasts
  either "RIN vX.Y.Z is available" (click the balloon to open the
  release page) or "You're on the latest version".
- **Settings → About tab** — installed version chip, "Check for updates
  now" button + status label + release link, and an
  "Automatically check on startup" toggle (default ON, opt-out).
- **Startup auto-check** — 3 s after boot, RIN does a quiet
  throttled check. Only NEW versions raise a tray balloon; the
  "up to date" path is silent so we don't spam users every launch.
  Honors `RinConfig.auto_check_updates` (new top-level field, default `True`).
- **Installer hardening (`scripts/install.ps1`)** — detects a running
  `RIN.exe` whose binary lives under the install dir, asks it to close
  gracefully (`CloseMainWindow` + 5 s wait), then `Stop-Process -Force`
  as fallback. `Remove-Item` is wrapped in `Invoke-WithRetry` with
  1-2-4 s exponential backoff so the OS has time to release file
  handles. Together these eliminate the "cannot remove file in use"
  failure mode when re-running `Install.bat` to upgrade.

### Docs
- **README + README.zh-CN** — new "Updating" / "更新" section under
  Install describing the download → quit → double-click flow and
  reassuring that `%LOCALAPPDATA%\RIN\` data is preserved.
- **`scripts/README-INSTALL.txt`** — new ASCII "UPGRADING" block.
- **`docs/troubleshooting.md`** — new "Install fails with 'cannot
  remove file in use' / robocopy error" entry.
- **`.github/SECURITY.md`** — replaced the stale "no auto-update"
  blanket statement with the precise scope of the new check (one
  outbound HTTPS call per 24 h, never auto-installs, opt-out in
  Settings → About).

### Privacy / network footprint
- The update check is the only outbound network request RIN itself
  initiates. It can be disabled entirely via Settings → About →
  "Automatically check on startup" + never clicking "Check for
  updates now". When disabled, RIN makes zero outbound requests
  (LLM provider traffic is separate and only fires when you ask
  for an analysis or summary).

### Tests
- **402 / 402 pytest pass** (was 371; +15 updater tests,
  +1 config round-trip, +4 install-script parse tests,
  +6 tray menu/handler tests, +6 settings-about tests).
- ruff clean across `src/`, `tests/`, and `scripts/`.

## v0.8.1 — Stability + ergonomics polish (2026-06-08)

Six days after v0.8.0, rolling up three non-breaking post-release
improvements into a maintenance bump. No new wizards, no new APIs —
just stability and quality-of-life fixes the v0.8.0 launch surfaced.

### Highlights
- **Single-instance enforcement** — A second `RIN.exe` launch (double
  click, autostart re-fire, etc.) detects the running tray via an OS
  lock on `%LOCALAPPDATA%\RIN\.lock` and exits silently with a friendly
  MessageBox pointing at the tray. No more duplicate hotkeys or
  concurrent SQLite writers. `--smoke` bypasses the gate;
  `RIN_SUPPRESS_DUP_DIALOG=1` skips the modal for unattended launchers.
- **Numeric case + collab task IDs** — `support_ticket` skill now
  recognises 16-digit case IDs (`2606050030000773`) and 19-digit collab
  task IDs (`2606010050000901001`) out of the box, with a configurable
  `id_labels` setting that prepends `Case` / `Task` to bucket titles.
- **True one-click installer** — Single `RIN-v0.8.1-windows-installer.zip`
  asset replaces the previous two-zip split. End-user flow is now
  literally *download → extract → double-click `Install.bat`*; the
  bundle ships pre-extracted so install completes in ~19 s.

### Other fixes
- `pyproject.toml` version corrected (was stale at `0.7.1`).

### Tests
- 371 / 371 pytest pass (was 366; +5 single-instance tests).
- ruff clean across `src/`, `tests/`, and `scripts/`.

See the detailed "Post-release" subsections under v0.8.0 below for
implementation specifics on each item.

## v0.8.0 — PoI-centric Skills Workflow — turn passive captures into topic-organised reports

PoIs ("Points of Interest") let RIN track the people, projects,
customers, papers, and other named things that matter to you.
v0.8.0 turns passive capture history into a topic-aware workflow:
you can declare PoIs, discover candidates from recent activity,
mention them explicitly in summaries, and have reports group the
period around them when they are active.

### New features
- **Generic `topic` skill** — declarative PoIs via keywords / regex /
  aliases / optional LLM judge. Configure `[skills.topic].topics` in
  `config.toml`; no custom Python needed for the common "project /
  customer / paper / person" workflow.
- **PoI discovery service** — mines the last N days for candidate PoIs
  from repeated regex IDs, frequent domains, recurring title-case
  phrases, and an opt-in LLM batch. CLI: `python -m rin poi-discover
  [--days N] [--use-llm] [--persist]`.
- **PoI-aware summaries** — the final summary prompt now includes the
  user's active topic list, so tracked PoIs are named explicitly when a
  capture touches them.
- **Per-PoI report layout** — new `reports.layout =
  "auto"|"per_poi"|"chronological"` setting. `auto` flips to the
  per-PoI layout whenever any topic was touched during the report
  period, otherwise preserving the old chronological flow.
- **Settings → "Topics & PoIs" tab** — manage tracked PoIs,
  accept/reject discovery suggestions, and add topics manually from one
  place.
- **PoI onboarding wizard** — 4 pages: Welcome → Declare → Discovery →
  Confirm. Auto-shown once after `FirstRunWizard`, re-invokable from
  Settings.
- **`poi_candidates` SQLite table** — migration v4, idempotent,
  storing discovery suggestions separately from confirmed skill buckets.

### Internals
- `src/rin/skills/builtin/topic/` — new bundled skill.
- `src/rin/poi/` — new subpackage for discovery + persistence.
- `src/rin/ui/poi_tab.py` + `src/rin/ui/poi_wizard.py`.
- `ReportsConfig.layout` and `SkillsConfig.poi_wizard_seen` fields.
- `PoICandidate` SQLAlchemy model.

### Tests
**361 / 361 pass** (+55 since v0.7.1; 306 → 361). All green. Ruff
clean.

### Backwards compatibility
Users with no PoIs configured see **zero behavior change**:
chronological reports stay chronological, the wizard never appears,
and the existing `support_ticket` skill remains the recommended choice
for ticket-centric workflows.

**Release artefact**: source zip auto-built by `release.yml` on tag
push. The PyInstaller .exe bundle (~423 MB) will be built locally and
uploaded as a follow-up, mirroring the v0.7.1 process.

### Post-release: true one-click installer (2026-06-08)
- **Single asset**: `RIN-v0.8.0-windows-installer.zip` (~430 MB)
  replaces the previous two-zip split (`-windows-exe.zip` standalone
  bundle + `-windows.zip` install script). Only one download.
- **Only manual step is double-click**: zip ships with
  `Install.bat` (calls `install.ps1 -FromBundle bundle -Force` under
  the hood), pre-extracted PyInstaller bundle, install script,
  README-INSTALL.txt, and `version.txt` stamp.
- `install.ps1` gains `[string]$FromBundle = ''` parameter for the
  "copy this directory tree into `%LOCALAPPDATA%\Programs\RIN\`" path,
  uses `robocopy /E` for the 1+ GB tree (handles edge cases
  `Copy-Item` chokes on), auto-installs FFmpeg via winget when
  missing, and registers Start Menu shortcut.
- `Get-RinVersion` now reads `version.txt` first (so the installer
  banner correctly prints `(v0.8.0)` when running from a bundle that
  has no `src/__init__.py`).
- `build_exe.ps1` rewritten to stage the installer layout under
  `build\installer\` and zip via
  `[System.IO.Compression.ZipFile]::CreateFromDirectory` (avoids the
  PS 5.1 `Compress-Archive` quirk that silently drops subdirectories
  with `-Path "stage\*"`).
- Verified end-to-end: clean uninstall → fresh extract → double-click
  → install completes in 19 s, RIN.exe launches cleanly.

### Post-release: numeric case + collab task IDs (2026-06-08)
- `support_ticket` skill now recognises **16-digit numeric case IDs**
  (e.g. `2606050030000773`) and **19-digit numeric collab task IDs**
  (e.g. `2606010050000901001`) out of the box, alongside the existing
  ServiceNow / Salesforce / GitHub-style alphabetic prefixes.
- New `[skills.support_ticket].id_labels` setting prepends a
  human-readable word (`Case` / `Task`) to the bucket title so
  reports and the Archives UI visually separate the two families.
- Word-boundary anchors ensure the 19-digit pattern does not also
  spawn a phantom 16-digit bucket from its prefix; each ID gets
  exactly one bucket.
- Strict length-match between `id_patterns` and `id_labels` —
  mismatched lengths fall back to empty prefixes so custom regexes
  are never accidentally tagged `Case` / `Task`.
- 5 new tests in `tests/test_skills_base.py` (366 / 366 pass total).

### Post-release: single-instance enforcement (2026-06-08)
- Only one RIN instance per user can run at a time. A second launch
  (double-clicked shortcut, autostart re-fire, etc.) detects the
  existing instance via an OS-level exclusive lock on
  `%LOCALAPPDATA%\RIN\.lock` and exits silently with a Windows
  MessageBox: *"RIN is already running. Look for the RIN icon in your
  system tray."*
- The lock is auto-released by the OS when the process dies
  (clean exit, crash, or kill) — no stale-lock cleanup needed.
- `python -m rin --smoke` bypasses the gate so CI / smoke tests still
  run alongside a live tray.
- `RIN_SUPPRESS_DUP_DIALOG=1` skips the modal for unattended launchers
  that prefer a silent exit.
- New module `src/rin/utils/single_instance.py` (msvcrt on Windows,
  fcntl on POSIX). 5 new tests in `tests/test_single_instance.py`
  (371 / 371 pass total).

## v0.7.1 — Polish + first real .exe asset

Bug fixes, ergonomics, and the **first actually-built PyInstaller
bundle** attached to a GitHub Release. Non-developer users can now
unzip + run `RIN.exe` directly — no Python required.

### Bug fixes (found during full v0.7.0 e2e test)
- **`exporters.export_html/pdf(theme=None)` crash** (R20) — added a
  `_resolve_theme` helper that returns `rin.ui.theme.LIGHT` when the
  caller passes `None`. All three public functions now have a
  `theme: Theme | None = None` default. Both formats now produce
  valid output without requiring a live Qt `Theme` instance.
- **Tray context-menu cold first-click lag** (R21) — measured at
  ~470 ms (Qt scanning emoji-font metrics for action labels via
  `sizeHint()`). New `TrayApp._prewarm_menu()` runs
  `ensurePolished` + `sizeHint` + a hidden off-screen `popup()`
  250 ms after `tray.show()`. **Measured: first right-click drops
  from 550 ms to 3.8 ms — ~150× speedup.**
- **Misleading "Screenshot failed" toast** (R22) — pressing F12 while
  paused, blacklisted, or out of disk all showed the same generic
  warning. New `SkipInfo` frozen dataclass + `service.last_skip()`
  accessor + `tray._notify_skip()` map each skip reason to a
  context-appropriate toast (e.g. *Captures paused · Resumes at 17:06*
  at info level instead of *Capture failed* at warning level).
- **`PyInstaller` spec crash on first build** — `Tree()` returns
  3-tuples for `COLLECT`, not the 2-tuples `Analysis.datas` wants.
  Replaced with a local `_walk_as_datas` helper that produces the
  flat `(src, dst)` form.

### Ergonomics
- **Pause controls moved from tray menu into Settings → Privacy**
  (R23) — the tray right-click menu was getting cluttered. The
  persistent "Pause captures" checkbox now lives next to the privacy
  blacklist; immediate-apply "Pause for 15 minutes" / "Pause for 1
  hour" / "Resume now" buttons sit below it with a live status label
  ("Paused until 17:06"). The global Ctrl+Alt+Shift+P panic hotkey
  is unchanged.
- Tray menu trimmed from 10 items to 8.

### Distribution
- **🎁 First real one-click .exe** — `dist/RIN-v0.7.1-windows-exe.zip`
  (423 MB compressed, 1.1 GB unpacked). PyInstaller `--onedir` bundle
  covering ChromaDB, sentence-transformers, faster-whisper, RapidOCR,
  mss, pynput, hidapi, PySide6 plugins, every `rin.skills.builtin.*`
  subpackage, every `rin.llm.*` provider. Smoke-tested: 53 MB RAM,
  responding tray icon, clean schedulers, after a clean unzip.
- Spec excludes `torch.cuda` / `torch.distributed` / `torch.onnx` /
  `torch.testing` / `torch.utils.{tensorboard,benchmark}` since
  RIN's inference path never touches them. ~20 MB savings;
  `torch_cpu.dll` (294 MB) is irreducible.

### Cleanups
- **2 stale `TODO(Agent D)` comments** removed from `config.py`. Both
  were notes that Agent D in v0.6.0 actually fulfilled — the comments
  outlived their purpose.
- **`mss.mss()` → `mss.MSS()`** across 3 files (`monitors.py`,
  `screenshot.py`, `utils/diagnostics.py`). `mss` 10.2 deprecated the
  factory wrapper. Pytest warnings drop from 3 → 1 (the remaining is
  a chromadb 3rd-party deprecation).

### Tests
**306 / 306 pass** (+16 since v0.7.0):
- 9 new `tests/test_capture_skip_reasons.py` — every `SkipReason`,
  reset-on-success guard, frozen dataclass guard, double-start guard
- 7 new `tests/test_settings_pause_controls.py` — round-trip via
  `cfg.paused` checkbox, timed-pause apply, timed-pause clear,
  expired ISO handling, tray-menu-no-longer-has-pause, panic-toggle
  still-works guard

### Internal
- Version bumped to `0.7.1` in `src/rin/__init__.py` +
  `pyproject.toml`.
- `e2e_test_results` table populated with 12 phases of real-data e2e
  results from the v0.7.0 manual test session.
- `review_findings` got R20–R23 (one medium, three lows), all marked
  fixed.

---

## v0.7.0 — Second fleet release: the final v0.4 backlog

Closes out the four remaining todos from the v0.4 backlog that we
flagged as "needs its own session". They didn't — four more parallel
sub-agents shipped them cleanly along strict file-ownership lines.

This release drops the "Windows-only" sticker into "Windows-first":
every OS-specific code path now routes through a `platform_compat`
dispatcher with macOS and Linux stubs that import cleanly and return
sane defaults. A genuine cross-platform release can follow without a
rewrite.

### Distribution
- **True one-click installer** — new `scripts/RIN.spec` + `scripts/
  build_exe.ps1` produce a PyInstaller `--onedir` bundle suitable for
  shipping to non-Python users. `scripts/install.ps1` gains a
  `-FromExe` flag that simply extracts the bundle into
  `%LOCALAPPDATA%\Programs\RIN\` — no Python provisioning needed.
  Spec covers ChromaDB, sentence-transformers, faster-whisper,
  RapidOCR, mss, pynput, hidapi, PySide6 plugins, every
  `rin.skills.builtin.*` subpackage, every `rin.llm.*` provider.
  Bundle target 750-950 MB unpacked; the new `docs/build-exe.md`
  documents the trade-off of excluding `torch.cuda` /
  `torch.distributed` for a slimmer ship.
- **`pyinstaller>=6.0`** added to the `dev` extras group.

### Cross-platform (Windows still primary)
- **New module `src/rin/utils/platform_compat.py`** with a small,
  stable surface:
  - `is_windows() / is_macos() / is_linux()`
  - `list_audio_devices()` — Windows: DirectShow via ffmpeg.
    macOS / Linux: stubs returning `[]`.
  - `get_system_theme()` — Windows: `HKCU\Software\Microsoft\Windows\
    CurrentVersion\Themes\Personalize\AppsUseLightTheme`. macOS /
    Linux: returns `"light"` for now.
  - `enable_autostart(cmd)` / `disable_autostart()` — Windows: `HKCU
    \Run`. macOS / Linux: stub.
  - `get_foreground_window_title()` /
    `get_foreground_process_name()` — Windows: `win32gui` /
    `win32process`. macOS / Linux: stubs.
- **Three sibling modules** keep the Windows code (`_platform_windows`)
  isolated from the macOS / Linux stubs (`_platform_macos`,
  `_platform_linux`). The stubs **import safely** on Windows, with
  docstrings pointing at the future real implementations
  (CoreAudio, NSWorkspace, NSUserDefaults, LaunchAgent plist, X11 /
  Wayland window title, PulseAudio, GTK Settings, `.desktop`
  autostart).
- `pywin32` is now declared with a `sys_platform == 'win32'` PEP 508
  marker so a future `pip install rin` on macOS / Linux doesn't try
  to pull the Windows-only package.

### Calendar integration (optional)
- **`src/rin/reports/integrations/`** — new package with `base.py`
  (`CalendarEvent` frozen dataclass + `CalendarProvider` ABC),
  `outlook.py` (Microsoft Graph via `msal` + `requests`),
  `google.py` (Google Calendar via `google-auth-oauthlib` +
  `googleapiclient`), and `factory.py` (`make_calendar_provider(cfg)`).
- **OAuth tokens via OS keyring** — `rin-outlook-calendar` and
  `rin-google-calendar` services. Outlook uses MSAL cache + silent
  refresh; Google stores credentials with the refresh token path.
- **Lazy imports throughout** — none of the calendar packages are
  imported until the user actually picks a provider. Default install
  doesn't pull them.
- **Reports → Reports tab** in Settings gains a calendar-provider
  dropdown + "Sign in…" button that runs the OAuth flow on a
  `QThreadPool` so the dialog never blocks.
- **`reports/generator.py`** injects a `## Calendar` section into the
  prompt material when a provider is configured. Fetch failures are
  logged + the report still produces output without the section.
- New `[calendar]` extras group:
  `[msal, requests, google-auth-oauthlib, google-api-python-client]`.

### Encryption at rest (optional)
- **`src/rin/utils/encryption.py`** — `CaptureCipher` wraps an
  AES-256-GCM key, with the key file at
  `%LOCALAPPDATA%\RIN\.master.key.enc` sealed by Windows DPAPI
  (`win32crypt.CryptProtectData`).
- `encrypt_file(src, dst)` / `decrypt_file(src, dst)` write a 12-byte
  random nonce + ciphertext; tampered ciphertext raises
  `cryptography.exceptions.InvalidTag` on read.
- **Capture path**: when `cfg.privacy.encrypt_at_rest=True`, the
  recorder + screenshotter rename their output to `*.enc` and the DB
  row's `path` points at the encrypted file.
- **Analysis path**: `image_analyzer` and `video_analyzer` decrypt
  `*.enc` files into a `tempfile` before handing them to OCR /
  ffmpeg; the temp file is cleaned up afterwards.
- **Settings → Privacy tab** gains an "Encrypt captures at rest
  (Windows DPAPI)" checkbox + a hint about the analysis-time
  trade-off.
- Default OFF. Zero regression for users who don't opt in.

### Tests
**290 / 290 pass** (+30 since v0.6.0):
- Calendar ×10 (base, outlook, google, factory, generator-with-calendar)
- Cross-platform ×9 (compat dispatcher, macOS stub, Linux stub)
- Encryption ×7 (round-trip, nonce uniqueness, tamper detection,
  file streaming, capture integration)
- PyInstaller adds no tests (the build artefact is verified manually)

### Internal
- Version bumped to `0.7.0` in `src/rin/__init__.py` +
  `pyproject.toml`.
- 12 modified + 22 new files. Zero collisions on the still-hot files
  (`config.py`, `ui/settings_dialog.py`, `pyproject.toml`,
  `capture/screenshot.py`) thanks to explicit file-ownership lines in
  each agent's prompt.

### Decisions of record
- **Cross-platform is "scaffolding", not "shipping"** — every dispatcher
  has a real Windows implementation; macOS / Linux paths import safely
  + return defaults. The actual native implementations are tracked
  separately in plan.md.
- **Calendar packages are optional** — `[calendar]` extras group, not
  in `dev` or `all`. Lazy imports inside every method that touches
  the relevant SDK.
- **Encryption is opt-in default OFF** — no behavioural change for
  existing users. A user enabling encryption later cannot decrypt
  pre-encryption captures, by design.
- **PyInstaller spec uses `--onedir`, not `--onefile`** — ChromaDB
  needs a directory layout to load its native libraries at runtime.

---

## v0.6.0 — Fleet release: 11 features in one batch

Eleven backlog items landed in parallel via four sub-agents along
clean file boundaries: a quality benchmark suite, three capture-side
features, three reports features, and four Settings / boot features.
Every collision risk on shared files (`config.py`, `pyproject.toml`,
`ui/settings_dialog.py`) was avoided by explicit ownership lines in
each agent's prompt.

### Capture pipeline
- **Thumbnails** — every capture writes a 240×135 RGB JPG quality-80
  sidecar next to its PNG / MP4. New column `captures.thumbnail_path`
  added via migration v2. New helper `rin.utils.thumbnail.make_thumbnail`.
- **Quick-note overlay** — opt-in 5-second mic-only recording fires
  right after a screenshot; saved as `quick_note.wav` (16 kHz mono) in
  the capture folder. Toggled via Settings → Capture → *Enable quick-note*.
- **Privacy blacklist** — Settings → Privacy: list of app / window
  title patterns to skip. Foreground-window lookup uses `win32gui`,
  fails safe (lets the capture through on a Win32 hiccup). Tray gains
  **⏸ Pause captures for 15 min** which writes
  `cfg.privacy.paused_until_iso` so even the trigger key is gated.

### Reports
- **Cross-report search** — SQLite **FTS5** virtual table over a new
  `report_text` mirror table, kept in sync via INSERT / UPDATE /
  DELETE triggers (migration v3, idempotent). New module
  `rin.reports.search` with `search_reports(query, limit)` returning
  ranked hits with 240-char snippets. Search box above the saved-reports
  list in Reports window. Historical reports back-filled from disk.
- **Report export (PDF / HTML)** — new `rin.reports.exporters` module
  with `export_pdf` (QTextDocument + QPrinter) and `export_html`
  (standalone with embedded `<style>`, no external links). Toolbar
  buttons in Reports window open a `QFileDialog`.
- **Obsidian / Notion target** — new `cfg.reports.obsidian_vault_path`.
  When set, each generated report also writes to
  `<vault>/Daily/YYYY-MM-DD.md` (or `Weekly/`) with YAML front-matter
  (`date`, `kind`, `captures`, `generated_by: RIN`).

### Settings / app boot
- **Data export & import** — Settings → Data → *Export everything*
  produces a zip containing `config.toml` (with API keys scrubbed via
  `diagnostics._redact_config_text`), a locked-copy SQLite snapshot,
  the ChromaDB folder, every saved report, and per-capture summaries
  as JSONL. *Import* round-trips it on a new machine and refuses to
  overwrite a non-empty data directory unless explicitly confirmed.
- **OCR + Whisper picker** — Settings → Analysis: multi-select OCR
  language list (en / ch_sim / ja / ko / de / fr / es) wired into
  RapidOCR, plus a Whisper model dropdown (tiny / base / small /
  medium / large-v3) with a memory-cost hint. Replaces the previously
  hard-coded values.
- **Opt-in error telemetry** — Settings → Advanced: enable + DSN field
  for `sentry-sdk` (new `telemetry` extras group; not installed by
  default). Self-host hint link to Sentry's docs. Default OFF.
  Installed lazily from `app.run` so a missing import is a no-op.
- **First-run wizard** — `FirstRunWizard(QWizard)` with 5 pages
  (Welcome / Pick trigger via learn-mode / LLM provider / Working
  hours / Done). Shown by `app.run` if `cfg.first_run_completed` is
  False and `--smoke` is not set. Saves the new
  `cfg.first_run_completed = True` on Finish.

### Quality
- **Performance benchmarks** — new `pytest-benchmark` suite
  (`tests/test_perf_*.py`) covering the four hot paths:
  - `screenshot.capture_all` — current mean **2.77 ms** (target ≤ 200 ms)
  - `Recorder.start / stop` — **12.21 ms** (target ≤ 100 ms)
  - `analyze_image` — **0.94 ms** mocked (target ≤ 1.5 s)
  - `embedder.embed_batch(10)` — **0.016 ms** mocked (target ≤ 500 ms)
  Thresholds are informational; tests don't `assert` so the suite
  stays green even on slower runners. `pytest-benchmark>=4.0` added to
  `dev` extras.

### Tests
**260 / 260 pass** (+27 since v0.5.0):
- Thumbnails ×3, quick-note ×2, privacy ×4
- Reports search ×1, exporters ×2, Obsidian ×2
- Data export ×2, OCR/Whisper ×1, telemetry ×3, wizard ×3
- Benchmarks ×4

### Internal
- Version bumped to `0.6.0` in `src/rin/__init__.py` +
  `pyproject.toml`.
- 14 modified files, 21 new files. Every modification respected the
  file-ownership lines specified in the parallel-agent prompts; the
  shared files (`config.py`, `pyproject.toml`, `ui/settings_dialog.py`)
  merged cleanly without manual intervention.
- Storage schema is now at migration version 3 (v2 = thumbnails, v3 =
  FTS5 `reports_fts` + `report_text` mirror + triggers).
- Boot order: `setup_logging` → `telemetry.install` → `init_db` →
  `build_app` → wizard (if first run) → `tray.start`.

### Decisions of record
- **Sub-agent boundaries** were strict enough to avoid every shared
  file conflict. The model used to surface Agent B's privacy fields
  + Agent B's quick-note fields + Agent C's Obsidian path from
  Agent D's Settings dialog passes: Agent D adds Settings UI; other
  agents only add config fields with explicit comments naming the tab
  that will surface them.
- **Sentry is optional** — `[project.optional-dependencies] telemetry`
  is its own group, not in `dev` or `all`. Users opt in with
  `pip install rin[telemetry]`.
- **PDF / HTML export does NOT need the QThreadPool dance** — both
  finish in < 200 ms even on a 100-page report, so they run on the Qt
  main thread.
- **First-run wizard gates on `cfg.first_run_completed`** (not just
  trigger.source unset) so the user can intentionally re-trigger it
  later by editing config.

### Deferred to a later release (each warrants its own session)
- `v0.4-cross-platform` — full macOS + Linux port
- `v0.4-pyinstaller-exe` — true one-click .exe distribution
- `v0.4-calendar-integration` — Outlook / Google Calendar APIs (OAuth)
- `v0.4-encryption-at-rest` — DPAPI-protected captures

---

## v0.5.0 — Skills (pluggable categorization)

Captures no longer have to live in a flat stream. A new **skill**
plugin system lets each user slice their corpus into buckets that
match how they actually work — by support-ticket ID, by research
paper, by 1:1 partner, by whatever pattern the skill author cares to
detect. When a bucket finishes, the skill renders a Markdown archive
that summarises the whole journey.

### Bundled `support_ticket` skill (the tech-support workflow)

Group captures by ticket ID across ServiceNow (`INC0012345`,
`REQ0012345`, `SR1234567890`), Salesforce (`CASE0007890`), or
GitHub-style (`#1234`). When any capture in the bucket mentions a
closed phrase (`Status: Closed`, `marked as resolved`, …) or the
bucket goes 14 days without new captures, the `BucketScheduler`
archives it.

The default archive uses the configured LLM to render a structured
post-mortem (`Customer problem` · `Investigation timeline` · `Root
cause` · `Resolution` · `Lessons learned`) with `cap-N` citations.
Falls back to a chronological template offline.

### How a custom skill works

Drop a folder under `%LOCALAPPDATA%\RIN\skills\<name>\` containing a
`skill.py` that exports a module-level `SKILL` instance. The registry
discovers it, validates its `[skills.<name>]` TOML against the skill's
optional `Config` Pydantic schema, and enables it as soon as the user
ticks the box in Settings → Skills. Full guide: [`docs/skills.md`](docs/skills.md).

### Added
- **New module**: `src/rin/skills/`
  - `base.py` — `Skill` ABC plus the frozen DTOs `BucketRef`,
    `SkillContext`, `CaptureInfo`. Default `render_archive` is a safe
    chronological dump.
  - `registry.py` — discovers bundled skills under
    `rin.skills.builtin.*` and user skills under
    `paths.skills_dir()`; validates each skill's TOML against its
    `Config` schema; returns `LoadedSkill` instances.
  - `pipeline.py` — `classify_capture(capture_id, cfg, …)` is called
    from `analyze_capture` after each `Analysis` row commits. UPSERTs
    `Bucket` rows on `(skill_name, key)`, inserts `CaptureBucket`
    junction rows, isolates per-skill exceptions.
  - `scheduler.py` — `BucketScheduler` periodic job (default 6 h)
    that runs `should_close` against every active bucket and calls
    `archive_bucket` for buckets that report done.
  - `builtin/support_ticket/` — the example skill.
- **New storage**:
  - `Bucket(id, skill_name, key, title, extra_json, status,
    opened_at, closed_at, archive_path)` with `UNIQUE(skill_name,
    key)`.
  - `CaptureBucket(capture_id, bucket_id, created_at)` junction —
    one capture can sit in N buckets across M skills.
  - Migration (version 1) creates both tables idempotently.
- **New config**: `SkillsConfig(enabled, user_skills_dir,
  closure_check_hours)` plus `extra="allow"` so per-skill TOML
  sections `[skills.<name>]` are preserved without the static schema
  having to know about every installed skill.
- **New paths**: `paths.skills_dir()` (default `%LOCALAPPDATA%\RIN\
  skills`) and `paths.archives_dir()` (default `%LOCALAPPDATA%\RIN\
  reports\archives`).
- **Settings → Skills**: new tab between *Analysis* and *Reports*. Lists
  every discovered skill as a card (display name + version chip +
  source chip + description + Enabled toggle). "Open skills folder…"
  link drops the user into `%LOCALAPPDATA%\RIN\skills\` via
  `os.startfile`. Includes a privacy warning about arbitrary code
  execution.
- **Reports window → Archives section**: side rail gains a list below
  the daily/weekly cards. Each entry shows `<skill_name> · <key>`;
  clicking renders the archive Markdown in the right pane (same QSS
  treatment as a report).
- **Tray + boot**: `BucketScheduler` is instantiated by `TrayApp` and
  starts/stops alongside the other schedulers. No new tray menu items.
- **Docs**: new [`docs/skills.md`](docs/skills.md) — user guide,
  custom-skill recipe with a minimal example, security warning, data
  layout.

### Tests
**233 / 233 pass** (+21 since v0.4.2):
- 8 unit tests covering `BucketRef` / `SkillContext` immutability,
  `_default_archive` chronology, `support_ticket` detect / closure /
  archive, registry discovery for bundled + user-drop-in skills,
  graceful skip of broken user skill, and a custom-`Config`
  smoke test.
- 4 end-to-end tests with the 5-capture fixture from `plan.md`: bucket
  linking, junction-row uniqueness, archive Markdown contents, "skill
  off" no-op, and idempotent re-classification.
- All 9 prior progress-widget tests still green.

### Internal
- Version bumped to `0.5.0` in `src/rin/__init__.py` +
  `pyproject.toml`.
- `analysis/summarizer.py` calls `classify_capture` after each
  successful `Analysis`; failures are logged and isolated so one bad
  skill cannot break the batch.
- `ui/tray.py` constructs + manages a `BucketScheduler`.
- `storage/__init__.py` re-exports `Bucket` and `CaptureBucket` for
  callers that want direct ORM access.

### Decisions of record
- **Multi-bucket per capture** — a single capture can match multiple
  skills *and* multiple buckets within a single skill (no first-match
  cap).
- **No skill enabled by default** — backwards-compat with v0.4. Users
  opt in via the Settings tab.
- **Closure detection = regex + inactivity timeout by default** —
  LLM-driven closure is opt-in per skill (`use_llm_for_closure`).
- **Archive rendering = LLM by default** — one call per ticket close
  is worth the artefact quality. Falls back to template offline.
- **Drop-in skills, not pip packages** — pip-installable skills
  (`rin-skill-*`) can come later; file-drop is the simplest contract.

---

## v0.4.2 — Spinners + busy overlays (no more freezes)

Long-running operations no longer block the Qt main thread. Every
sync call to an LLM, embedder, or ffmpeg subprocess that used to
freeze the UI for tens of seconds now runs on a worker, and the
affected pane shows a clear busy state.

### Added
- **`src/rin/ui/progress.py`** — two new reusable widgets:
  - `Spinner(size, accent, thickness)` — a rotating-arc indeterminate
    indicator drawn from scratch with `QPainter`. ~30 FPS. Starts/stops
    via `start()` / `stop()` (also auto-starts on `showEvent`).
  - `BusyOverlay(parent, message, theme)` — a semi-transparent surface
    that covers any parent widget, centers a `Spinner` + message label,
    and absorbs mouse events so the caller can't double-fire the
    operation. Tracks parent geometry via an event filter.
- Exported from `rin.ui.__all__` so other code can import them directly.

### Changed
- **Reports window**: `generate_report()` is now dispatched through a
  `QRunnable` task on `QThreadPool.globalInstance()`. While running, a
  `BusyOverlay` covers the right-pane viewer with the message
  `Generating today's report…` / `Generating this week's report…`, and
  the `Today` / `This week` / `Refresh` buttons disable themselves
  until the worker emits `done` or `failed`. Errors surface in the
  viewer with a hint pointing to the diagnostic-report flow.
- **Settings → Capture → Audio device**: enumeration shells to ffmpeg
  (1-3 s on a typical PC). Refresh is now async: the `Refresh` button
  hides itself and an inline 18 px spinner spins in its slot until the
  worker delivers the device list. Failures keep the previous list
  intact and tag the button's tooltip with the error.
- **Settings dialog open**: previously the dialog blocked on the
  initial audio enumeration. Now `load_from_config` seeds the combo
  with the currently saved device and kicks off the async refresh — the
  dialog opens instantly even on the first show.
- **Search & Ask window**:
  - The results pane now switches to a centered `Spinner` + label
    (`Searching captures…`) while the search worker runs, instead of
    showing a plain "Searching…" placeholder row.
  - The "agent is thinking" chat bubble now contains a real `Spinner` +
    `Thinking…` label, replacing the static text-only bubble.

### Tests
**212 / 212 pass** (+9 since v0.4.1):
- Spinner default size + custom size + accent setter
- Spinner start/stop idempotency
- Spinner minimum-size clamp at 12 px
- BusyOverlay constructs hidden
- BusyOverlay message round-trip
- BusyOverlay theme swap
- BusyOverlay tracks parent resize via event filter

### Screenshots
`docs/screenshots/after/` adds:
- `spinner_gallery_{light,dark}.png` — 16 / 20 / 24 / 32 / 40 px spinners
- `reports_busy_{light,dark}.png` — `BusyOverlay` covering the viewer
- `search_busy_{light,dark}.png` — spinner placeholder in results +
  thinking bubble in chat

### Internal
- Version bumped to `0.4.2` in `src/rin/__init__.py` and
  `pyproject.toml`.
- `reports_window.py` gained `_ReportSignals` + `_GenerateReportTask`.
- `settings_dialog.py` gained `_AudioRefreshSignals` +
  `_AudioRefreshTask` and split the sync `_populate_audio_combo` into a
  small `_apply_audio_devices` (UI mutation only) + async path.

---

## v0.4.1 — Fine-grained UI polish

The v0.3.2 redesign got the layout right but the details still felt
unfinished — washed-out field labels, ungrouped trigger controls, full-
width primary buttons fighting for attention, plain-text empty states,
nav-rail icons that disappeared in dark mode. This release goes through
every visible widget and tightens the details.

### Settings dialog
- **Nav rail** now uses a subtle ``accent_subtle`` background + a
  **3 px left accent stripe** on the selected row (Fluent 2 pattern)
  instead of the saturated-blue blob. Icons are recoloured per-theme.
- **Page headers** now use the Segoe UI Variable *Display* family with
  a supporting caption sourced from each nav item, so every page starts
  with a clear "what is this section for?" line.
- **Trigger row** binds the captured key + the Learn button into a
  single visually grouped row: the key reads as an accent-tinted chip
  (e.g. ``F12``) instead of a floating "Key: f12" label.
- **Field labels** are now SemiBold + body-text colour (not the washed
  ``text_muted``); hints are smaller + render directly below the input
  they describe via the new ``role="field-hint"`` selector.
- **Input widths** are pinned per tier (number / picker / text / URL)
  with ``setFixedWidth`` — ``setMaximumWidth`` was being ignored by
  ``QFormLayout`` and inputs were stretching the whole row.
- **Save / Cancel** buttons get a ``min-width: 96`` so they read as
  distinct affordances, not narrow ovals.

### Reports window
- Card content tightened: large date + ``Daily`` / ``Weekly`` chip on
  one row, file name as a caption below.
- Action row replaces the stacked full-width buttons with a single
  row: ``Generate → [Today] [This week]`` on the left, ``Refresh``
  flat link on the right.
- Empty state in the right pane now leads with a tinted document icon
  before the heading and supporting text.
- Vertical divider between rails draws a real 1 px line via
  ``role="divider-vert"``.

### Search & Ask window
- **Combined search bar**: the input + "Search" button share a single
  rounded shape via ``role="search"`` + ``role="search-attached"``.
  Same treatment for the Ask box + Send button.
- **Distinct chat bubbles**: user bubbles use the accent-tinted
  ``accent_subtle`` fill with a tail on the bottom-right; agent
  bubbles use the surface colour with a tail on the bottom-left.
- Citations under an answer render as compact accent chips
  (``cap-3`` ``cap-7``) instead of an inline comma-separated string.
- Empty states for both panes now show a tinted SVG icon
  (``search`` / ``chat``) above the heading.

### Design tokens (``theme.py``)
- **New typographic ramp** with a ``font_size_display`` (22 pt) for
  hero headings + ``font_family_display`` ("Segoe UI Variable Display")
  applied to ``heading="hero"`` / ``heading="h1"`` selectors.
- **New colour tokens**: ``accent_subtle`` (computed via a flat blend
  with the background per theme), ``surface_card``, ``border_strong``,
  ``focus_ring``.
- Tighter neutrals: borders ``#E5E5E5 → #D6D6D6`` (light) and
  ``#3F3F3F → #484848`` (dark) for crispness on hi-DPI; muted text
  bumped slightly for readability.
- ``radius_chip`` token added (12 px).

### Stylesheet (``style.py``)
- **Focus rings** now visible on every input and button: a 2 px solid
  ``focus_ring`` border with auto-adjusted padding to prevent layout
  shift on focus.
- **Hover affordance** on default buttons: border colour bumps to
  ``text_muted``, background to ``surface_hover``.
- **Chip widget** (``role="chip"``): an inline pill, optionally
  ``accent="true"`` for the tinted variant used by the trigger key +
  citation badges.
- **New selectors**: ``role="user-bubble"``, ``role="agent-bubble"``,
  ``role="search"``, ``role="search-attached"``, ``role="field-hint"``,
  ``role="divider-vert"``, ``role="icon"``, ``heading="hero"``,
  ``heading="subtle"``.

### Icon system (``icon.py``)
- New ``tinted_icon(name, color, sizes=...)`` factory loads any bundled
  Fluent SVG and recolours its fill at render time. Multi-resolution
  ``QIcon`` returned. Used by the nav rail (theme-aware), empty states,
  and chip indicators.
- ``_read_svg`` is now ``functools.lru_cache``'d (small bundled assets
  on a hot render path).
- New ``icon_size_for(rule)`` helper returns canonical Qt icon sizes
  (``nav`` / ``menu`` / ``card`` / ``empty-state`` / ``button``).

### Tests
**203 / 203 pass** (+8 since v0.4.0):
- 6 new theme/QSS assertions: accent-subtle blending, focus-ring
  presence, every new ``role="…"`` / ``heading="…"`` selector renders.
- 2 new icon factory tests: ``tinted_icon`` recolours a known asset to
  the requested fill; canonical sizes are reasonable.

### Screenshots
`docs/screenshots/before_v041/` captures the v0.4.0 baseline;
`docs/screenshots/after/` overwritten with the new pass. Light + dark.

### Internal
- Version bumped to ``0.4.1`` in ``src/rin/__init__.py`` and
  ``pyproject.toml``.

---

## v0.4.0 — Project hygiene + small polish

Focus of this release is making RIN a healthy open-source project: real
CI, proper governance docs, a diagnostic-report helper for support
cases, and a few quality-of-life touches.

### Added
- **GitHub Actions CI** (`.github/workflows/ci.yml`) — runs ruff +
  pytest + smoke on `windows-latest` for Python 3.11 and 3.12 on every
  push and PR. Uploads coverage XML as an artefact.
- **Automated release workflow** (`.github/workflows/release.yml`) —
  on `git push --tags v*.*.*` builds the release zip via
  `scripts/build_release.ps1 -SkipChecks` and publishes a GitHub Release
  with the asset. No more manual `gh release create`.
- **Diagnostic-report helper** — new tray menu entry **🩺 Generate
  diagnostic report** (also runnable as `python -m rin.utils.diagnostics`).
  Writes a redacted zip containing `config.toml` (API keys scrubbed),
  recent `rin.log` files, Python / OS / FFmpeg versions, monitor list,
  `pip freeze`, and corpus-size counts (no captures, no summaries).
  Safe to share on issues.
- **Reserved-key warning in learn mode** — `LearnRecorder` now exposes
  `.reserved_warning` (`(reason, severity)` tuple). The Settings dialog
  and onboarding flow can use this to warn before saving a binding like
  `Alt+Tab`, `Ctrl+C`, or `Enter`. Table of reserved combinations lives
  in `src/rin/input/reserved_keys.py`.
- **Code coverage configuration** — `[tool.coverage]` in `pyproject.toml`
  with branch coverage on, omitting purely Qt-loop code from the
  reporting target. CI uploads the `coverage.xml`.
- **Governance documents**:
  - `CONTRIBUTING.md` — dev setup, branch naming, commit style,
    co-author trailer, and "the five hard rules" (no GPL deps, no
    bundled FFmpeg, UTF-8 subprocess decoding, Qt-main-thread
    marshalling, no hard-coded styling).
  - `SECURITY.md` — disclosure process via GitHub Security Advisories.
  - `CODE_OF_CONDUCT.md` — Contributor Covenant 2.1.
  - `.github/ISSUE_TEMPLATE/{bug,feature,config}.yml` — structured
    issue forms.
  - `.github/pull_request_template.md` — PR checklist enforcing the
    five rules.
- **Architecture deep-dive** — `docs/architecture.md` with Mermaid
  sequence diagrams for the three core flows (tap → captured row,
  analysis tick → summary → vector, user asks → RAG answer).
- **Troubleshooting guide** — `docs/troubleshooting.md` consolidating
  every known failure mode (RDP gdigrab, ffmpeg stderr deadlock,
  cp1252 UnicodeDecode, missing winget, …) plus the diagnostic-report
  workflow.

### Tests
**195 / 195 pass** (+19 since v0.3.2):
- 10 for `input.reserved_keys.lookup_reserved`
- 7 for `utils.diagnostics.build_report` (config redaction, missing
  config, empty root, monitor enumeration, capture counts)
- 2 extra `LearnRecorder` cases (reserved-key surfaced as warning)

### Internal
- Project version bumped to `0.4.0` in `src/rin/__init__.py` and
  `pyproject.toml`.
- `src/rin/input/__init__.py` re-exports `RESERVED_KEYS` and
  `lookup_reserved` for downstream code.

---

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
