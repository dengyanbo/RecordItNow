# Points of Interest (PoIs)

> Turn passive captures into topic-organised reports.

## What is a PoI?

A PoI is something you want RIN to **group your captures by**. That might be a
project, a customer, a paper, a team, a codename, or a person you work with
often.

When RIN analyzes a new capture, it scans the OCR text, the transcript, and
the summary for your configured PoIs. If a PoI matches, RIN links the capture
to that PoI's bucket. Your reports can then show one section per PoI instead
of one long chronological blob.

Think of PoIs as your personal filing system for passive capture. They answer
questions like:

- "Show me everything about Project Atlas this week."
- "Group my notes by customer, not by timestamp."
- "Keep the release report focused on the initiatives I actually care about."

PoIs are usually best for **named topics**. If your workflow revolves around
precise ticket IDs, RIN's bundled `support_ticket` skill is still the better
fit. You can also run both skills together.

## Three ways to establish PoIs

You do not need to hand-edit TOML if you do not want to. RIN supports three
practical entry points:

1. **The wizard** — After RIN's initial setup, the PoI wizard appears once.
   It walks you through declaring a few PoIs, running discovery, and
   confirming what should be tracked.

2. **Settings → Topics & PoIs** — This is the everyday control panel. You can
   add, edit, pause, archive, accept suggestions, reject noise, and save
   changes whenever you like.

3. **The CLI — run discovery on your own schedule** — `python -m rin
   poi-discover --days 14` mines your recent captures for likely PoIs. You can
   click **Discover now…** in Settings, run the command manually, or schedule
   it yourself with Task Scheduler. RIN itself does **not** run discovery
   automatically.

The important model is: **discovery suggests; you decide.** Nothing becomes an
active tracked PoI until you accept it.

## Quick start

The fastest path is to add one PoI manually, then watch one report group
itself around that topic.

1. Open **Settings → Topics & PoIs**.
2. Click **Add manually**.
3. Enter a short, stable name. Good names are things like `Project Atlas`,
   `Northwind`, or `Fulfillment rewrite`.
4. Add a description if the name needs context. This helps you later, and it
   gives the optional LLM judge more signal.
5. Add one or more **keywords**. Start with the obvious words you already type
   or see on screen.
6. Add **aliases** if the topic is known by multiple names. Example: `Atlas`,
   `Atlas rollout`, `fulfillment rewrite`.
7. Add **regex** only if the topic has a stable ID pattern. Example:
   `JIRA-\d+`, `GH-\d+`, `INC\d{7}`.
8. Decide whether to enable **LLM judge**. Leave it off unless your topic is
   genuinely fuzzy.
9. Click **Save**.
10. Trigger a capture that clearly mentions the PoI.
11. Run **Analyze now** if you do not want to wait for the scheduler.
12. Open **Reports** and generate today's report.
13. Confirm a `## <PoI name>` section appears.

> [screenshot placeholder: Settings → Topics & PoIs tab]
>
> [screenshot placeholder: Add manually form]
>
> [screenshot placeholder: report grouped by PoI]

A few naming tips help immediately:

- Prefer names you would be happy to read as report headings.
- Put the human-readable topic in `name`; keep machine-shaped IDs in `regex`.
- Start narrow. It is easier to broaden a PoI later than to clean up an overly
  broad topic.

If you are unsure what to add, start with three PoIs max. That keeps reports
readable and makes discovery suggestions easier to review.

## The four match strategies

Each PoI can combine keywords, regex, aliases, and an optional LLM judge. Most
users start with keywords + aliases, add regex when a stable ID exists, and
only enable the judge when the topic is genuinely fuzzy.

### 1) Keywords

Keywords are case-insensitive substring matches. Use them when the topic has a
distinctive visible name such as `atlas` or `fulfillment rewrite`. Avoid very
generic words like `api` or `meeting` unless you narrow them with aliases or an
LLM judge.

### 2) Regex

Regex is the right tool for stable identifiers such as `JIRA-\d+`, `GH-\d+`,
`INC\d{7}`, or `CASE\d{6,8}`. If the wording changes but the identifier stays
fixed, regex is usually the strongest signal.

### 3) Aliases

Aliases are alternate human names for the same PoI: abbreviations, codenames,
renamed projects, or customer shorthand. A topic named `Project Atlas` can
still match `atlas rollout` and `fulfillment rewrite` without turning the main
name into an unreadable keyword list.

### 4) LLM judge (optional)

If `llm_judge = true`, RIN asks your configured provider whether a capture is
really about the PoI. Use it for semantic edge cases only. Keywords, regex, and
aliases are free; the judge may consume tokens, and `llm_judge_max_chars` caps
the text sent.

### Match order in practice

Think regex first, then keywords / aliases, then the optional judge. That keeps
the common path cheap and predictable.

## Discovery

Discovery turns recent history into **candidate PoIs**. It never enables a
tracked topic by itself; it only surfaces suggestions worth reviewing.

Start it from:

- **Settings → Topics & PoIs → Discover now…**
- the onboarding wizard
- `python -m rin poi-discover --days N`

Discovery mines four signal types:

- **Regex mining** — repeated machine-shaped IDs across captures
- **Domain mining** — recurring hostnames seen in OCR'd URLs
- **Phrase mining** — repeated Title Case phrases like `Project Atlas`
- **LLM batch** (`--use-llm`) — one model call over sampled summaries to
  extract named entities or workstreams that local passes might miss

By default the CLI is a dry-run and prints suggestions. Add `--persist` to save
them into `poi_candidates` for later review in the UI. Candidate status values
are `pending`, `accepted`, `rejected`, and `merged`; a candidate stays a
suggestion until you accept it.

## Archive lifecycle

A PoI stays active while captures keep touching it. RIN can mark a topic as
done in three common ways.

### 1) Inactivity timeout

`archive_after_days` says, "if nothing new mentions this topic for N days,
consider it finished enough to archive."

This is useful for short projects, customer escalations, or experiments with a
natural end.

### 2) Explicit close phrases

`closed_phrases` lets you close a topic immediately when a capture contains
phrases like:

- `project closed`
- `shipped to prod`
- `migration complete`

Use these when your workflow has obvious end markers.

### 3) Manual action from the UI

Sometimes you know the topic is done before the text says so. From **Settings
→ Topics & PoIs**, you can archive or pause a PoI manually.

A practical pattern is:

- pause a PoI if the work is dormant but may resume,
- archive it if the story is genuinely complete.

## Reports

`reports.layout` controls how daily and weekly reports are structured. The
three modes are:

- `chronological`
- `per_poi`
- `auto`

`auto` is the default, and it is usually the right choice.

Behavior:

- if at least one tracked PoI touched the report period, the report is grouped
  by PoI;
- if no tracked PoIs were touched, the report falls back to the old
  chronological layout.

A simplified example:

```md
# Daily report — 2026-06-02

## Project Atlas
- Reviewed rollout checklist (`cap-41`)
- Fixed migration script (`cap-44`)

## Northwind
- Triage call notes (`cap-47`)
- Drafted follow-up email (`cap-49`)

## Everything else
- General admin and unrelated captures
```

That layout is easier to skim when your day spans several parallel
workstreams. It also makes export cleaner, because each section already reads
like a mini status update.

## TOML reference

Power users can edit `config.toml` directly. The `topic` skill is fully
declarative.

```toml
[skills]
enabled = ["topic", "support_ticket"]
poi_wizard_seen = true

[skills.topic]
llm_judge_max_chars = 1200

[[skills.topic.topics]]
name = "Project Atlas"
description = "Internal rewrite of the fulfillment pipeline"
keywords = ["atlas", "fulfillment rewrite"]
regex = []
aliases = ["atlas rollout"]
llm_judge = true
archive_after_days = 21
closed_phrases = ["project closed", "shipped to prod"]
```

A few field notes:

- `enabled` controls whether the `topic` skill runs at all.
- `poi_wizard_seen = true` means the one-time wizard has already been shown.
- `keywords`, `regex`, and `aliases` are optional lists.
- `llm_judge` is per topic, so you can keep the fuzzy tier only where it
  helps.
- `archive_after_days` and `closed_phrases` control when the bucket should
  close.

If you edit TOML by hand, keep one `[[skills.topic.topics]]` table per PoI.
That makes diffs easy to read and keeps merges manageable.

## CLI

```bash
python -m rin poi-discover --days 14            # dry-run, regex/domain/phrase only
python -m rin poi-discover --days 30 --use-llm  # also use LLM batch (1 LLM call)
python -m rin poi-discover --days 30 --persist  # save results to poi_candidates table
```

Practical notes:

- `--days` widens or narrows the search window.
- `--use-llm` is optional and cost-bearing.
- `--persist` stores suggestions for later review in Settings.
- You can combine `--use-llm` and `--persist` if you want both.

## FAQ

### Can I edit a PoI later?

Yes. Open **Settings → Topics & PoIs**, select the topic, and change its name,
description, keywords, aliases, regex, or archive behavior. PoIs are meant to
evolve with your work.

### Does PoI tracking work without an LLM?

Yes. Keywords, regex, aliases, report grouping, and local discovery all work
without any cloud LLM. The optional LLM pieces are:

- the per-topic `llm_judge`,
- `poi-discover --use-llm`,
- and the normal summary generation path if your chosen provider is remote.

If you want the cheapest setup, start with local matching only.

### What about privacy?

PoIs do not change RIN's basic privacy model. Your captures, config, reports,
and SQLite database remain local. Only the optional LLM judge or optional LLM
discovery batch send text to the provider you configured. If you keep those
features off, PoI matching stays local.

### Can I use `topic` and `support_ticket` together?

Yes. That is a common setup. Use `support_ticket` for rigid ticket IDs, and
`topic` for broader projects, customers, and initiatives. The same capture can
belong to both.

### How do I export or share PoI-organised work?

Use the normal report flow. Generate a daily or weekly report, then export it
as Markdown, PDF, or HTML from the Reports window. If you use an Obsidian
vault target, the grouped report is written there too.

## See also

- [docs/skills.md](skills.md) — the underlying skill framework (advanced).
- [DEVELOPING.md](../DEVELOPING.md) — developer documentation.
- [CHANGELOG.md](../CHANGELOG.md) — release notes.
