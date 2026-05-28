"""Capture current Settings/Reports/Search windows for the v0.4.1 polish pass.

Renders each window in light + dark themes, saves PNGs to
``docs/screenshots/before_v041/`` so we can diff against the post-refactor
versions. Run with:

    python scripts/capture_ui_screenshots.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rin.app import apply_theme  # noqa: E402
from rin.config import RinConfig  # noqa: E402
from rin.storage import init_db  # noqa: E402
from rin.ui.reports_window import ReportsWindow  # noqa: E402
from rin.ui.search_window import SearchWindow  # noqa: E402
from rin.ui.settings_dialog import SettingsDialog  # noqa: E402

OUT_DIR = REPO / "docs" / "screenshots" / "before_v041"


def _grab(widget, path: Path) -> None:
    widget.show()
    widget.adjustSize()
    QApplication.processEvents()
    # let the QSS settle
    QTimer.singleShot(300, lambda: None)
    QApplication.processEvents()
    pm: QPixmap = widget.grab()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    pm.save(str(path), "PNG")
    widget.hide()
    QApplication.processEvents()


def _render(cfg: RinConfig, theme_name: str) -> None:
    cfg.ui.theme = theme_name  # type: ignore[assignment]
    apply_theme(QApplication.instance(), cfg)

    settings = SettingsDialog(cfg)
    settings.resize(820, 580)
    _grab(settings, OUT_DIR / f"settings_{theme_name}.png")

    reports = ReportsWindow(cfg)
    reports.resize(1080, 680)
    _grab(reports, OUT_DIR / f"reports_{theme_name}.png")

    search = SearchWindow(cfg)
    search.resize(940, 760)
    _grab(search, OUT_DIR / f"search_{theme_name}.png")


def main() -> int:
    _app = QApplication.instance() or QApplication(sys.argv)
    init_db()
    cfg = RinConfig.load()

    for theme in ("light", "dark"):
        _render(cfg, theme)

    print(f"saved into {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
