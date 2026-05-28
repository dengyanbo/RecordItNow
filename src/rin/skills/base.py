"""Core types every skill builds on.

Skill authors subclass :class:`Skill` and implement :meth:`Skill.detect`
to map a capture's text content into one or more :class:`BucketRef`
values. The registry validates the skill's TOML config against the
optional ``Config`` Pydantic model; instances are then handed a frozen
:class:`SkillContext` per capture and :class:`CaptureInfo` lists for
closure / archive decisions.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class BucketRef:
    """A categorization result returned by :meth:`Skill.detect`.

    The pair ``(skill_name, key)`` is unique inside RIN's database —
    re-detecting the same ``key`` for the same skill upserts the
    existing bucket rather than creating a duplicate.
    """

    key: str
    title: str
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillContext:
    """Read-only context passed to :meth:`Skill.detect`.

    The skill should treat every field as immutable and short-lived;
    do not retain a reference past the call.
    """

    capture_id: int
    capture_kind: str
    started_at: datetime
    summary: str
    ocr_text: str
    transcript_text: str
    window_titles: tuple[str, ...] = ()
    config: BaseModel | None = None


@dataclass(frozen=True)
class CaptureInfo:
    """A capture snapshot used by :meth:`Skill.should_close` and
    :meth:`Skill.render_archive`."""

    capture_id: int
    started_at: datetime
    summary: str
    ocr_text: str
    transcript_text: str
    file_paths: tuple[Path, ...] = ()


class Skill(ABC):
    """A pluggable categorization unit.

    Subclasses must define ``name``, ``display_name``, ``version``,
    ``description``, and override :meth:`detect`. Optional overrides:
    :attr:`Config`, :meth:`should_close`, :meth:`render_archive`.

    Skills run in-process and see the full OCR + transcript text of
    every capture. Users installing third-party skills must trust their
    source — RIN does not sandbox skill code.
    """

    name: str = "skill"
    display_name: str = "Skill"
    version: str = "0.0.0"
    description: str = ""

    # Optional Pydantic schema for the skill's [skills.<name>] config
    # table. ``None`` means the skill takes no configuration.
    Config: type[BaseModel] | None = None

    def __init__(self, config: BaseModel | None = None) -> None:
        self.config = config

    # ----- mandatory --------------------------------------------------

    @abstractmethod
    def detect(self, ctx: SkillContext) -> list[BucketRef]:
        """Return the buckets this capture belongs to (may be empty)."""

    # ----- optional overrides ----------------------------------------

    def should_close(
        self,
        bucket: Any,
        captures: list[CaptureInfo],
        now: datetime,
    ) -> bool:
        """Return ``True`` if ``bucket`` should be archived now.

        Default: never auto-close (callers can manually archive via the
        UI). ``bucket`` is the SQLAlchemy ``Bucket`` row; the skill
        should treat it as read-only.
        """

        return False

    def render_archive(
        self,
        bucket: Any,
        captures: list[CaptureInfo],
        provider: Any | None = None,
    ) -> str:
        """Produce the Markdown body for the bucket's archive.

        Default: a chronological list with summaries. Skills targeting
        a richer narrative should override and (optionally) use the
        passed ``provider`` (an ``rin.llm.base.Provider``).
        """

        return _default_archive(bucket, captures)


def _default_archive(bucket: Any, captures: list[CaptureInfo]) -> str:
    """Plain chronological dump — every skill's safe fallback."""

    title = getattr(bucket, "title", None) or getattr(bucket, "key", "Archive")
    opened = getattr(bucket, "opened_at", None)
    closed = getattr(bucket, "closed_at", None)
    lines = [f"# {title}", ""]
    if opened or closed:
        lines.append(
            f"**Opened:** {opened.isoformat() if opened else '—'}  "
            f"**Closed:** {closed.isoformat() if closed else '—'}"
        )
        lines.append("")
    lines.append(f"**Captures:** {len(captures)}")
    lines.append("")
    for cap in sorted(captures, key=lambda c: c.started_at):
        ts = cap.started_at.isoformat()
        line = f"- `cap-{cap.capture_id}` @ {ts}"
        if cap.summary:
            line += f" — {cap.summary[:240]}"
        lines.append(line)
    return "\n".join(lines) + "\n"
