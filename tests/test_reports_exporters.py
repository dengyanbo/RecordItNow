"""Report export helper tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from rin.reports.exporters import export_html
from rin.ui.theme import LIGHT


def test_export_html_writes_standalone_file(tmp_path: Path) -> None:
    dst = tmp_path / "report.html"

    export_html("# Exported report\n\nBody text.", dst, LIGHT)

    content = dst.read_text(encoding="utf-8")
    assert dst.exists()
    assert dst.stat().st_size > 0
    assert "<style>" in content
    assert LIGHT.accent in content
    assert "<html" in content.lower()


def test_export_pdf_writes_non_empty_file(tmp_path: Path) -> None:
    dst = tmp_path / "report.pdf"
    script = """
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'minimal')

try:
    from PySide6.QtWidgets import QApplication
except Exception as exc:
    print(f'SKIP:{exc}')
    raise SystemExit(2)

app = QApplication.instance()
if app is None:
    try:
        app = QApplication([])
    except Exception as exc:
        print(f'SKIP:{exc}')
        raise SystemExit(2)

from rin.reports.exporters import export_pdf
from rin.ui.theme import LIGHT

export_pdf('# Exported report\\n\\nBody text.', Path(sys.argv[1]), LIGHT)
"""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "minimal"
    result = subprocess.run(
        [sys.executable, "-c", script, str(dst)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )

    if result.returncode == 2:
        pytest.skip(result.stdout.strip() or result.stderr.strip() or "QApplication unavailable")

    assert result.returncode == 0, result.stderr or result.stdout
    assert dst.exists()
    assert dst.stat().st_size > 0
