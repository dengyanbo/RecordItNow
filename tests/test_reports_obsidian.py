"""Obsidian report export tests."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from rin.config import RinConfig
from rin.reports.generator import CaptureItem, ReportPeriod, generate_report
from rin.storage import db, init_db


@pytest.fixture(autouse=True)
def fresh_db():
    db.reset()
    init_db()
    yield
    db.reset()


def _sample_item() -> CaptureItem:
    return CaptureItem(
        id=7,
        kind="screenshot",
        started_at=datetime(2026, 5, 28, 9, 30),
        duration_ms=1_000,
        monitor_count=1,
        summary="Reviewed release notes and bug backlog.",
    )


def test_generate_report_writes_obsidian_copy_when_configured(tmp_path: Path) -> None:
    cfg = RinConfig()
    cfg.llm.name = "none"
    cfg.reports.obsidian_vault_path = str(tmp_path / "vault")
    period = ReportPeriod(
        kind="daily",
        start=datetime(2026, 5, 28),
        end=datetime(2026, 5, 29),
    )

    generate_report(period, cfg, items=[_sample_item()], provider=None, out_dir=tmp_path / "reports")

    vault_copy = tmp_path / "vault" / "Daily" / "2026-05-28.md"
    expected_prefix = (
        "---\n"
        "date: 2026-05-28\n"
        "kind: daily\n"
        "captures: 1\n"
        "generated_by: RIN\n"
        "---\n\n"
    )
    assert vault_copy.exists()
    assert vault_copy.read_text(encoding="utf-8").startswith(expected_prefix)
    assert "Reviewed release notes" in vault_copy.read_text(encoding="utf-8")


def test_generate_report_skips_obsidian_copy_when_unset(tmp_path: Path) -> None:
    cfg = RinConfig()
    cfg.llm.name = "none"
    period = ReportPeriod(
        kind="daily",
        start=datetime(2026, 5, 28),
        end=datetime(2026, 5, 29),
    )

    generate_report(period, cfg, items=[_sample_item()], provider=None, out_dir=tmp_path / "reports")

    assert not (tmp_path / "vault").exists()
