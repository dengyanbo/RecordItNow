"""FFmpeg keyframe extraction for the video analyzer.

Given a video, we extract one frame every ``interval_seconds`` to a
temp PNG and feed each through the image analyzer. This keeps the LLM
bill bounded for long recordings.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..utils.logging import get_logger
from ..utils.proc import no_window_kwargs

log = get_logger(__name__)


def ffmpeg_available(binary: str = "ffmpeg") -> bool:
    return shutil.which(binary) is not None


def extract_keyframes(
    video_path: Path,
    output_dir: Path,
    *,
    interval_seconds: int = 5,
    binary: str = "ffmpeg",
    runner=None,
) -> list[Path]:
    """Extract one frame every ``interval_seconds`` from ``video_path``.

    Returns the list of written PNG paths sorted by name. ``runner`` is for tests;
    pass a function with the same signature as ``subprocess.run`` to mock ffmpeg.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    fps_expr = f"1/{max(1, interval_seconds)}"
    pattern = output_dir / "frame-%04d.png"
    args = [
        binary,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-i",
        str(video_path),
        "-vf",
        f"fps={fps_expr}",
        "-q:v",
        "2",
        str(pattern),
    ]
    runner = runner or subprocess.run
    try:
        # Force UTF-8 with replacement so FFmpeg's stderr (which can include
        # non-ASCII codec names, paths, etc.) never crashes the reader thread
        # on Windows where the default would be cp1252.
        proc = runner(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            **no_window_kwargs(),
        )
    except FileNotFoundError as exc:
        log.warning(f"ffmpeg not found: {exc}")
        return []
    if proc.returncode != 0:
        log.warning(
            f"ffmpeg keyframe extraction failed (rc={proc.returncode}): "
            f"{(proc.stderr or '')[:200]}"
        )
        return []
    return sorted(output_dir.glob("frame-*.png"))
