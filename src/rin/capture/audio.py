"""Audio capture helpers built on ``sounddevice``.

This module is the source of raw audio samples for Phase 6 transcription;
the Phase 2 video recorder uses ffmpeg directly for the actual MP4 mux.

Two helpers:

* :func:`list_audio_devices` — enumerate available input/output devices.
* :class:`AudioRecorder`     — context-managed WAV recorder. Use
  ``loopback=True`` to capture WASAPI system-audio loopback (Windows)
  instead of a microphone.
"""
from __future__ import annotations

import contextlib
import wave
from pathlib import Path
from typing import Any

from ..utils.logging import get_logger

log = get_logger(__name__)


def list_audio_devices() -> list[dict[str, Any]]:
    """Return a list of ``{index, name, max_input_channels, hostapi}`` dicts."""

    try:
        import sounddevice as sd
    except ImportError as exc:  # pragma: no cover
        log.warning(f"sounddevice not available: {exc}")
        return []
    devices = []
    for i, d in enumerate(sd.query_devices()):
        devices.append(
            {
                "index": i,
                "name": d.get("name", f"device-{i}"),
                "max_input_channels": d.get("max_input_channels", 0),
                "max_output_channels": d.get("max_output_channels", 0),
                "hostapi": d.get("hostapi", -1),
            }
        )
    return devices


def list_dshow_audio_devices(binary: str = "ffmpeg", runner=None) -> list[str]:
    """Enumerate DirectShow **audio** input device names available to ffmpeg.

    Runs ``ffmpeg -list_devices true -f dshow -i dummy`` and parses the device
    names out of the (always non-zero) stderr listing. Returns an empty list if
    ffmpeg is missing or the call fails.

    These names are what the recorder passes to ffmpeg as ``-f dshow -i
    audio="<name>"`` — pick one from this list in the settings UI.
    """

    import shutil
    import subprocess

    if shutil.which(binary) is None and runner is None:
        return []

    runner = runner or subprocess.run
    try:
        proc = runner(
            [binary, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning(f"ffmpeg device enumeration failed: {exc}")
        return []

    return _parse_dshow_audio_devices(proc.stderr or "")


def _parse_dshow_audio_devices(stderr: str) -> list[str]:
    """Parse ffmpeg ``-list_devices`` stderr into a list of audio device names.

    Handles both the classic ``"<name>" (audio)`` format and the older
    section-header style where audio devices appear after a
    ``"DirectShow audio devices"`` header.
    """

    import re

    devices: list[str] = []
    seen: set[str] = set()
    in_audio_section = False
    name_re = re.compile(r'"([^"]+)"\s*(?:\(([^)]+)\))?')
    for raw_line in stderr.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if "directshow audio devices" in lower:
            in_audio_section = True
            continue
        if "directshow video devices" in lower:
            in_audio_section = False
            continue
        if "alternative name" in lower:
            continue
        match = name_re.search(line)
        if not match:
            continue
        name = match.group(1)
        kind = (match.group(2) or "").lower()
        is_audio = kind == "audio" or (in_audio_section and kind != "video")
        if is_audio and name not in seen:
            seen.add(name)
            devices.append(name)
    return devices


def _write_pcm16_wav(out_path: Path, data, *, samplerate: int, channels: int) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = data.tobytes() if hasattr(data, "tobytes") else bytes(data)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(payload)


def record_short_clip(
    seconds: int,
    device: int | str | None,
    out_path: Path,
) -> Path:
    """Record a short 16 kHz mono WAV clip for screenshot quick-notes."""

    try:
        import sounddevice as sd
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("sounddevice package not installed") from exc

    out_path = Path(out_path)
    samplerate = 16_000
    channels = 1
    seconds = max(0, int(seconds))
    frame_count = samplerate * seconds
    if frame_count <= 0:
        _write_pcm16_wav(out_path, b"", samplerate=samplerate, channels=channels)
        return out_path

    clip = sd.rec(
        frame_count,
        samplerate=samplerate,
        channels=channels,
        dtype="int16",
        device=device,
    )
    sd.wait()
    _write_pcm16_wav(out_path, clip, samplerate=samplerate, channels=channels)
    log.info(f"Quick-note recorded → {out_path}")
    return out_path


class AudioRecorder:
    """Records audio from a single device to a WAV file.

    Implementation note: keeps a list of received numpy arrays and writes
    them out on ``stop()`` rather than streaming, which is fine for the
    typical capture length (seconds to a few minutes). For multi-hour
    recordings we'd switch to a streaming WAV writer.
    """

    def __init__(
        self,
        out_path: Path,
        *,
        samplerate: int = 48000,
        channels: int = 2,
        device: int | str | None = None,
        loopback: bool = False,
    ) -> None:
        self.out_path = Path(out_path)
        self.samplerate = samplerate
        self.channels = channels
        self.device = device
        self.loopback = loopback
        self._stream = None
        self._buffers: list = []

    # --- lifecycle ----------------------------------------------------------------

    def start(self) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("sounddevice package not installed") from exc

        def _callback(indata, _frames, _time, _status) -> None:
            # Copy because indata is a view into a ring buffer reused by PortAudio.
            self._buffers.append(indata.copy())

        extra: dict[str, Any] = {}
        if self.loopback:  # pragma: no cover - hardware-specific
            extra["extra_settings"] = sd.WasapiSettings(loopback=True)

        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            device=self.device,
            dtype="float32",
            callback=_callback,
            **extra,
        )
        self._stream.start()
        log.info(f"AudioRecorder started → {self.out_path}")

    def stop(self) -> Path:
        if self._stream is None:
            raise RuntimeError("AudioRecorder.stop called before start")
        with contextlib.suppress(Exception):
            self._stream.stop()
            self._stream.close()
        self._stream = None
        self._flush_to_wav()
        return self.out_path

    # --- helpers ------------------------------------------------------------------

    def _flush_to_wav(self) -> None:
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("numpy not installed; required to write WAV") from exc
        if not self._buffers:
            self._write_silent_wav()
            return
        data = np.concatenate(self._buffers, axis=0)
        pcm16 = np.clip(data * 32767.0, -32768, 32767).astype(np.int16)
        _write_pcm16_wav(
            self.out_path,
            pcm16,
            samplerate=self.samplerate,
            channels=self.channels,
        )
        self._buffers.clear()

    def _write_silent_wav(self) -> None:
        _write_pcm16_wav(
            self.out_path,
            b"",
            samplerate=self.samplerate,
            channels=self.channels,
        )
