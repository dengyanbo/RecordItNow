"""Video analyzer tests with mocked keyframe extractor + transcriber."""
from __future__ import annotations

from pathlib import Path

from rin.analysis.transcribe import Transcript
from rin.analysis.video_analyzer import analyze_video
from rin.config import AnalysisConfig
from rin.llm.base import ImageAnalysis


def _fake_extract_keyframes(video, out_dir, *, interval_seconds, **_kwargs):
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(3):
        f = out_dir / f"frame-{i:04d}.png"
        f.write_bytes(b"\x89PNG")
        frames.append(f)
    return frames


def _fake_transcribe(audio_path, *, model_name="small"):
    return Transcript(text="Hello world.", language="en", segments=[{"start": 0, "end": 1, "text": "Hello world."}])


def _fake_analyze_image(path, *, provider=None):
    return ImageAnalysis(summary=f"Summary of {path.name}", text=f"Text from {path.name}")


def test_analyze_video_collects_frame_summaries_and_transcript(tmp_path: Path) -> None:
    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"\x00\x00\x00\x18ftypisom")
    work = tmp_path / "work"
    result = analyze_video(
        vid,
        cfg=AnalysisConfig(keyframe_interval_seconds=5),
        work_dir=work,
        extract_keyframes_fn=_fake_extract_keyframes,
        transcribe_fn=_fake_transcribe,
        analyze_image_fn=_fake_analyze_image,
    )
    assert len(result.frame_summaries) == 3
    assert "Summary of frame-0000.png" in result.frame_summaries[0]
    assert "Text from frame-0000.png" in result.ocr_text
    assert result.transcript.text == "Hello world."


def test_analyze_video_cleans_up_internal_tempdir(tmp_path: Path) -> None:
    """Issue R1 (v0.3.0 review): mkdtemp leak must be plugged."""

    import os
    import tempfile

    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"\x00\x00\x00\x18ftypisom")

    seen_paths: list[Path] = []

    def grabbing_extract(video, out_dir, *, interval_seconds, **_kwargs):
        seen_paths.append(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        # Create one frame so the analyzer has something to iterate on.
        f = out_dir / "frame-0000.png"
        f.write_bytes(b"\x89PNG")
        return [f]

    # Don't pass work_dir → analyze_video allocates and must clean up.
    before = {p.name for p in Path(tempfile.gettempdir()).iterdir() if p.name.startswith("rin-vid-")}
    result = analyze_video(
        vid,
        cfg=AnalysisConfig(keyframe_interval_seconds=5),
        extract_keyframes_fn=grabbing_extract,
        transcribe_fn=lambda p, **_kw: Transcript(text=""),
        analyze_image_fn=lambda p, provider=None: ImageAnalysis(summary="s"),
    )
    after = {p.name for p in Path(tempfile.gettempdir()).iterdir() if p.name.startswith("rin-vid-")}

    assert result.frame_summaries == ["s"]
    # The work_dir created internally must no longer exist on disk.
    assert seen_paths and not seen_paths[0].exists(), \
        f"keyframe dir leaked: {seen_paths[0]}"
    # No new rin-vid-* dir was leaked at the system level.
    leaked = after - before
    assert leaked == set(), f"leaked tempdirs: {leaked}"
    # Suppress the "imported but unused" lint for `os`.
    _ = os


def test_analyze_video_respects_caller_provided_work_dir(tmp_path: Path) -> None:
    """When caller passes a work_dir we must NOT delete it."""

    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"\x00\x00\x00\x18ftypisom")
    caller_dir = tmp_path / "mywork"

    def fake_extract(video, out_dir, *, interval_seconds, **_kwargs):
        out_dir.mkdir(parents=True, exist_ok=True)
        return []

    analyze_video(
        vid,
        cfg=AnalysisConfig(),
        work_dir=caller_dir,
        extract_keyframes_fn=fake_extract,
        transcribe_fn=lambda p, **_kw: Transcript(text=""),
        analyze_image_fn=lambda p, provider=None: ImageAnalysis(summary=""),
    )
    assert caller_dir.exists(), "caller-provided work_dir must NOT be removed"


def test_missing_video_returns_empty(tmp_path: Path) -> None:
    result = analyze_video(
        tmp_path / "does-not-exist.mp4",
        cfg=AnalysisConfig(),
    )
    assert result.frame_summaries == []
    assert result.transcript.text == ""
