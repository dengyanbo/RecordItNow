"""System-tray application — the always-on entry point.

Wires together the input listener, capture service, analysis scheduler,
and the various secondary windows (settings, reports stub, search stub).
All capture operations are offloaded to a :class:`QThreadPool` worker
so the Qt main thread never blocks on disk I/O.
"""
from __future__ import annotations

import contextlib
from collections.abc import Callable
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, QPoint, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..analysis import AnalysisScheduler
from ..capture import CaptureService
from ..config import RinConfig, TriggerBinding
from ..input import InputManager
from ..reports import ReportsScheduler
from ..skills.scheduler import BucketScheduler
from ..utils.logging import get_logger
from ..utils.panic import PanicHotkey
from .icon import PulseIconAnimator, make_icon
from .notifications import attach as attach_tray_notifier
from .notifications import notify
from .reports_window import ReportsWindow
from .search_window import SearchWindow
from .settings_dialog import SettingsDialog
from .theme import Theme, resolve, with_accent

log = get_logger(__name__)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], object]) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:  # pragma: no cover - thread-pool plumbing
        try:
            self._fn()
        except Exception as exc:
            log.error(f"Background task failed: {exc}")


class TrayApp(QObject):
    """Owns the long-lived background workers and the tray menu."""

    shot_captured = Signal(int)
    recording_started = Signal()
    recording_stopped = Signal(int)

    # Internal: relays APScheduler-thread callbacks onto the Qt main thread
    # via Qt.QueuedConnection. Touching QSystemTrayIcon (setToolTip / setIcon)
    # from a non-main thread is not safe per Qt docs (R3 from review).
    _analysis_progress_received = Signal(int, int, int)  # (index, total, capture_id)
    _analysis_finished_received = Signal(int, int)       # (succeeded, total)

    def __init__(
        self,
        config: RinConfig,
        *,
        capture_service: CaptureService | None = None,
        input_manager: InputManager | None = None,
        analysis_scheduler: AnalysisScheduler | None = None,
        reports_scheduler: ReportsScheduler | None = None,
        bucket_scheduler: BucketScheduler | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.capture_service = capture_service or CaptureService(config)
        self.input_manager = input_manager or InputManager(config, parent=self)
        self.analysis_scheduler = analysis_scheduler or AnalysisScheduler(config)
        self.reports_scheduler = reports_scheduler or ReportsScheduler(config)
        self.bucket_scheduler = bucket_scheduler or BucketScheduler(config)
        self._pool = QThreadPool.globalInstance()

        self.tray = QSystemTrayIcon(make_icon(theme=self._current_theme()), parent=self)
        self.tray.setToolTip("RIN — Record It Now")
        self._menu = QMenu()
        self._build_menu()
        self.tray.setContextMenu(self._menu)
        attach_tray_notifier(self.tray)
        self._pulse = PulseIconAnimator(self.tray, theme=self._current_theme(), parent=self)

        self._settings_dialog: SettingsDialog | None = None
        self._reports_window: ReportsWindow | None = None
        self._search_window: SearchWindow | None = None
        self._panic_hotkey = PanicHotkey(self._panic_toggle)

        self.input_manager.shot_requested.connect(self._on_shot_requested)
        self.input_manager.record_started.connect(self._on_record_started)
        self.input_manager.record_stopped.connect(self._on_record_stopped)

        # Bounce analysis progress / completion onto the Qt main thread via
        # queued signals so tray icon + tooltip updates are MT-safe.
        self._analysis_progress_received.connect(
            self._on_analysis_progress_main, Qt.ConnectionType.QueuedConnection
        )
        self._analysis_finished_received.connect(
            self._on_analysis_finished_main, Qt.ConnectionType.QueuedConnection
        )
        self.analysis_scheduler.set_progress_callback(
            self._analysis_progress_received.emit,
            finished_cb=self._analysis_finished_received.emit,
        )

    # --- lifecycle ----------------------------------------------------------------

    def start(self) -> None:
        self.capture_service.warm_up()
        self.input_manager.start()
        self.analysis_scheduler.start()
        self.reports_scheduler.start()
        self.bucket_scheduler.start()
        self._panic_hotkey.install()
        self.tray.show()
        # Pre-warm the context menu so the first user right-click is snappy.
        # Without this, Qt lazily computes emoji font metrics + applies QSS
        # on the first popup, manifesting as a 400-500 ms hang. Schedule it
        # after Qt has fully initialised the tray (a 250 ms delay) so the
        # warm-up runs alongside our background-thread bootstrap rather than
        # competing with it on the main thread.
        QTimer.singleShot(250, self._prewarm_menu)
        notify(
            "RIN started",
            "Press your trigger button to capture. Ctrl+Alt+Shift+P to pause.",
        )

    def _prewarm_menu(self) -> None:
        """Pay Qt's first-popup cost off the user's interaction path.

        Measured cost on Windows / PySide6 6.7 with our 325-line QSS and
        emoji action labels:

        * ``ensurePolished()`` ≈ 1 ms (applies the stylesheet to the menu)
        * ``sizeHint()`` cold ≈ 470 ms — dominates because emoji glyphs in
          action text force a full font metrics scan
        * ``popup()`` cold ≈ 80 ms; warm ≈ 5 ms — builds the native Win32
          ``HMENU`` and runs the first paint pipeline

        We run all three here so the first real right-click only pays the
        warm cost.
        """

        try:
            self._menu.ensurePolished()
            # Force layout — this is where the bulk of the cold cost lives.
            self._menu.sizeHint()
            # Briefly popup at an off-screen coordinate that is well outside
            # any plausible monitor layout. The window is hidden on the next
            # event-loop tick so the user never sees it.
            self._menu.popup(QPoint(-10000, -10000))
            QTimer.singleShot(0, self._menu.hide)
        except Exception as exc:
            # Pre-warm is a UX optimisation, never block the user if it
            # fails on an unusual Qt build / display config.
            log.debug(f"Tray menu pre-warm skipped: {exc}")

    def stop(self) -> None:
        self._panic_hotkey.uninstall()
        # If a recording is still active when the app quits, finalize it
        # gracefully — otherwise the ffmpeg subprocess(es) survive as orphans
        # and keep recording silently (issue R4 from the v0.3.0 review).
        try:
            if self.capture_service.is_recording():
                log.info("Stopping in-progress recording before shutdown")
                self.capture_service.stop_recording()
        except Exception as exc:
            log.warning(f"stop_recording during shutdown raised: {exc}")
        with contextlib.suppress(Exception):
            self._pulse.stop()
        self.analysis_scheduler.stop()
        self.reports_scheduler.stop()
        self.bucket_scheduler.stop()
        self.input_manager.stop()
        self.tray.hide()

    # --- menu construction --------------------------------------------------------

    def _build_menu(self) -> None:
        self._capture_action = QAction("📸 Capture now", self)
        self._capture_action.triggered.connect(self._on_shot_requested)
        self._menu.addAction(self._capture_action)

        self._record_action = QAction("⏺  Start recording", self)
        self._record_action.triggered.connect(self._toggle_recording)
        self._menu.addAction(self._record_action)

        self._menu.addSeparator()

        self._reports_action = QAction("📄 Reports…", self)
        self._reports_action.triggered.connect(self._open_reports)
        self._menu.addAction(self._reports_action)

        self._search_action = QAction("🔎 Search…", self)
        self._search_action.triggered.connect(self._open_search)
        self._menu.addAction(self._search_action)

        self._settings_action = QAction("⚙️  Settings…", self)
        self._settings_action.triggered.connect(self._open_settings)
        self._menu.addAction(self._settings_action)

        self._menu.addSeparator()

        self._analyze_action = QAction("🧠 Analyze now", self)
        self._analyze_action.triggered.connect(self._analyze_now)
        self._menu.addAction(self._analyze_action)

        self._pause_action = QAction("⏸  Pause captures", self, checkable=True)
        self._pause_action.triggered.connect(self._toggle_pause)
        self._menu.addAction(self._pause_action)

        self._pause_15_action = QAction("⏸ Pause captures for 15 min", self)
        self._pause_15_action.triggered.connect(self._pause_captures_for_15_minutes)
        self._menu.addAction(self._pause_15_action)

        self._menu.addSeparator()

        self._diagnostic_action = QAction("🩺 Generate diagnostic report", self)
        self._diagnostic_action.triggered.connect(self._generate_diagnostic)
        self._menu.addAction(self._diagnostic_action)

        self._menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit)
        self._menu.addAction(quit_action)

    # --- slots --------------------------------------------------------------------

    # Map skip-reasons returned by CaptureService.last_skip() to user-facing
    # notification titles + severity. Kept module-level so both the screenshot
    # and recording paths share the same vocabulary.
    _SKIP_NOTIFICATION: dict[str, tuple[str, str]] = {
        "paused": ("Captures paused", "info"),
        "blacklist": ("Skipped — privacy filter", "info"),
        "disk_full": ("Not enough disk space", "warning"),
        "no_monitors": ("No displays detected", "warning"),
        "already_recording": ("Already recording", "info"),
        "failed": ("Capture failed", "warning"),
    }

    def _notify_skip(self, fallback_title: str) -> None:
        """Render a context-appropriate toast from ``CaptureService.last_skip()``.

        Reads the service's last-skip record (set inside the service's own
        lock right before it returned ``None``/``False``) so users see
        e.g. *Captures paused — Resumes at 17:06* rather than a generic
        *Capture failed*.
        """

        skip = self.capture_service.last_skip()
        if skip is None:
            notify(fallback_title, "Check the log for details.", level="warning")
            return
        title, level = self._SKIP_NOTIFICATION.get(
            skip.reason, (fallback_title, "warning")
        )
        notify(title, skip.detail, level=level)

    def _on_shot_requested(self) -> None:
        if self.input_manager.is_paused():
            return

        def _do() -> None:
            cap_id = self.capture_service.take_screenshot()
            if cap_id is not None:
                self.shot_captured.emit(cap_id)
                notify("Screenshot saved", f"capture_id={cap_id}")
            else:
                self._notify_skip("Screenshot failed")

        self._pool.start(_Task(_do))

    def _current_theme(self) -> Theme:
        return with_accent(resolve(self.config.ui.theme), self.config.ui.accent)

    def _on_record_started(self) -> None:
        if self.input_manager.is_paused():
            return

        def _do() -> None:
            if self.capture_service.start_recording():
                self.recording_started.emit()
                notify("Recording started", "Release the button to stop.")
                self._pulse.start()
                self._record_action.setText("⏹  Stop recording")
            else:
                self._notify_skip("Recording failed to start")

        self._pool.start(_Task(_do))

    def _on_record_stopped(self) -> None:
        def _do() -> None:
            cap_id = self.capture_service.stop_recording()
            self._pulse.stop()
            self._record_action.setText("⏺  Start recording")
            if cap_id is not None:
                self.recording_stopped.emit(cap_id)
                notify("Recording saved", f"capture_id={cap_id}")

        self._pool.start(_Task(_do))

    def _toggle_recording(self) -> None:
        if self.capture_service.is_recording():
            self._on_record_stopped()
        else:
            self._on_record_started()

    def _toggle_pause(self, checked: bool) -> None:
        self.input_manager.set_paused(checked)
        notify("Captures paused" if checked else "Captures resumed")

    def _panic_toggle(self) -> None:
        new_state = not self.input_manager.is_paused()
        self.input_manager.set_paused(new_state)
        self._pause_action.setChecked(new_state)
        notify("Captures paused" if new_state else "Captures resumed")

    def _pause_captures_for_15_minutes(self) -> None:
        try:
            self.config.privacy.paused_until_iso = (
                datetime.now() + timedelta(minutes=15)
            ).isoformat()
            self.config.save()
        except Exception as exc:
            log.error(f"Failed to save timed pause: {exc}")
            notify("Pause failed", "Could not save the 15-minute pause.", level="warning")
            return
        notify("Captures paused", "New captures will be skipped for the next 15 minutes.")

    def _analyze_now(self) -> None:
        notify(
            "Analysis started",
            "First run loads OCR + embedding models (10–60 s).",
        )

        def _do() -> None:
            # Manual click should bypass the working-hours/idle gate.
            self.analysis_scheduler.trigger_now(force=True)

        self._pool.start(_Task(_do))

    def _generate_diagnostic(self) -> None:
        """Build a redacted diagnostic zip and reveal it in Explorer."""

        notify(
            "Building diagnostic report",
            "Collecting logs and environment info (no captures included).",
        )

        def _do() -> None:
            try:
                from ..utils.diagnostics import build_report

                path = build_report()
            except Exception as exc:
                log.error(f"Diagnostic report failed: {exc}")
                notify(
                    "Diagnostic report failed",
                    f"{exc.__class__.__name__}: {exc}",
                    level="warning",
                )
                return
            notify(
                "Diagnostic report ready",
                f"Saved to {path.name}. Review before sharing.",
            )
            # Open File Explorer with the zip selected. Wrapped in
            # contextlib.suppress so a missing explorer.exe (e.g. headless
            # CI) does not surface as a user-facing toast.
            with contextlib.suppress(Exception):
                import subprocess

                subprocess.Popen(["explorer.exe", "/select,", str(path)])

        self._pool.start(_Task(_do))

    def _on_analysis_progress(self, index: int, total: int, capture_id: int) -> None:
        """Per-capture progress, fires on the APScheduler worker thread.

        We do **not** touch any Qt widget here. The scheduler emits the
        ``_analysis_progress_received`` Qt signal which is delivered onto
        the main thread via ``Qt.QueuedConnection`` (see ``__init__``).
        """

        # Kept for backwards-compat with callers wired pre-v0.3.1; the
        # actual UI work lives in :meth:`_on_analysis_progress_main`.
        self._analysis_progress_received.emit(index, total, capture_id)

    def _on_analysis_progress_main(self, index: int, total: int, capture_id: int) -> None:
        """Main-thread UI updates for analysis progress."""

        self.tray.setToolTip(f"RIN — Analyzing {index}/{total} (cap-{capture_id})")
        if index == 1 or index == total or index % 5 == 0:
            notify(
                f"Analyzing {index}/{total}",
                f"cap-{capture_id} done",
            )

    def _on_analysis_finished(self, succeeded: int, total: int) -> None:
        """Batch-complete callback; fires on the APScheduler thread."""

        self._analysis_finished_received.emit(succeeded, total)

    def _on_analysis_finished_main(self, succeeded: int, total: int) -> None:
        """Main-thread UI updates for batch completion."""

        self.tray.setToolTip("RIN — Record It Now")
        if total == 0:
            notify("Analysis complete", "Nothing new to analyze.")
            return
        level = "info" if succeeded == total else "warning"
        notify(
            "Analysis complete",
            f"{succeeded}/{total} captures analyzed",
            level=level,
        )

    def _open_settings(self) -> None:
        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(
                self.config,
                learn_callback=self._begin_learn_mode,
            )
            self._settings_dialog.config_saved.connect(self._on_config_saved)
        self._settings_dialog.load_from_config()
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def _open_reports(self) -> None:
        if self._reports_window is None:
            self._reports_window = ReportsWindow(self.config)
        self._reports_window.show()
        self._reports_window.raise_()

    def _open_search(self) -> None:
        if self._search_window is None:
            self._search_window = SearchWindow(self.config)
        self._search_window.show()
        self._search_window.raise_()

    def _quit(self) -> None:
        self.stop()
        from PySide6.QtWidgets import QApplication

        QApplication.quit()

    def _begin_learn_mode(self, on_captured: Callable[[TriggerBinding], None]) -> None:
        self.input_manager.start_learn(on_captured=on_captured)

    def _on_config_saved(self, cfg: RinConfig) -> None:
        self.input_manager.update_binding(cfg.trigger)
        self._apply_theme()
        notify("Settings saved")

    def _apply_theme(self) -> None:
        """Re-render the global QSS + refresh tray icons after a theme change."""

        from PySide6.QtWidgets import QApplication

        from ..app import apply_theme

        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self.config)
        theme = self._current_theme()
        self._pulse.set_theme(theme)
        if not self.capture_service.is_recording():
            self.tray.setIcon(make_icon(theme=theme))
