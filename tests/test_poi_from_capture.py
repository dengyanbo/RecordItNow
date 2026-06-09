"""Tests for Phase 2-B: ``mine_topic_from_capture`` + persona templates."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from rin import paths as paths_mod
from rin.poi.from_capture import (
    MAX_KEYWORDS_PER_CAPTURE,
    MAX_REGEX_PATTERNS_PER_CAPTURE,
    SUGGESTED_NAME_FALLBACK,
    CaptureSeed,
    mine_topic_from_capture,
)
from rin.skills.builtin.topic.skill import TopicSpec
from rin.skills.builtin.topic.templates import (
    PERSONA_TEMPLATES,
    PersonaTemplate,
    list_templates,
    merge_template_topics,
    template_by_key,
)
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
        cap = Capture(
            kind="screenshot",
            status="analyzed",
            started_at=when,
            ended_at=when,
        )
        s.add(cap)
        s.flush()
        s.add(Analysis(capture_id=cap.id, summary=summary, ocr_text=ocr or None))
        if transcript:
            s.add(Transcript(capture_id=cap.id, text=transcript))
        s.flush()
        return cap.id


# ----- mine_topic_from_capture ---------------------------------------------


def test_mine_returns_none_for_missing_capture(rin_db: Path) -> None:
    assert mine_topic_from_capture(9999) is None


def test_mine_picks_regex_id_first(rin_db: Path) -> None:
    cap_id = _insert(
        "Customer escalated incident INC1234567 about login failure.",
        ocr="INC1234567 STATUS open",
    )
    seed = mine_topic_from_capture(cap_id)
    assert seed is not None
    assert seed.capture_id == cap_id
    assert seed.topic.name == "INC1234567"
    assert any("INC" in r for r in seed.topic.regex)
    assert "INC1234567" in seed.topic.keywords
    assert seed.evidence_quote and "INC1234567" in seed.evidence_quote


def test_mine_falls_back_to_phrase_when_no_regex(rin_db: Path) -> None:
    cap_id = _insert(
        "Worked on Project Atlas frontend rewrite all afternoon.",
        ocr="lorem ipsum nothing useful here",
    )
    seed = mine_topic_from_capture(cap_id)
    assert seed is not None
    assert seed.topic.name == "Project Atlas"
    assert seed.topic.regex == []
    assert "Project Atlas" in seed.topic.keywords


def test_mine_falls_back_to_domain(rin_db: Path) -> None:
    cap_id = _insert(
        "browsing docs",
        ocr="Opened https://docs.example.com/intro and read.",
    )
    seed = mine_topic_from_capture(cap_id)
    assert seed is not None
    assert seed.topic.name == "docs.example.com"
    assert "docs.example.com" in seed.topic.keywords


def test_mine_uses_fallback_name_for_unstructured_text(rin_db: Path) -> None:
    cap_id = _insert("just thinking about stuff", ocr="")
    seed = mine_topic_from_capture(cap_id)
    assert seed is not None
    # No regex, no domain, no title-case phrase → fallback first 30 chars.
    assert seed.topic.name.startswith("just thinking")
    assert seed.topic.regex == []
    # Fallback still produces a snippet so the editor isn't blank.
    assert seed.evidence_quote


def test_mine_returns_default_name_when_no_text(rin_db: Path) -> None:
    cap_id = _insert("", ocr="")
    seed = mine_topic_from_capture(cap_id)
    assert seed is not None
    assert seed.topic.name == SUGGESTED_NAME_FALLBACK


def test_mine_respects_keyword_and_regex_caps(rin_db: Path) -> None:
    cap_id = _insert(
        "INC1111111 INC2222222 INC3333333 INC4444444 INC5555555",
        ocr="INC6666666 INC7777777 INC8888888 INC9999999",
    )
    seed = mine_topic_from_capture(cap_id)
    assert seed is not None
    assert len(seed.topic.keywords) <= MAX_KEYWORDS_PER_CAPTURE
    assert len(seed.topic.regex) <= MAX_REGEX_PATTERNS_PER_CAPTURE


def test_mine_uses_transcript_when_summary_blank(rin_db: Path) -> None:
    cap_id = _insert(
        "",
        ocr="",
        transcript="The customer mentioned ticket CASE123456 several times.",
    )
    seed = mine_topic_from_capture(cap_id)
    assert seed is not None
    assert "CASE" in seed.topic.name


def test_mine_returns_capture_seed_dataclass(rin_db: Path) -> None:
    cap_id = _insert("Quick note about Project Atlas demo today.")
    seed = mine_topic_from_capture(cap_id)
    assert isinstance(seed, CaptureSeed)
    assert isinstance(seed.topic, TopicSpec)


# ----- persona templates ---------------------------------------------------


def test_all_personas_exist() -> None:
    keys = {template.key for template in PERSONA_TEMPLATES}
    assert keys == {"engineer", "customer_success", "researcher", "manager"}


def test_each_persona_has_topics() -> None:
    for template in PERSONA_TEMPLATES:
        assert template.topics, f"{template.key} has no topics"
        assert template.display_name, f"{template.key} missing display_name"
        for topic in template.topics:
            assert isinstance(topic, TopicSpec)
            assert topic.name
            assert topic.keywords


def test_persona_has_no_duplicate_names() -> None:
    for template in PERSONA_TEMPLATES:
        names = [topic.name.casefold() for topic in template.topics]
        assert len(names) == len(set(names)), template.key


def test_template_by_key_returns_unknown_as_none() -> None:
    assert template_by_key("does-not-exist") is None
    assert template_by_key("") is None
    assert isinstance(template_by_key("engineer"), PersonaTemplate)


def test_list_templates_matches_module_constant() -> None:
    assert list_templates() is PERSONA_TEMPLATES


def test_merge_template_topics_dedupes_by_name() -> None:
    engineer = template_by_key("engineer")
    cs = template_by_key("customer_success")
    assert engineer is not None
    assert cs is not None
    merged = merge_template_topics([engineer, cs])
    names = [topic.name.casefold() for topic in merged]
    assert len(names) == len(set(names))
    # Merged copies should be independent: mutating one doesn't affect template.
    merged[0].keywords.append("__sentinel__")
    assert "__sentinel__" not in engineer.topics[0].keywords


def test_merge_template_topics_handles_empty() -> None:
    assert merge_template_topics([]) == []
