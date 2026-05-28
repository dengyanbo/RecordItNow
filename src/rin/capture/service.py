"""High-level capture service consumed by the rest of the app.

The :class:`InputManager`'s ``shot_requested`` / ``record_started`` /
``record_stopped`` signals are connected to :class:`CaptureService`. It
owns the active recorder (one at a time) and persists capture rows.

All public methods are thread-safe under a simple lock — the gesture
recognizer runs on the Qt main thread, but a tap could fire while a
recording finalize is still in progress.
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from ..config import RinConfig
from ..storage import session
from ..storage.files import has_enough_free_space, new_session_dir
from ..storage.models import Capture, CaptureFile
from ..utils.logging import get_logger
from .audio import record_short_clip
from .monitors import MonitorInfo, enumerate_monitors, refresh_monitor_records
from .privacy import is_capture_allowed
from .recorder import VideoRecorder
from .screenshot import capture_screenshot

log = get_logger(__name__)


class CaptureService:
    """Orchestrates screenshots + recordings and persists metadata."""

    def __init__(self, config: RinConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._recorder: VideoRecorder | None = None
        self._recording_folder: Path | None = None
        self._recording_started_at: datetime | None = None
        self._monitors: list[MonitorInfo] | None = None

    # --- lifecycle ----------------------------------------------------------------

    def warm_up(self) -> None:
        """Refresh monitor info and persist it. Called at startup."""

        try:
            self._monitors = refresh_monitor_records()
        except Exception as exc:
            log.error(f"Monitor enumeration failed: {exc}")
            self._monitors = []

    def is_recording(self) -> bool:
        return self._recorder is not None

    # --- screenshot ---------------------------------------------------------------

    def take_screenshot(self) -> int | None:
        with self._lock:
            if not self._guard_disk():
                return None
            paused_until = self._active_pause_until()
            if paused_until is not None:
                log.info(f"Skipping screenshot: captures paused until {paused_until.isoformat()}")
                return None
            if not is_capture_allowed(self.config.privacy.app_blacklist):
                log.info("Skipping screenshot: foreground window matched privacy blacklist")
                return None
            try:
                cap_id = capture_screenshot(monitors=self._monitors)
            except Exception as exc:
                log.error(f"Screenshot failed: {exc}")
                return None
            self._record_quick_note_if_enabled(cap_id)
            return cap_id

    # --- recording ----------------------------------------------------------------

    def start_recording(
        self,
        *,
        audio_device: str | None = None,
        recorder_factory=None,
    ) -> bool:
        with self._lock:
            if self._recorder is not None:
                log.warning("start_recording called while already recording; ignoring")
                return False
            if not self._guard_disk():
                return False
            paused_until = self._active_pause_until()
            if paused_until is not None:
                log.info(f"Skipping recording start: captures paused until {paused_until.isoformat()}")
                return False
            monitors = self._monitors or enumerate_monitors()
            if not monitors:
                log.error("No monitors detected; cannot start recording")
                return False

            self._recording_started_at = datetime.now()
            timestamp = self._recording_started_at.strftime("%Y%m%d-%H%M%S")
            self._recording_folder = new_session_dir("rec", timestamp=timestamp)
            # Fallback to the configured audio device when the caller didn't pass one.
            effective_audio = audio_device or self.config.capture.audio_device

            try:
                if recorder_factory is None:
                    self._recorder = VideoRecorder(
                        monitors=monitors,
                        folder=self._recording_folder,
                        capture_cfg=self.config.capture,
                        audio_device=effective_audio,
                    )
                else:
                    self._recorder = recorder_factory(
                        monitors=monitors,
                        folder=self._recording_folder,
                        capture_cfg=self.config.capture,
                        audio_device=effective_audio,
                    )
                self._recorder.start()
            except Exception as exc:
                log.error(f"start_recording failed: {exc}")
                self._recorder = None
                self._recording_folder = None
                self._recording_started_at = None
                return False
            log.info(f"Recording started → {self._recording_folder}")
            return True

    def stop_recording(self) -> int | None:
        with self._lock:
            if self._recorder is None:
                log.warning("stop_recording called when not recording")
                return None
            outputs = self._recorder.stop()
            folder = self._recording_folder
            started_at = self._recording_started_at
            self._recorder = None
            self._recording_folder = None
            self._recording_started_at = None

        return self._persist_recording(outputs, folder, started_at)

    # --- helpers ------------------------------------------------------------------

    def _persist_recording(
        self,
        outputs: list[Path],
        folder: Path | None,
        started_at: datetime | None,
    ) -> int | None:
        if folder is None or started_at is None:
            return None
        ended_at = datetime.now()
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)
        monitors = self._monitors or []
        with session() as s:
            thumb = next((out.with_suffix(".jpg") for out in outputs if out.with_suffix(".jpg").exists()), None)
            cap = Capture(
                kind="video",
                status="captured",
                folder=str(folder),
                thumbnail_path=str(thumb) if thumb else None,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=duration_ms,
            )
            files = []
            total = 0
            for out in outputs:
                size = out.stat().st_size if out.exists() else 0
                total += size
                idx = self._monitor_index_from_path(out, monitors)
                files.append(
                    CaptureFile(
                        monitor_index=idx,
                        path=str(out),
                        media_type="video/mp4",
                        file_size=size,
                    )
                )
            cap.files = files
            cap.file_size = total
            s.add(cap)
            s.flush()
            cap_id = cap.id
        log.info(f"Recording stopped: capture_id={cap_id}, {len(outputs)} file(s), {duration_ms}ms")
        return cap_id

    @staticmethod
    def _monitor_index_from_path(path: Path, monitors: list[MonitorInfo]) -> int:
        for m in monitors:
            if path.stem.endswith(f"-{m.index}"):
                return m.index
        return 0

    def _active_pause_until(self) -> datetime | None:
        paused_until_iso = self.config.privacy.paused_until_iso
        if not paused_until_iso:
            return None
        try:
            paused_until = datetime.fromisoformat(paused_until_iso)
        except ValueError:
            log.warning(f"Invalid paused_until_iso ignored: {paused_until_iso!r}")
            return None
        now = datetime.now(paused_until.tzinfo) if paused_until.tzinfo else datetime.now()
        if paused_until > now:
            return paused_until
        return None

    def _record_quick_note_if_enabled(self, capture_id: int) -> None:
        cfg = self.config.capture
        if not cfg.enable_quick_note or cfg.quick_note_seconds <= 0:
            return
        folder = self._capture_folder_for(capture_id)
        if folder is None:
            return
        try:
            record_short_clip(
                cfg.quick_note_seconds,
                cfg.quick_note_audio_device,
                folder / "quick_note.wav",
            )
        except Exception as exc:
            log.warning(f"Quick-note recording failed for capture_id={capture_id}: {exc}")

    def _capture_folder_for(self, capture_id: int) -> Path | None:
        with session() as s:
            cap = s.get(Capture, capture_id)
            if cap is None or not cap.folder:
                return None
            return Path(cap.folder)

    def _guard_disk(self) -> bool:
        if not has_enough_free_space(self.config.storage.min_free_space_gb):
            log.error(
                f"Refusing capture: less than {self.config.storage.min_free_space_gb} GB free"
            )
            return False
        return True
