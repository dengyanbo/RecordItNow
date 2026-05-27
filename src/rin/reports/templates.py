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
