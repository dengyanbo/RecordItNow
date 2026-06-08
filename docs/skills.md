# Skills — pluggable categorization (v0.5+)

A **skill** is a small Python plugin that decides how RIN should
**categorize** your captures. The default RIN flow produces a flat
stream — every capture gets summarized and dropped into a daily report.
Skills let you slice the same stream into *buckets* with a meaning
that matters to you:

- A tech-support engineer wants captures grouped by **ticket ID**.
- A researcher wants them grouped by **paper / experiment**.
- A manager wants them grouped by **1:1 partner**.

Each skill:

1. Scans the OCR + summary of every capture (running automatically
   after analysis).
2. Returns zero or more `(key, title)` buckets the capture should
   belong to.
3. Periodically checks each active bucket — if the bucket has
   "finished" (e.g. ticket resolved), the skill renders a Markdown
   archive summarising the whole journey.

Most users should start with the generic
**[`topic`](#the-topic-skill-recommended-for-most-users)** skill or
follow the [PoI guide](poi.md). RIN also ships with
**`support_ticket`** (the tech-support example). Drop your own under
`%LOCALAPPDATA%\RIN\skills\<name>\` to extend the system.

---

## Quick start with `support_ticket`

1. **Enable it** — open Settings → **Skills** → toggle *Support tickets*
   to Enabled → **Save**.
2. **Work as usual.** Every time RIN analyzes a capture, the skill
   scans the OCR + summary for ticket IDs. Defaults cover **16-digit
   numeric case IDs** (e.g. `2606050030000773`), **19-digit collab
   task IDs** (e.g. `2606010050000901001`), and the legacy
   `INC0012345` / `CASE0007890` / `SR1234567890` / `#1234` style
   prefixes. Matches are linked to a *bucket* keyed by the ticket ID;
   the bucket title also picks up a `Case ` / `Task ` prefix when one
   of the numeric defaults matches.
3. **Close a ticket.** When any capture in the bucket mentions a
   "closed" phrase (`Status: Closed`, `marked as resolved`, …) the
   `BucketScheduler` archives the bucket on its next tick (default: 6h).
4. **Read the archive.** Open Reports → **Archives** → click the
   ticket. RIN renders a Markdown post-mortem with sections:
   *Customer problem*, *Investigation timeline*, *Root cause*,
   *Resolution*, *Lessons learned*. Each bullet cites a specific
   `cap-N`.

Override the defaults in `%LOCALAPPDATA%\RIN\config.toml`:

```toml
[skills]
enabled = ["support_ticket"]
closure_check_hours = 6

[skills.support_ticket]
# Restrict / extend the recognised ticket-ID shapes.
# Defaults cover Microsoft-style 16-digit case IDs + 19-digit collab
# task IDs (16-digit case prefix + 3-digit task suffix), plus the
# common legacy alphabetic prefixes.
id_patterns = [
    "\\d{19}",       # collab task ID (default → "Task" prefix)
    "\\d{16}",       # case ID (default → "Case" prefix)
    "INC\\d{7}",
    "REQ\\d{7}",
    "SR\\d{7,10}",
    "CASE\\d{6,8}",
    "JIRA-\\d+",     # custom: JIRA card numbers
]
# Optional friendly word prefixed to each bucket's title, aligned by
# index with id_patterns. Use "" for no prefix. When the two lists
# differ in length all labels are silently dropped to avoid
# mis-labelling, so re-list both together if you override either.
id_labels = ["Task", "Case", "", "", "", "", ""]
# Phrases that mark a ticket as done.
closed_phrases = [
    "ticket closed",
    "case closed",
    "marked as resolved",
    "status: closed",
    "status: resolved",
]
# Archive automatically after N days of no new captures.
auto_archive_after_days = 14
# Use the configured LLM to write a structured post-mortem
# (root cause, resolution, lessons learned) when archiving.
# Falls back to a plain chronological dump if no provider.
use_llm_for_archive = true
# When true, detect() returns only the first matched ticket id per
# capture. Default keeps every match.
only_first_match = false
```

---

## The `topic` skill (recommended for most users)

If your work is organized around **topics** instead of rigid ticket IDs,
start here. `topic` is the bundled "point of interest" tracker: you tell
RIN which projects, customers, papers, people, or initiatives matter to
you, and it groups matching captures into topic buckets automatically.

Use `topic` when:

- your work has recognizable names but not stable IDs,
- you want a no-code setup in `config.toml`,
- regex alone is not enough and an optional YES/NO LLM judge helps.

Example config:

```toml
[skills]
enabled = ["topic", "support_ticket"]

[skills.topic]
llm_judge_max_chars = 1200
llm_judge_system_prompt = "You are a classifier. Reply only with YES or NO."

[[skills.topic.topics]]
name = "Platform migration"
description = "JIRA-tracked migration work for the platform team"
regex = ["JIRA-\\d+"]
archive_after_days = 14
closed_phrases = ["migration complete", "project closed"]

[[skills.topic.topics]]
name = "Project Atlas"
description = "Internal codename for the Atlas customer rollout"
keywords = ["atlas", "customer rollout"]
aliases = ["atlas launch", "atlas workstream"]
llm_judge = true
archive_after_days = 21
closed_phrases = ["project closed", "shipped to prod"]
```

How it behaves:

1. **Regex first.** If a topic has `regex`, RIN checks those patterns
   first against the capture summary, OCR text, and transcript.
2. **Then keywords / aliases.** Simple case-insensitive substring
   matching covers everyday references like `atlas` or `pkg`.
3. **Then optional LLM judge.** If `llm_judge = true` and a provider is
   available, RIN asks a narrow YES/NO question about that topic.
4. **Archive when done or stale.** A topic closes immediately when a
   configured `closed_phrases` substring appears, or after
   `archive_after_days` with no new captures.

This is the recommended bundled skill for most users because it stays
fully declarative: no Python file, no custom packaging, just TOML.

---

## Writing your own skill

A skill is a single Python file that exports a module-level `SKILL`
object. Drop it into the right folder and RIN picks it up on the next
discovery pass (Settings dialog open, or `BucketScheduler` start).

### Layout

```
%LOCALAPPDATA%\RIN\skills\
└─ my_research/
   ├─ skill.py        # required
   └─ <whatever else you need>
```

Click **Settings → Skills → "Open skills folder…"** to jump there.

### Minimal example

```python
# %LOCALAPPDATA%\RIN\skills\my_research\skill.py
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from rin.skills.base import (
    BucketRef, CaptureInfo, Skill, SkillContext, _default_archive,
)


class ResearchConfig(BaseModel):
    paper_patterns: list[str] = Field(
        default_factory=lambda: [r"arXiv:\d{4}\.\d{4,5}", r"doi:10\.\d+/\S+"]
    )


class ResearchSkill(Skill):
    name = "research_paper"
    display_name = "Research papers"
    version = "0.1.0"
    description = "Group captures by arXiv ID / DOI."
    Config = ResearchConfig

    def detect(self, ctx: SkillContext) -> list[BucketRef]:
        cfg = self.config or ResearchConfig()
        text = " ".join((ctx.summary, ctx.ocr_text, ctx.transcript_text))
        seen: dict[str, BucketRef] = {}
        for pattern in cfg.paper_patterns:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                key = m.group(0)
                if key not in seen:
                    seen[key] = BucketRef(key=key, title=key)
        return list(seen.values())

    def should_close(
        self, bucket: Any, captures: list[CaptureInfo], now: datetime,
    ) -> bool:
        # Auto-archive papers no one has touched in 30 days.
        if not captures:
            return False
        last = max(c.started_at for c in captures)
        return (now - last).days >= 30

    # render_archive defaults to a chronological list — keep that.


SKILL = ResearchSkill()
```

Enable it in `config.toml`:

```toml
[skills]
enabled = ["research_paper", "support_ticket"]

[skills.research_paper]
paper_patterns = ["arXiv:\\d{4}\\.\\d{4,5}", "PMID:\\d+"]
```

Reopen Settings to see the new skill in the list.

### The `Skill` interface

| Member | Required | Purpose |
|---|---|---|
| `name: str` | ✅ | Stable identifier matched against `[skills.enabled]`. |
| `display_name: str` | ✅ | Shown in Settings UI. |
| `version: str` | ✅ | Shown next to the name as a chip. Bumpable per release. |
| `description: str` | ✅ | One-liner shown in the Settings card. |
| `Config: type[pydantic.BaseModel]` | optional | Pydantic schema for the `[skills.<name>]` TOML section. `None` means "no config". |
| `detect(ctx) -> list[BucketRef]` | ✅ | Look at one capture and return the buckets it belongs to. Empty list is fine. |
| `should_close(bucket, captures, now) -> bool` | optional | Default: never. Return `True` to trigger archive on the next scheduler tick. |
| `render_archive(bucket, captures, provider) -> str` | optional | Default: chronological dump. Override to write a richer narrative; the active LLM `provider` is passed in for you. |

### Data flow inside `detect`

```text
                          ┌──────────────────────────────┐
   capture is analyzed →  │   classify_capture(...)      │
                          │   - load Capture row         │
                          │   - build SkillContext       │
                          └──────────────┬───────────────┘
                                         ▼
                          ┌──────────────────────────────┐
                          │ for each enabled skill:       │
                          │     skill.detect(ctx)         │
                          │     for each BucketRef:        │
                          │         UPSERT bucket row     │
                          │         INSERT capture_buckets│
                          └───────────────────────────────┘
```

### Data flow inside the scheduler

```text
                ┌─────────────────────────────────────────┐
   every 6 h    │  BucketScheduler.tick()                  │
                │  for each Bucket WHERE status='active':  │
                │      skill = registry.get(skill_name)    │
                │      captures = load_capture_infos(b.id) │
                │      if skill.should_close(b, captures): │
                │          body = skill.render_archive(...) │
                │          write reports/archives/<s>/<k>.md│
                │          status='archived'  closed_at=now │
                └─────────────────────────────────────────┘
```

### Errors

A skill crashing in `detect`, `should_close`, or `render_archive` is
**logged and skipped** — the failure cannot break the analysis pipeline
or stall other skills. Check `%LOCALAPPDATA%\RIN\logs\rin.log` after a
failure.

---

## ⚠️ Security note

User-installed skills run **in the RIN process** with **full access to
every capture's OCR text, transcript, and summary**. They can also
import any installed Python package and make network calls. Treat the
`%LOCALAPPDATA%\RIN\skills\` folder the same way you would treat your
Python `site-packages` — only install code from sources you trust.

Bundled skills under `rin.skills.builtin.*` are reviewed as part of the
RIN repository. Third-party skills are not.

---

## Bundled skills

| Name | Source | What it does |
|---|---|---|
| `support_ticket` | `rin.skills.builtin.support_ticket` | Ticket IDs — defaults cover 16-digit numeric case IDs, 19-digit collab task IDs, plus legacy ServiceNow / Salesforce / GitHub-style prefixes. Bucket titles get a `Case` / `Task` prefix when the default patterns match. Archives on `Status: Closed` or N-day inactivity. |
| `topic` | `rin.skills.builtin.topic` | Generic topic tracker (keywords / regex / aliases / optional LLM judge). The right tool when your work isn't ID-anchored. |

More bundled skills will follow over time — open a PR if you build one
worth bundling.

---

## Data layout

```
%LOCALAPPDATA%\RIN\
├─ skills\
│   └─ <user_skill_name>\
│       └─ skill.py
└─ reports\
    └─ archives\
        └─ support_ticket\
            ├─ INC0012345.md
            └─ INC0019876.md
```

The corresponding SQLite tables:

- `buckets` — `(id, skill_name, key, title, extra_json, status, opened_at, closed_at, archive_path)` with `UNIQUE(skill_name, key)`.
- `capture_buckets` — `(capture_id, bucket_id, created_at)`, many-to-many.

The same capture can sit in N buckets across M skills (e.g. an Outlook
screenshot showing both `INC0012345` and a JIRA card matches two skills
independently).
