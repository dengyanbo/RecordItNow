"""Structured per-POI rollup payload for the ``analyses.analysis_json`` column.

Phase 1-B (v0.11.0) introduced this so a single capture that touched
multiple tracked topics can carry one short block per topic on top of
the existing free-text general summary. Downstream consumers (reports,
RAG, future tools) can render the per-POI block directly instead of
extracting topics out of a paragraph.

Schema (versioned, additive-safe)::

    {
      "schema_version": 1,
      "general_summary": "Free-text 2-4 sentence summary.",
      "poi_blocks": [
        {"poi": "Project Atlas", "block": "1-2 sentences about Atlas."},
        ...
      ]
    }

All fields are optional in parsed payloads — ``parse`` returns a
:class:`StructuredAnalysis` with safe defaults if the LLM produced
malformed JSON, and the caller falls back to ``Analysis.summary``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..utils.logging import get_logger

log = get_logger(__name__)

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PoIBlock:
    poi: str
    block: str


@dataclass(frozen=True)
class StructuredAnalysis:
    general_summary: str = ""
    poi_blocks: tuple[PoIBlock, ...] = field(default_factory=tuple)
    schema_version: int = SCHEMA_VERSION

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "general_summary": self.general_summary,
                "poi_blocks": [
                    {"poi": b.poi, "block": b.block} for b in self.poi_blocks
                ],
            },
            ensure_ascii=False,
        )

    def block_for(self, poi: str) -> str | None:
        """Return the block text for ``poi`` (case-insensitive match) or ``None``."""

        if not poi:
            return None
        needle = poi.strip().lower()
        for b in self.poi_blocks:
            if b.poi.strip().lower() == needle:
                return b.block
        return None


def empty() -> StructuredAnalysis:
    return StructuredAnalysis()


def parse(text: str | None) -> StructuredAnalysis:
    """Parse ``text`` as a structured payload; return :func:`empty` on failure."""

    if not text:
        return empty()
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return empty()
    if not isinstance(data, dict):
        return empty()
    general = data.get("general_summary")
    blocks_raw = data.get("poi_blocks")
    blocks: list[PoIBlock] = []
    if isinstance(blocks_raw, list):
        for entry in blocks_raw:
            if not isinstance(entry, dict):
                continue
            poi = entry.get("poi")
            block_text = entry.get("block")
            if isinstance(poi, str) and isinstance(block_text, str):
                poi_clean = poi.strip()
                block_clean = block_text.strip()
                if poi_clean and block_clean:
                    blocks.append(PoIBlock(poi=poi_clean, block=block_clean))
    version_raw = data.get("schema_version")
    version = version_raw if isinstance(version_raw, int) else SCHEMA_VERSION
    return StructuredAnalysis(
        general_summary=general.strip() if isinstance(general, str) else "",
        poi_blocks=tuple(blocks),
        schema_version=version,
    )


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def parse_llm_response(reply: str) -> StructuredAnalysis:
    """Tolerant parse of an LLM response that *might* be a JSON object.

    Some providers wrap JSON in ```json fences``` or add a preamble like
    "Here is the JSON:". This helper extracts the first object-shaped
    blob and falls back to :func:`empty` on any failure.
    """

    if not reply:
        return empty()
    candidate = reply.strip()
    # Try the whole thing first.
    parsed = parse(candidate)
    if parsed.general_summary or parsed.poi_blocks:
        return parsed
    # Try to peel off a ```json``` fence.
    match = _JSON_FENCE.search(candidate)
    if match is not None:
        parsed = parse(match.group(1))
        if parsed.general_summary or parsed.poi_blocks:
            return parsed
    # Last resort: locate the first { ... last }.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end > start:
        parsed = parse(candidate[start : end + 1])
        if parsed.general_summary or parsed.poi_blocks:
            return parsed
    return empty()


def build_prompt(
    *,
    detected_pois: list[str],
    max_blocks: int,
    material: str,
) -> str:
    """Compose the JSON-formatted ask sent to the LLM.

    The prompt:
      * Asks for a single JSON object matching :class:`StructuredAnalysis`.
      * Lists the detected POIs (caller has already capped / filtered them).
      * Caps requested ``poi_blocks`` at ``max_blocks`` to bound cost.
    """

    pois = [p.strip() for p in detected_pois if p and p.strip()]
    capped = pois[:max_blocks]
    poi_lines = "\n".join(f"  - {p}" for p in capped) or "  (none detected)"
    lines = [
        "You are summarizing a user's screen activity for a personal journal.",
        "Return ONLY a single JSON object with this exact shape (no prose, no markdown fences):",
        "{",
        '  "schema_version": 1,',
        '  "general_summary": "2-4 sentence paragraph capturing the activity overall",',
        '  "poi_blocks": [',
        '    {"poi": "<name>", "block": "1-2 sentences about that topic in this capture"}',
        "  ]",
        "}",
        "",
        f"Cover at most {max_blocks} of the following detected topics (skip any with no real signal):",
        poi_lines,
        "",
        "Do not include filler phrases. If a topic isn't actually visible, leave it out of poi_blocks.",
        "",
        "Source material:",
        material,
    ]
    return "\n".join(lines)


__all__ = [
    "PoIBlock",
    "SCHEMA_VERSION",
    "StructuredAnalysis",
    "build_prompt",
    "empty",
    "parse",
    "parse_llm_response",
]
