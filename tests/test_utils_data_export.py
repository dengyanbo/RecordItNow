"""Round-trip tests for Settings → Data export/import."""
from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from rin import paths
from rin.config import RinConfig
from rin.storage import Analysis, Capture, db, init_db, session
from rin.utils.data_export import export_all, import_all


def _seed_source_root() -> None:
    cfg = RinConfig()
    cfg.analysis.ocr_languages = ["en", "de"]
    cfg.analysis.whisper_model = "medium"
    cfg.save()

    cfg_path = paths.config_path()
    cfg_text = cfg_path.read_text(encoding="utf-8")
    cfg_path.write_text(
        cfg_text.replace("[llm]\n", "[llm]\napi_key = \"sk-secret\"\n", 1),
        encoding="utf-8",
    )

    (paths.reports_dir() / "2026-05-28.md").write_text("# Daily\n", encoding="utf-8")
    (paths.chroma_dir() / "manifest.json").write_text('{"ok": true}\n', encoding="utf-8")

    db.reset()
    init_db()
    with session() as s:
        cap = Capture(kind="screenshot", status="analyzed", folder="captures\\2026\\05\\28\\cap-1")
        s.add(cap)
        s.flush()
        s.add(
            Analysis(
                capture_id=cap.id,
                summary="Finished issue triage",
                ocr_text="INC1234567",
                entities_json="{}",
                llm_provider="openai",
                llm_model="gpt-4o",
            )
        )
    db.reset()



def test_export_import_round_trip_and_scrubbed_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_source_root()
    out = tmp_path / "rin-export.zip"

    export_all(out)

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert "config.toml" in names
        assert "rin.db" in names
        assert "reports/2026-05-28.md" in names
        assert "chroma/manifest.json" in names
        assert "summaries/analyses.jsonl" in names

        config_blob = zf.read("config.toml").decode("utf-8")
        assert "sk-secret" not in config_blob
        assert "<redacted>" in config_blob

        summary_rows = [
            json.loads(line)
            for line in zf.read("summaries/analyses.jsonl").decode("utf-8").splitlines()
            if line.strip()
        ]
        assert summary_rows[0]["summary"] == "Finished issue triage"
        assert summary_rows[0]["ocr_text"] == "INC1234567"

    import_root = tmp_path / "import-root"
    monkeypatch.setenv("RIN_DATA_DIR", str(import_root))
    paths.reset_cache()
    db.reset()

    restored = import_all(out)

    assert restored == import_root
    assert (import_root / "config.toml").exists()
    assert "<redacted>" in (import_root / "config.toml").read_text(encoding="utf-8")
    assert (import_root / "reports" / "2026-05-28.md").read_text(encoding="utf-8") == "# Daily\n"
    assert (import_root / "chroma" / "manifest.json").exists()
    assert (import_root / "summaries" / "analyses.jsonl").exists()

    conn = sqlite3.connect(str(import_root / "rin.db"))
    try:
        count = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
    finally:
        conn.close()
    assert count == 1



def test_import_refuses_non_empty_root_without_force(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_source_root()
    out = tmp_path / "rin-export.zip"
    export_all(out)

    occupied = tmp_path / "occupied-root"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("keep", encoding="utf-8")
    monkeypatch.setenv("RIN_DATA_DIR", str(occupied))
    paths.reset_cache()
    db.reset()

    with pytest.raises(ValueError, match="non-empty"):
        import_all(out)
