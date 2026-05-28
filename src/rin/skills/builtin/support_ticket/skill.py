"""Implementation of the bundled ``support_ticket`` skill."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ....llm.base import LLMError, Provider
from ....utils.logging import get_logger
from ...base import BucketRef, CaptureInfo, Skill, SkillContext, _default_archive

log = get_logger(__name__)


# Default regexes — opinionated but conservative. Common ticket-ID
# formats from the systems we routinely see (ServiceNow, Salesforce,
# GitHub-style). Easily overridden via the skill's TOML config.
_DEFAULT_PATTERNS = (
    r"\bINC\d{7}\b",
    r"\bREQ\d{7}\b",
    r"\bSR\d{7,10}\b",
    r"\bCASE\d{6,8}\b",
    r"#\d{4,6}\b",
)

_DEFAULT_CLOSED_PHRASES = (
    "ticket closed",
    "case closed",
    "marked as resolved",
    "status: closed",
    "status: resolved",
    "resolved by",
)


class SupportTicketConfig(BaseModel):
    """User-tunable settings for the ``support_ticket`` skill.

    Override in ``config.toml`` under ``[skills.support_ticket]``::

        [skills.support_ticket]
        id_patterns = ["INC\\d{7}", "JIRA-\\d+"]
        closed_phrases = ["ticket closed", "done"]
        auto_archive_after_days = 7
        use_llm_for_archive = true
    """

    id_patterns: list[str] = Field(default_factory=lambda: list(_DEFAULT_PATTERNS))
    closed_phrases: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_CLOSED_PHRASES)
    )
    auto_archive_after_days: int = 14
    use_llm_for_archive: bool = True
    use_llm_for_closure: bool = False
    # When True, only the first match is returned per capture. Default
    # (False) returns every distinct ticket ID found.
    only_first_match: bool = False


class SupportTicketSkill(Skill):
    name = "support_ticket"
    display_name = "Support tickets"
    version = "0.1.0"
    description = (
        "Group captures by ticket ID (ServiceNow / Salesforce / "
        "GitHub-style). Archive when the ticket closes."
    )
    Config = SupportTicketConfig

    def __init__(self, config: SupportTicketConfig | None = None) -> None:
        super().__init__(config)
        self._compiled: list[re.Pattern[str]] = []

    # ------------------------------------------------------------------
    # detect
    # ------------------------------------------------------------------

    def detect(self, ctx: SkillContext) -> list[BucketRef]:
        cfg = self._config()
        patterns = self._compile(cfg.id_patterns)
        text = "\n".join(filter(None, (ctx.summary, ctx.ocr_text, ctx.transcript_text)))
        if not text or not patterns:
            return []

        seen: dict[str, BucketRef] = {}
        for pat in patterns:
            for match in pat.finditer(text):
                key = match.group(0).strip()
                if not key:
                    continue
                norm = key.upper()
                if norm in seen:
                    continue
                title = self._extract_title(text, match.end(), norm)
                seen[norm] = BucketRef(key=norm, title=title, extra={})
                if cfg.only_first_match:
                    return list(seen.values())
        return list(seen.values())

    # ------------------------------------------------------------------
    # should_close
    # ------------------------------------------------------------------

    def should_close(
        self,
        bucket: Any,
        captures: list[CaptureInfo],
        now: datetime,
    ) -> bool:
        cfg = self._config()
        if not captures:
            return False
        if self._any_closed_phrase(captures, cfg.closed_phrases):
            return True
        # Inactivity timeout.
        last = max(c.started_at for c in captures)
        return (now - last).days >= cfg.auto_archive_after_days

    # ------------------------------------------------------------------
    # render_archive
    # ------------------------------------------------------------------

    def render_archive(
        self,
        bucket: Any,
        captures: list[CaptureInfo],
        provider: Provider | None = None,
    ) -> str:
        cfg = self._config()
        if cfg.use_llm_for_archive and provider is not None and captures:
            try:
                return self._llm_archive(bucket, captures, provider)
            except LLMError as exc:
                log.warning(
                    f"support_ticket: LLM archive for {bucket.key} failed; "
                    f"using fallback ({exc})"
                )
        return _default_archive(bucket, captures)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _config(self) -> SupportTicketConfig:
        if isinstance(self.config, SupportTicketConfig):
            return self.config
        return SupportTicketConfig()

    def _compile(self, patterns: list[str]) -> list[re.Pattern[str]]:
        if self._compiled and len(self._compiled) == len(patterns):
            return self._compiled
        compiled: list[re.Pattern[str]] = []
        for p in patterns:
            try:
                compiled.append(re.compile(p, re.IGNORECASE))
            except re.error as exc:
                log.warning(f"support_ticket: skipping bad regex {p!r}: {exc}")
        self._compiled = compiled
        return compiled

    @staticmethod
    def _extract_title(text: str, end_offset: int, key: str) -> str:
        """Use the 60 chars after the match as a context hint."""

        tail = text[end_offset : end_offset + 60].strip().splitlines()
        first_line = tail[0] if tail else ""
        cleaned = re.sub(r"\s+", " ", first_line).strip(" -:|·")
        if cleaned:
            return f"{key} — {cleaned[:48]}"
        return key

    @staticmethod
    def _any_closed_phrase(captures: list[CaptureInfo], phrases: list[str]) -> bool:
        lowered = [p.lower() for p in phrases if p]
        for cap in captures:
            blob = " ".join(
                (cap.summary or "", cap.ocr_text or "", cap.transcript_text or "")
            ).lower()
            for phrase in lowered:
                if phrase in blob:
                    return True
        return False

    @staticmethod
    def _llm_archive(
        bucket: Any,
        captures: list[CaptureInfo],
        provider: Provider,
    ) -> str:
        timeline = []
        for cap in sorted(captures, key=lambda c: c.started_at):
            ts = cap.started_at.isoformat()
            snippet = (cap.summary or "")[:600]
            timeline.append(f"- cap-{cap.capture_id} @ {ts}: {snippet}")
        joined = "\n".join(timeline)
        prompt = (
            "You are summarizing a support engineer's interactions with a "
            f"single ticket ({bucket.key}). Produce a Markdown archive "
            "with the following sections in this exact order: "
            "`# {title}` (the ticket title), `## Customer problem`, "
            "`## Investigation timeline`, `## Root cause`, `## Resolution`, "
            "`## Lessons learned`. Be concise and factual; use bullet points "
            "with capture IDs as citations (e.g. `cap-12`).\n\n"
            "Captures in chronological order:\n"
            + joined
        )
        text = provider.analyze_text(
            prompt,
            system=(
                "You write tight, accurate post-mortem notes for a tech "
                "support engineer reviewing a closed ticket."
            ),
        )
        # Ensure the result starts with a top-level heading regardless of
        # what the LLM produced.
        text = text.strip()
        if not text.startswith("# "):
            title = getattr(bucket, "title", None) or bucket.key
            text = f"# {title}\n\n" + text
        return text + "\n"


SKILL = SupportTicketSkill()
