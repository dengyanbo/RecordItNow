"""Report templates (offline fallback rendered with Jinja2)."""
from __future__ import annotations

FALLBACK_REPORT_TEMPLATE = """# RIN Report — {{ kind|title }}

**Period:** {{ period_start.strftime('%Y-%m-%d %H:%M') }} → {{ period_end.strftime('%Y-%m-%d %H:%M') }}

**Captures in range:** {{ items|length }}

{% if items %}
## Captures

{% for item in items %}
### {{ loop.index }}. {{ item.kind|title }} — {{ item.started_at.strftime('%Y-%m-%d %H:%M') }}

- **id:** cap-{{ item.id }}
- **duration:** {{ item.duration_ms or 0 }} ms
- **monitors:** {{ item.monitor_count }}
{% if item.summary %}

{{ item.summary }}
{% endif %}

{% endfor %}
{% else %}
_No captures in this period._
{% endif %}

---

_Generated offline (no LLM provider available)._
"""


LLM_PROMPT_TEMPLATE = """You are writing a {kind} activity report for the user.
Cover the period {period_start} → {period_end}.

Produce a single markdown document with these sections in order:
1. **Highlights** — 3-5 bullet points capturing the most important moments.
2. **Apps & topics** — short list of apps/topics observed.
3. **Open questions** — anything the user might want to follow up on.
4. **Action items** — concrete to-dos surfaced by the captures.

Reference captures by id like (cap-12) when relevant. Keep the report under
500 words. Source material follows.

{material}
"""


POI_GROUPED_REPORT_TEMPLATE = """# RIN Report — {{ kind|title }}

**Period:** {{ period_start.strftime('%Y-%m-%d %H:%M') }} → {{ period_end.strftime('%Y-%m-%d %H:%M') }}

**Captures in range:** {{ items|length }}
**Topics active in period:** {{ poi_sections|length }}

{% if poi_sections %}
{% for section in poi_sections %}
## {{ section.title }}

{% if section.status_change %}
**Status:** {{ section.status_change }}
{% endif %}
**Captures in period:** {{ section.captures|length }}
{% if section.archive_path %}
**Archive:** [{{ section.archive_path }}]({{ section.archive_path }})
{% endif %}

{% for cap in section.captures %}
- `cap-{{ cap.id }}` @ {{ cap.started_at.strftime('%Y-%m-%d %H:%M') }}{% if cap.summary %} — {{ cap.summary }}{% endif %}
{% endfor %}

{% endfor %}
{% endif %}

{% if uncategorized %}
## Uncategorized

{% for cap in uncategorized %}
- `cap-{{ cap.id }}` @ {{ cap.started_at.strftime('%Y-%m-%d %H:%M') }}{% if cap.summary %} — {{ cap.summary }}{% endif %}
{% endfor %}
{% else %}
_All captures were categorized into a topic._
{% endif %}

---

_Generated offline (no LLM provider available)._
"""


POI_GROUPED_LLM_PROMPT = """You are writing a {kind} activity report grouped by the user's tracked topics.
Period: {period_start} → {period_end}.
Total captures: {total_captures}.
Topics with activity: {topic_count}.

Produce ONE markdown document with these sections in this exact order:

1. `# RIN Report — {kind_title}` (top heading)
2. `## Summary` — 2-3 sentence overall rollup.
3. One `## {{topic name}}` section per topic in the order given below. Each topic section must contain:
   - `**Status:**` line if there is any status change in the period (opened, archived, reopened); otherwise omit.
   - `### Highlights` — 2-4 concise bullets, citing capture IDs like `cap-12`.
   - `### Activity timeline` — chronological bullet list of the topic's captures with timestamps.
   - `### Open questions` — anything left unresolved; omit the heading if there are none.
   - `### Archive` — if `archive_path` is given, link to it.
4. `## Uncategorized` (only if there are uncategorized captures) — bullet list of those captures with capture IDs.

Keep the whole document under 800 words. Be factual and concise. Source material follows.

{material}
"""
