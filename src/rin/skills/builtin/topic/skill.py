"""Bundled ``topic`` skill.

The ``topic`` skill is a generic, declarative point-of-interest tracker.
Instead of writing a custom Python plugin, users list the topics they care
about in ``config.toml`` and define a few low-cost matching signals:
regexes, keywords, aliases, and (optionally) an LLM yes/no judge.

This fills the gap between RIN's flat default stream and highly structured
ID-based workflows such as ``support_ticket``. A user can track project
names, customer names, paper titles, people, vendors, initiatives, or any
other recurring thread that should accumulate into its own archive.

Detection is deliberately tiered:

1. Regexes first for precise, cheap matches.
2. Keywords and aliases second for broad substring matching.
3. A provider-backed LLM judge last when the cheap tiers miss.

The base ``Skill.detect()`` API does not receive an LLM provider today, so
runtime code can attach one directly with :meth:`TopicSkill.set_provider`.
That keeps the bundled skill framework unchanged while still giving tests and
future wiring a clean injection point.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ....llm.base import LLMError, Provider
from ....utils.logging import get_logger
from ...base import BucketRef, CaptureInfo, Skill, SkillContext, _default_archive

log = get_logger(__name__)

_MISSING_PROVIDER_WARNING = (
    "topic: llm_judge requested but no provider has been attached; "
    "skipping LLM judge"
)
_ARCHIVE_SYSTEM_PROMPT = "You write concise factual summaries of activity around a single topic."


class TopicSpec(BaseModel):
    """One tracked point of interest.

    ``name`` becomes both the bucket key and the bucket title. The other
    fields let users balance precision and convenience:

    * ``regex`` handles stable identifiers or naming schemes.
    * ``keywords`` and ``aliases`` cover informal mentions.
    * ``llm_judge`` is an opt-in fallback for fuzzy cases.
    * ``closed_phrases`` and ``archive_after_days`` control auto-archival.
    """

    name: str
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    regex: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    llm_judge: bool = False
    archive_after_days: int = 30
    closed_phrases: list[str] = Field(default_factory=list)


class TopicConfig(BaseModel):
    """User-facing settings for the bundled ``topic`` skill.

    Example TOML::

        [skills.topic]
        llm_judge_max_chars = 1200

        [[skills.topic.topics]]
        name = "Project Atlas"
        description = "Internal rewrite of the fulfillment pipeline"
        keywords = ["atlas", "fulfillment rewrite"]
        aliases = ["atlas rollout"]
        llm_judge = true
        archive_after_days = 21
        closed_phrases = ["project closed", "shipped to prod"]
    """

    topics: list[TopicSpec] = Field(default_factory=list)
    llm_judge_max_chars: int = 1200
    llm_judge_system_prompt: str = "You are a classifier. Reply only with YES or NO."


class TopicSkill(Skill):
    """Track arbitrary topics without requiring a custom skill.

    The skill is intentionally conservative: each topic is evaluated in
    isolation and wrapped in a broad ``try`` block so one bad user-supplied
    regex or provider failure cannot break the rest of the pipeline.
    """

    name = "topic"
    display_name = "Topics"
    version = "0.1.0"
    description = (
        "Track arbitrary topics (projects, people, customers, papers) via "
        "keywords/regex/aliases or optional LLM judge."
    )
    Config = TopicConfig

    def __init__(self, config: TopicConfig | None = None) -> None:
        super().__init__(config)
        self._provider: Provider | None = None
        self._compiled_regexes: dict[
            tuple[str, tuple[str, ...]], tuple[re.Pattern[str], ...]
        ] = {}
        self._warned_missing_provider = False

    def set_provider(self, provider: Provider | None) -> None:
        """Attach a provider for ``llm_judge`` calls.

        ``detect()`` only receives :class:`SkillContext`, so the provider is
        injected onto the skill instance instead of threading it through the
        current skill base API.
        """

        self._provider = provider
        self._warned_missing_provider = False

    def detect(self, ctx: SkillContext) -> list[BucketRef]:
        """Return one bucket per matching topic spec.

        The combined text is built once and shared across all tiers:

        * regex over the original text
        * substring scans over a lower-cased copy
        * optional LLM yes/no classification
        """

        cfg = self._config(ctx)
        if not cfg.topics:
            return []

        text, lowered = self._combined_text(
            ctx.summary,
            ctx.ocr_text,
            ctx.transcript_text,
        )
        seen: dict[str, BucketRef] = {}

        for spec in cfg.topics:
            try:
                if self._matches_regex(spec, text):
                    seen.setdefault(spec.name, self._bucket_ref(spec))
                    continue
                if self._matches_terms(spec, lowered):
                    seen.setdefault(spec.name, self._bucket_ref(spec))
                    continue
                if spec.llm_judge and self._matches_llm(spec, text, cfg):
                    seen.setdefault(spec.name, self._bucket_ref(spec))
            except Exception as exc:  # noqa: BLE001 - per-spec isolation is required
                log.warning(f"topic: skipping spec {spec.name!r}: {exc}")
        return list(seen.values())

    def should_close(
        self,
        bucket: Any,
        captures: list[CaptureInfo],
        now: datetime,
    ) -> bool:
        """Archive a topic when it is explicitly closed or goes stale."""

        cfg = self._config()
        spec = self._spec_for_bucket(bucket, cfg)
        if spec is None or not captures:
            return False
        if self._has_closed_phrase(captures, spec.closed_phrases):
            return True
        last_capture = max(c.started_at for c in captures)
        return (now - last_capture).days >= spec.archive_after_days

    def render_archive(
        self,
        bucket: Any,
        captures: list[CaptureInfo],
        provider: Provider | None = None,
    ) -> str:
        """Render a Markdown archive for one topic bucket.

        Without a provider, or when the bucket is empty, the safe default is
        a plain chronological dump. With a provider, the skill asks for a
        concise topic-centric rollup that highlights status, actions, and
        unresolved questions.
        """

        if provider is None or not captures:
            return _default_archive(bucket, captures)

        ordered = sorted(captures, key=lambda c: c.started_at)
        try:
            return self._llm_archive(bucket, ordered, provider)
        except LLMError as exc:
            bucket_key = getattr(bucket, "key", None) or getattr(bucket, "title", "topic")
            log.warning(
                f"topic: LLM archive for {bucket_key!r} failed; using fallback ({exc})"
            )
            return _default_archive(bucket, captures)

    def _config(self, ctx: SkillContext | None = None) -> TopicConfig:
        """Return the validated config bound to the skill."""

        if isinstance(self.config, TopicConfig):
            return self.config
        if ctx is not None and isinstance(ctx.config, TopicConfig):
            return ctx.config
        return TopicConfig()

    @staticmethod
    def _bucket_ref(spec: TopicSpec) -> BucketRef:
        """Build the bucket emitted for a matched topic spec."""

        return BucketRef(key=spec.name, title=spec.name)

    @staticmethod
    def _combined_text(*parts: str) -> tuple[str, str]:
        """Join capture text once and return original + lower-cased forms."""

        text = "\n".join(part for part in parts if part)
        return text, text.lower()

    def _compiled_patterns(self, spec: TopicSpec) -> tuple[re.Pattern[str], ...]:
        """Compile a topic's regex list, logging and skipping bad patterns."""

        cache_key = (spec.name, tuple(spec.regex))
        cached = self._compiled_regexes.get(cache_key)
        if cached is not None:
            return cached

        compiled: list[re.Pattern[str]] = []
        for pattern in spec.regex:
            if not pattern:
                continue
            try:
                compiled.append(re.compile(pattern, re.IGNORECASE))
            except re.error as exc:
                log.warning(
                    f"topic: skipping bad regex for {spec.name!r}: {pattern!r}: {exc}"
                )
        out = tuple(compiled)
        self._compiled_regexes[cache_key] = out
        return out

    def _matches_regex(self, spec: TopicSpec, text: str) -> bool:
        """Return ``True`` when any configured regex matches the capture."""

        if not text or not spec.regex:
            return False
        return any(pattern.search(text) for pattern in self._compiled_patterns(spec))

    @staticmethod
    def _matches_terms(spec: TopicSpec, lowered_text: str) -> bool:
        """Return ``True`` when any keyword or alias appears as a substring."""

        if not lowered_text:
            return False
        for term in (*spec.keywords, *spec.aliases):
            needle = term.strip().lower()
            if needle and needle in lowered_text:
                return True
        return False

    def _matches_llm(self, spec: TopicSpec, text: str, cfg: TopicConfig) -> bool:
        """Ask the attached provider for a YES/NO classification."""

        provider = self._provider
        if provider is None:
            if not self._warned_missing_provider:
                log.warning(_MISSING_PROVIDER_WARNING)
                self._warned_missing_provider = True
            return False

        snippet = text[: cfg.llm_judge_max_chars]
        prompt = (
            f"Is the following capture about '{spec.name}'? "
            f"Description: {spec.description}\n\n"
            f"Content:\n{snippet}\n\n"
            "Reply with YES or NO only."
        )
        try:
            reply = provider.analyze_text(
                prompt,
                system=cfg.llm_judge_system_prompt,
            )
        except LLMError as exc:
            log.warning(f"topic: llm_judge failed for {spec.name!r}: {exc}")
            return False
        return reply.strip().upper().startswith("Y")

    def _spec_for_bucket(self, bucket: Any, cfg: TopicConfig) -> TopicSpec | None:
        """Resolve the config entry backing ``bucket``."""

        title = getattr(bucket, "title", None)
        key = getattr(bucket, "key", None)
        for spec in cfg.topics:
            if spec.name == title or spec.name == key:
                return spec
        return None

    def _has_closed_phrase(
        self,
        captures: list[CaptureInfo],
        phrases: list[str],
    ) -> bool:
        """Return ``True`` when any capture contains any close marker."""

        lowered_phrases = [phrase.strip().lower() for phrase in phrases if phrase.strip()]
        if not lowered_phrases:
            return False

        for cap in captures:
            _, lowered = self._combined_text(
                cap.summary,
                cap.ocr_text,
                cap.transcript_text,
            )
            for phrase in lowered_phrases:
                if phrase in lowered:
                    return True
        return False

    @staticmethod
    def _llm_archive(
        bucket: Any,
        captures: list[CaptureInfo],
        provider: Provider,
    ) -> str:
        """Generate the structured archive text with the configured provider."""

        title = getattr(bucket, "title", None) or getattr(bucket, "key", "Topic")
        timeline: list[str] = []
        for cap in captures:
            ts = cap.started_at.isoformat()
            summary = (cap.summary or "")[:600]
            timeline.append(f"- cap-{cap.capture_id} @ {ts} — {summary}")

        prompt = "\n".join(
            [
                "Write a structured Markdown archive for activity around a single tracked topic.",
                "Use this exact section order:",
                f"# {title}",
                "## Status",
                "## Timeline",
                "## Key actions",
                "## Decisions",
                "## Open questions",
                "## Linked resources",
                "",
                "Be concise and factual.",
                "Cite capture ids like `cap-12` in the relevant bullets.",
                "In `## Timeline`, use bullet lines in the form `- cap-N @ ISO-timestamp — short summary`.",
                "",
                "Captures in chronological order:",
                *timeline,
            ]
        )
        text = provider.analyze_text(prompt, system=_ARCHIVE_SYSTEM_PROMPT).strip()
        if not text.startswith("# "):
            text = f"# {title}\n\n{text}"
        return text + "\n"


SKILL = TopicSkill()
