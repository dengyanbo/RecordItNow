"""Phase 1-B: ``analysis_json`` structured payload + parsing."""
from __future__ import annotations

import json

from rin.analysis import structured


def test_parse_empty_returns_empty_structured() -> None:
    out = structured.parse(None)
    assert out.general_summary == ""
    assert out.poi_blocks == ()


def test_parse_valid_payload_roundtrips() -> None:
    payload = json.dumps(
        {
            "schema_version": 1,
            "general_summary": "Worked on Atlas all morning.",
            "poi_blocks": [
                {"poi": "Atlas", "block": "Refactored fulfillment queue."},
                {"poi": "Beacon", "block": "Reviewed PR-217."},
            ],
        }
    )

    parsed = structured.parse(payload)

    assert parsed.general_summary == "Worked on Atlas all morning."
    assert len(parsed.poi_blocks) == 2
    assert parsed.poi_blocks[0].poi == "Atlas"
    assert parsed.poi_blocks[0].block == "Refactored fulfillment queue."
    assert parsed.block_for("atlas") == "Refactored fulfillment queue."
    assert parsed.block_for("nope") is None


def test_parse_skips_malformed_blocks() -> None:
    payload = json.dumps(
        {
            "general_summary": "x",
            "poi_blocks": [
                {"poi": "Good", "block": "Yes"},
                {"poi": "BadMissingBlock"},
                "not even a dict",
                {"poi": "", "block": "empty poi name"},
                {"poi": "EmptyBlock", "block": "  "},
            ],
        }
    )

    parsed = structured.parse(payload)

    assert len(parsed.poi_blocks) == 1
    assert parsed.poi_blocks[0].poi == "Good"


def test_parse_garbage_returns_empty() -> None:
    assert structured.parse("not json at all").poi_blocks == ()
    assert structured.parse("[]").poi_blocks == ()
    assert structured.parse('"a string"').poi_blocks == ()


def test_parse_llm_response_strips_json_fence() -> None:
    reply = (
        "Sure, here is the JSON:\n```json\n"
        '{"schema_version": 1, "general_summary": "x", '
        '"poi_blocks": [{"poi": "Atlas", "block": "y"}]}\n'
        "```\nLet me know if you need more."
    )
    parsed = structured.parse_llm_response(reply)
    assert parsed.general_summary == "x"
    assert parsed.poi_blocks[0].poi == "Atlas"


def test_parse_llm_response_handles_naked_object() -> None:
    reply = (
        'Preamble text {"general_summary": "x", '
        '"poi_blocks": [{"poi": "A", "block": "b"}]} trailing'
    )
    parsed = structured.parse_llm_response(reply)
    assert parsed.general_summary == "x"
    assert parsed.poi_blocks[0].poi == "A"


def test_parse_llm_response_empty_on_failure() -> None:
    assert structured.parse_llm_response("").general_summary == ""
    assert structured.parse_llm_response("just prose").general_summary == ""


def test_to_json_roundtrip() -> None:
    obj = structured.StructuredAnalysis(
        general_summary="hi",
        poi_blocks=(structured.PoIBlock(poi="Atlas", block="a"),),
    )
    again = structured.parse(obj.to_json())
    assert again.general_summary == "hi"
    assert again.poi_blocks[0].poi == "Atlas"


def test_build_prompt_caps_at_max_blocks() -> None:
    prompt = structured.build_prompt(
        detected_pois=["A", "B", "C", "D", "E"],
        max_blocks=2,
        material="some content",
    )
    # Only first 2 POIs listed; the cap message states the limit.
    assert "Cover at most 2" in prompt
    assert "- A" in prompt
    assert "- B" in prompt
    assert "- C" not in prompt
    assert "- D" not in prompt


def test_build_prompt_handles_empty_pois() -> None:
    prompt = structured.build_prompt(detected_pois=[], max_blocks=2, material="x")
    assert "(none detected)" in prompt
