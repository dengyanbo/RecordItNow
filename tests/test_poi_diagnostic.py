"""Tests for Phase 2-C diagnostic engine."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from rin import paths as paths_mod
from rin.llm.base import ImageAnalysis, LLMError, Provider, ProviderCapabilities
from rin.poi.diagnostic import (
    DiagnosticStep,
    diagnose_topic_against_capture,
)
from rin.skills.builtin.topic.skill import TopicSpec
from rin.storage import db, init_db, session
from rin.storage.models import Analysis, Capture, Transcript


@pytest.fixture()
def rin_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RIN_DATA_DIR", str(tmp_path))
    paths_mod.reset_cache()
    db.reset()
    init_db()
    yield tmp_path
    db.reset()
    paths_mod.reset_cache()


def _insert(summary: str, *, ocr: str = "", transcript: str = "") -> int:
    when = datetime.now()
    with session() as s:
        cap = Capture(kind="screenshot", status="analyzed", started_at=when, ended_at=when)
        s.add(cap)
        s.flush()
        s.add(Analysis(capture_id=cap.id, summary=summary, ocr_text=ocr or None))
        if transcript:
            s.add(Transcript(capture_id=cap.id, text=transcript))
        s.flush()
        return cap.id


class _FakeYesProvider(Provider):
    name = "fake-yes"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_vision=False, supports_chat=True)

    def analyze_image(self, image_path, *, prompt=None):
        return ImageAnalysis(summary="")

    def analyze_text(self, prompt, *, system=None):
        return "YES, the capture looks related to that topic."

    def chat(self, messages):
        return ""


class _FakeNoProvider(_FakeYesProvider):
    name = "fake-no"

    def analyze_text(self, prompt, *, system=None):
        return "NO, this is about something else."


class _FailingProvider(_FakeYesProvider):
    name = "fake-fail"

    def analyze_text(self, prompt, *, system=None):
        raise LLMError("provider down")


def _step(result, kind: str) -> DiagnosticStep:
    for step in result.steps:
        if step.kind == kind:
            return step
    raise AssertionError(f"No {kind} step in result: {result.steps}")


# ----- core behaviour ------------------------------------------------------


def test_returns_none_for_missing_capture(rin_db: Path) -> None:
    topic = TopicSpec(name="X", keywords=["x"])
    assert diagnose_topic_against_capture(topic, 9999) is None


def test_regex_pass(rin_db: Path) -> None:
    cap_id = _insert("Looking at INC1234567 right now")
    topic = TopicSpec(name="Incidents", regex=[r"INC\d{7}"])
    result = diagnose_topic_against_capture(topic, cap_id)
    assert result is not None
    assert result.overall_match
    step = _step(result, "regex")
    assert step.passed
    assert "INC1234567" in (step.matched_text or "")


def test_regex_fail_recorded(rin_db: Path) -> None:
    cap_id = _insert("just browsing docs")
    topic = TopicSpec(name="Incidents", regex=[r"INC\d{7}"])
    result = diagnose_topic_against_capture(topic, cap_id)
    assert result is not None
    assert not result.overall_match
    step = _step(result, "regex")
    assert not step.passed


def test_keyword_pass_with_window(rin_db: Path) -> None:
    cap_id = _insert("Discussing the Atlas migration plan with the team today.")
    topic = TopicSpec(name="Atlas", keywords=["Atlas"])
    result = diagnose_topic_against_capture(topic, cap_id)
    assert result is not None
    step = _step(result, "keyword")
    assert step.passed
    assert step.matched_text and "Atlas" in step.matched_text


def test_keyword_fail_includes_closest_match(rin_db: Path) -> None:
    cap_id = _insert("Talking about the Atalas plan and team prep.")
    topic = TopicSpec(name="Atlas", keywords=["Atlas"])
    result = diagnose_topic_against_capture(topic, cap_id)
    assert result is not None
    step = _step(result, "keyword")
    assert not step.passed
    # difflib should pick up "Atalas" as a close fuzzy match.
    assert step.closest_text is not None


def test_no_regex_emits_skipped_row(rin_db: Path) -> None:
    cap_id = _insert("Just text")
    topic = TopicSpec(name="X", keywords=["x"])
    result = diagnose_topic_against_capture(topic, cap_id)
    assert result is not None
    regex_step = _step(result, "regex")
    assert "no patterns" in regex_step.value.lower()
    assert not regex_step.passed


def test_no_keywords_emits_skipped_row(rin_db: Path) -> None:
    cap_id = _insert("hello")
    topic = TopicSpec(name="X", regex=[r"hello"])
    result = diagnose_topic_against_capture(topic, cap_id)
    assert result is not None
    keyword_step = _step(result, "keyword")
    assert "no keywords" in keyword_step.value.lower()


def test_alias_pass(rin_db: Path) -> None:
    cap_id = _insert("Working on PrjAtl rollout.")
    topic = TopicSpec(name="Atlas", keywords=["atlas"], aliases=["PrjAtl"])
    result = diagnose_topic_against_capture(topic, cap_id)
    assert result is not None
    alias_step = _step(result, "alias")
    assert alias_step.passed


def test_overall_match_requires_at_least_one_pass(rin_db: Path) -> None:
    cap_id = _insert("nothing here")
    topic = TopicSpec(name="Atlas", keywords=["atlas"], regex=[r"INC\d+"])
    result = diagnose_topic_against_capture(topic, cap_id)
    assert result is not None
    assert not result.overall_match


def test_invalid_regex_recorded(rin_db: Path) -> None:
    cap_id = _insert("ok")
    topic = TopicSpec(name="X", regex=["[invalid"])
    result = diagnose_topic_against_capture(topic, cap_id)
    assert result is not None
    step = _step(result, "regex")
    assert not step.passed
    assert "invalid regex" in step.notes.lower()


# ----- llm_judge -----------------------------------------------------------


def test_llm_judge_skipped_without_provider(rin_db: Path) -> None:
    cap_id = _insert("about Atlas")
    topic = TopicSpec(name="Atlas", llm_judge=True, keywords=[])
    result = diagnose_topic_against_capture(topic, cap_id)
    assert result is not None
    step = _step(result, "llm_judge")
    assert not step.passed
    assert "no provider" in step.notes.lower()


def test_llm_judge_pass(rin_db: Path) -> None:
    cap_id = _insert("about Atlas")
    topic = TopicSpec(name="Atlas", llm_judge=True, keywords=[])
    result = diagnose_topic_against_capture(
        topic, cap_id, provider=_FakeYesProvider()
    )
    assert result is not None
    step = _step(result, "llm_judge")
    assert step.passed
    assert "YES" in step.notes


def test_llm_judge_fail(rin_db: Path) -> None:
    cap_id = _insert("about Atlas")
    topic = TopicSpec(name="Atlas", llm_judge=True, keywords=[])
    result = diagnose_topic_against_capture(
        topic, cap_id, provider=_FakeNoProvider()
    )
    assert result is not None
    step = _step(result, "llm_judge")
    assert not step.passed


def test_llm_judge_provider_failure_recorded(rin_db: Path) -> None:
    cap_id = _insert("about Atlas")
    topic = TopicSpec(name="Atlas", llm_judge=True, keywords=[])
    result = diagnose_topic_against_capture(
        topic, cap_id, provider=_FailingProvider()
    )
    assert result is not None
    step = _step(result, "llm_judge")
    assert not step.passed
    assert "provider down" in step.notes.lower()


def test_result_includes_summary_preview(rin_db: Path) -> None:
    cap_id = _insert("First line of summary.\nSecond line.")
    topic = TopicSpec(name="X", keywords=["x"])
    result = diagnose_topic_against_capture(topic, cap_id)
    assert result is not None
    assert result.summary_preview == "First line of summary."
    assert result.capture_text_chars > 0
