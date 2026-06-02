"""SQLAlchemy ORM models for RIN's metadata database.

Schema summary
--------------
* ``captures``        — one row per screenshot or recording session.
* ``capture_files``   — physical files belonging to a capture, one per monitor / stream.
* ``monitors``        — last-seen geometry per physical display.
* ``analyses``        — per-capture LLM summary + OCR text + entities.
* ``transcripts``     — Whisper output for video captures.
* ``reports``         — generated daily / weekly markdown rollups.
* ``report_text``     — cached markdown bodies for full-text report search.
* ``tags`` + ``capture_tags`` — user / auto tagging (many-to-many).
* ``buckets`` + ``capture_buckets`` — skill-driven categorization (v0.5+).
* ``poi_candidates``  — discovery-suggested PoIs (v0.8+).
* ``key_value``       — runtime state the user never directly edits.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Capture(Base):
    __tablename__ = "captures"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # "screenshot" | "video"
    status: Mapped[str] = mapped_column(String(32), default="pending")
    started_at: Mapped[datetime] = mapped_column(default=func.now(), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(default=None)
    duration_ms: Mapped[int | None] = mapped_column(default=None)
    file_size: Mapped[int | None] = mapped_column(BigInteger, default=None)
    folder: Mapped[str | None] = mapped_column(Text, default=None)
    thumbnail_path: Mapped[str | None] = mapped_column(Text, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    files: Mapped[list[CaptureFile]] = relationship(
        back_populates="capture", cascade="all, delete-orphan"
    )
    analyses: Mapped[list[Analysis]] = relationship(
        back_populates="capture", cascade="all, delete-orphan"
    )
    transcripts: Mapped[list[Transcript]] = relationship(
        back_populates="capture", cascade="all, delete-orphan"
    )
    tags: Mapped[list[Tag]] = relationship(
        secondary="capture_tags", back_populates="captures"
    )


class CaptureFile(Base):
    __tablename__ = "capture_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    capture_id: Mapped[int] = mapped_column(
        ForeignKey("captures.id", ondelete="CASCADE"), index=True
    )
    monitor_index: Mapped[int]
    path: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(32))  # image/png, video/mp4, audio/wav
    width: Mapped[int | None] = mapped_column(default=None)
    height: Mapped[int | None] = mapped_column(default=None)
    file_size: Mapped[int | None] = mapped_column(BigInteger, default=None)

    capture: Mapped[Capture] = relationship(back_populates="files")


class Monitor(Base):
    __tablename__ = "monitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_name: Mapped[str] = mapped_column(String(255), unique=True)
    x: Mapped[int]
    y: Mapped[int]
    width: Mapped[int]
    height: Mapped[int]
    is_primary: Mapped[bool] = mapped_column(default=False)
    last_seen_at: Mapped[datetime] = mapped_column(default=func.now())


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    capture_id: Mapped[int] = mapped_column(
        ForeignKey("captures.id", ondelete="CASCADE"), index=True
    )
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    ocr_text: Mapped[str | None] = mapped_column(Text, default=None)
    entities_json: Mapped[str | None] = mapped_column(Text, default=None)
    llm_provider: Mapped[str | None] = mapped_column(String(32), default=None)
    llm_model: Mapped[str | None] = mapped_column(String(128), default=None)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), index=True)

    capture: Mapped[Capture] = relationship(back_populates="analyses")


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(primary_key=True)
    capture_id: Mapped[int] = mapped_column(
        ForeignKey("captures.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16), default=None)
    segments_json: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    capture: Mapped[Capture] = relationship(back_populates="transcripts")


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("kind", "period_start", "period_end"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    period_start: Mapped[datetime]
    period_end: Mapped[datetime]
    kind: Mapped[str] = mapped_column(String(16))  # "daily" | "weekly" | "custom"
    markdown_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    text_entry: Mapped[ReportText | None] = relationship(back_populates="report", uselist=False)


class ReportText(Base):
    __tablename__ = "report_text"

    report_id: Mapped[int] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), primary_key=True
    )
    body_text: Mapped[str] = mapped_column("body", Text)

    report: Mapped[Report] = relationship(back_populates="text_entry")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)

    captures: Mapped[list[Capture]] = relationship(
        secondary="capture_tags", back_populates="tags"
    )


class CaptureTag(Base):
    __tablename__ = "capture_tags"

    capture_id: Mapped[int] = mapped_column(
        ForeignKey("captures.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )


class Bucket(Base):
    """A skill-driven categorization unit (v0.5+).

    A bucket groups N captures under a single key (e.g. a support ticket
    ID) that a :class:`~rin.skills.base.Skill` extracted via its
    :meth:`detect` method. When the skill decides the bucket is "done"
    (resolved, archived, etc.) the scheduler runs the skill's
    :meth:`render_archive`, writes the resulting Markdown to
    ``reports/archives/<skill>/<key>.md``, and flips ``status`` to
    ``archived`` with ``closed_at`` + ``archive_path`` populated.
    """

    __tablename__ = "buckets"
    __table_args__ = (UniqueConstraint("skill_name", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    skill_name: Mapped[str] = mapped_column(String(64), index=True)
    key: Mapped[str] = mapped_column(String(256), index=True)
    title: Mapped[str] = mapped_column(Text)
    extra_json: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(16), default="active")  # "active" | "archived"
    opened_at: Mapped[datetime] = mapped_column(default=func.now(), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(default=None)
    archive_path: Mapped[str | None] = mapped_column(Text, default=None)


class CaptureBucket(Base):
    """Junction table — one capture can belong to many buckets."""

    __tablename__ = "capture_buckets"

    capture_id: Mapped[int] = mapped_column(
        ForeignKey("captures.id", ondelete="CASCADE"), primary_key=True
    )
    bucket_id: Mapped[int] = mapped_column(
        ForeignKey("buckets.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(default=func.now())


class PoICandidate(Base):
    """A discovery-suggested Point of Interest (v0.8+).

    Surfaces to the user in Settings → "Topics & PoIs" → Suggested tab.
    The user accepts (→ written into config.toml [skills.topic]),
    rejects, or merges. Discovery is rerunnable and re-suggests pending
    candidates; accepted/rejected ones are remembered so we don't pester.
    """

    __tablename__ = "poi_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    suggested_name: Mapped[str] = mapped_column(String(256), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # "regex" | "domain" | "phrase" | "llm"
    description: Mapped[str | None] = mapped_column(Text, default=None)
    evidence_capture_ids: Mapped[str] = mapped_column(Text)  # JSON list of ints
    score: Mapped[float] = mapped_column(default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|accepted|rejected|merged
    suggested_at: Mapped[datetime] = mapped_column(default=func.now(), index=True)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)
    decided_by: Mapped[str | None] = mapped_column(String(32), default=None)  # "user" | "auto"


class KeyValue(Base):
    """Runtime state the user never directly edits (last-run timestamps, panic-pause expiry, …)."""

    __tablename__ = "key_value"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())
