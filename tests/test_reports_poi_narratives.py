"""Phase 1-C (v0.12.0): per-POI narrative paragraphs in per_poi reports.

Sections with >= POI_NARRATIVE_MIN_CAPTURES captures and a provider
get a 2-3 sentence cross-capture narrative. The narrative is cached
in ``reports.poi_narratives_json`` so re-rendering the same report
doesn't re-call the LLM.

Behavioural contract:
- < min captures → no narrative call, no cache write
- no provider → no narrative call
- cache hit → no LLM call, narrative reused
- narrative rendered into both Jinja template and offline plain text
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from rin import paths as paths_mod
from rin.config import RinConfig
from rin.llm.base import LLMError, Provider, ProviderCapabilities
from rin.reports.generator import (
    POI_NARRATIVE_MIN_CAPTURES,
    PoIReportSection,
    ReportPeriod,
    _build_narrative_prompt,
    _render_poi_grouped_offline,
    generate_report,
    populate_poi_narratives,
)
from rin.storage import db, init_db, session
from rin.storage.models import (
    Analysis,
    Bucket,
    Capture,
    CaptureBucket,
    Report,
)


class _RecordingProvider(Provider):
    name = "recording"
    model = "test"

    def __init__(self, response: str = "Narrative paragraph.") -> None:
        self.response = response
        self.calls: list[tuple[str, str | None]] = []

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(vision=False, text=True, audio=False)

    def is_available(self) -> bool:
        return True

    def analyze_text(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append((prompt, system))
        return self.response

    def analyze_image(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError

    def chat(self, messages):  # pragma: no cover
        raise NotImplementedError


class _BoomProvider(Provider):
    name = "boom"
    model = "test"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(vision=False, text=True, audio=False)

    def is_available(self) -> bool:
        return True

    def analyze_text(self, prompt: str, *, system: str | None = None) -> str:
        raise LLMError("nope")

    def analyze_image(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError

    def chat(self, messages):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture()
def rin_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    paths_mod.reset_cache()
    db.reset()
    init_db()
    yield tmp_path
    db.reset()
    paths_mod.reset_cache()


def _period() -> ReportPeriod:
    return ReportPeriod(
        kind="daily",
        start=datetime(2026, 6, 1, 0, 0),
        end=datetime(2026, 6, 2, 0, 0),
    )


def _section(title: str, capture_count: int) -> PoIReportSection:
    from rin.reports.generator import CaptureItem

    captures = [
        CaptureItem(
            id=10 * (i + 1),
            kind="screenshot",
            started_at=datetime(2026, 6, 1, 9 + i, 0),
            duration_ms=None,
            monitor_count=1,
            summary=f"{title} capture #{i + 1}",
        )
        for i in range(capture_count)
    ]
    return PoIReportSection(
        bucket_id=hash(title) & 0xFFFF,
        title=title,
        status_change=None,
        captures=captures,
        archive_path=None,
    )


def test_populate_narratives_requires_min_captures() -> None:
    short = _section("Atlas", capture_count=POI_NARRATIVE_MIN_CAPTURES - 1)
    provider = _RecordingProvider()
    cache = populate_poi_narratives(_period(), [short], provider=provider)
    assert short.narrative is None
    assert provider.calls == []
    assert cache == {}


def test_populate_narratives_calls_llm_for_qualifying_sections() -> None:
    section = _section("Atlas", capture_count=POI_NARRATIVE_MIN_CAPTURES)
    provider = _RecordingProvider(response="Atlas progressed nicely.")
    cache = populate_poi_narratives(_period(), [section], provider=provider)
    assert section.narrative == "Atlas progressed nicely."
    assert len(provider.calls) == 1
    assert cache == {str(section.bucket_id): "Atlas progressed nicely."}


def test_populate_narratives_no_provider_skips_call() -> None:
    section = _section("Atlas", capture_count=POI_NARRATIVE_MIN_CAPTURES)
    cache = populate_poi_narratives(_period(), [section], provider=None)
    assert section.narrative is None
    assert cache == {}


def test_populate_narratives_uses_cache_no_llm_call() -> None:
    section = _section("Atlas", capture_count=POI_NARRATIVE_MIN_CAPTURES)
    provider = _RecordingProvider()
    seeded = {str(section.bucket_id): "Cached narrative."}
    cache = populate_poi_narratives(
        _period(), [section], provider=provider, cache=seeded
    )
    assert section.narrative == "Cached narrative."
    assert provider.calls == []
    # Cache entry preserved.
    assert cache[str(section.bucket_id)] == "Cached narrative."


def test_populate_narratives_handles_llm_error_gracefully() -> None:
    section = _section("Atlas", capture_count=POI_NARRATIVE_MIN_CAPTURES)
    cache = populate_poi_narratives(
        _period(), [section], provider=_BoomProvider()
    )
    assert section.narrative is None
    assert cache == {}


def test_build_narrative_prompt_includes_topic_and_captures() -> None:
    section = _section("Atlas", capture_count=POI_NARRATIVE_MIN_CAPTURES)
    prompt = _build_narrative_prompt(section, _period())
    assert "Atlas" in prompt
    assert "cap-10" in prompt
    assert "cap-20" in prompt
    assert "2026-06-01" in prompt


def test_offline_renderer_includes_narrative() -> None:
    section = _section("Atlas", capture_count=POI_NARRATIVE_MIN_CAPTURES)
    section.narrative = "Brief story of Atlas this period."
    body = _render_poi_grouped_offline(
        _period(),
        items=section.captures,
        poi_sections=[section],
        uncategorized=[],
    )
    assert "Brief story of Atlas this period." in body


def _insert_capture_with_bucket(
    when: datetime, summary: str, bucket_id: int
) -> int:
    with session() as s:
        cap = Capture(kind="screenshot", status="analyzed", started_at=when)
        s.add(cap)
        s.flush()
        s.add(Analysis(capture_id=cap.id, summary=summary))
        s.add(CaptureBucket(capture_id=cap.id, bucket_id=bucket_id))
        s.flush()
        return cap.id


def _seed_atlas_bucket_with_three_captures() -> int:
    """Returns the bucket id."""

    with session() as s:
        bucket = Bucket(
            skill_name="topic",
            key="Atlas",
            title="Atlas",
            opened_at=datetime(2026, 6, 1, 8, 0),
        )
        s.add(bucket)
        s.flush()
        bucket_id = bucket.id
    for i in range(3):
        _insert_capture_with_bucket(
            datetime(2026, 6, 1, 9 + i, 0),
            f"Atlas capture #{i + 1}",
            bucket_id,
        )
    return bucket_id


def test_generate_report_persists_narratives_to_reports_row(
    rin_db: Path, tmp_path: Path
) -> None:
    bucket_id = _seed_atlas_bucket_with_three_captures()
    cfg = RinConfig.model_validate({"reports": {"layout": "per_poi"}})
    provider = _RecordingProvider(response="Atlas advanced this period.")

    report = generate_report(_period(), cfg, provider=provider, out_dir=tmp_path)

    assert "Atlas advanced this period." in report.body
    assert len(provider.calls) >= 1  # at least the narrative call

    with session() as s:
        row = s.get(Report, report.report_id)
        assert row is not None
        assert row.poi_narratives_json is not None
        stored = json.loads(row.poi_narratives_json)
    assert stored[str(bucket_id)] == "Atlas advanced this period."


def test_generate_report_uses_cached_narratives_on_rerun(
    rin_db: Path, tmp_path: Path
) -> None:
    bucket_id = _seed_atlas_bucket_with_three_captures()
    cfg = RinConfig.model_validate({"reports": {"layout": "per_poi"}})

    # First run: provider gets called once for the narrative.
    p1 = _RecordingProvider(response="First-run narrative.")
    generate_report(_period(), cfg, provider=p1, out_dir=tmp_path)
    first_call_count = sum(
        1 for prompt, _ in p1.calls if "Narrative" not in prompt[:30] or True
    )
    assert first_call_count >= 1

    # Second run with a different provider that would return something
    # else IF called. The cached value should win — only the body LLM
    # call may fire (for the report markdown itself).
    p2 = _RecordingProvider(response="Second-run narrative.")
    report = generate_report(_period(), cfg, provider=p2, out_dir=tmp_path)

    # The cached narrative is the one that appears (when LLM body fails
    # or in offline mode); for the LLM body call it is fed into the
    # material so the response can reference it. Either way the
    # narrative call itself MUST NOT re-fire — verify by inspecting
    # prompts for the narrative-specific signature.
    narrative_calls = [
        call for call in p2.calls if "2-3 sentence paragraph" in call[0]
    ]
    assert narrative_calls == []

    with session() as s:
        row = s.get(Report, report.report_id)
        stored = json.loads(row.poi_narratives_json)
    assert stored[str(bucket_id)] == "First-run narrative."


def test_generate_report_no_narrative_when_section_too_small(
    rin_db: Path, tmp_path: Path
) -> None:
    # Only ONE capture under the bucket → below min.
    with session() as s:
        bucket = Bucket(
            skill_name="topic",
            key="Atlas",
            title="Atlas",
            opened_at=datetime(2026, 6, 1, 8, 0),
        )
        s.add(bucket)
        s.flush()
        bucket_id = bucket.id
    _insert_capture_with_bucket(
        datetime(2026, 6, 1, 10, 0), "One Atlas capture", bucket_id
    )
    cfg = RinConfig.model_validate({"reports": {"layout": "per_poi"}})
    provider = _RecordingProvider(response="should not appear")
    report = generate_report(_period(), cfg, provider=provider, out_dir=tmp_path)

    # No narrative-style prompt fired.
    narrative_calls = [
        call for call in provider.calls if "2-3 sentence paragraph" in call[0]
    ]
    assert narrative_calls == []

    with session() as s:
        row = s.get(Report, report.report_id)
    assert row.poi_narratives_json in (None, "")
