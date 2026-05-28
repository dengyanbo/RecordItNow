"""Generate a redacted diagnostic-report zip for support cases.

Invoked from the tray menu (``🩺 Generate diagnostic report``) or via
``python -m rin.utils.diagnostics``. The output zip is written under
``%LOCALAPPDATA%\\RIN\\`` and is **safe to share** — secrets, captures,
and summaries are excluded.

Bundle contents
---------------
- ``config.toml.txt``    — redacted copy of the user's config (API keys
                           blanked, paths preserved).
- ``rin.log``            — most recent log file (rotated copies last 7 days).
- ``environment.json``   — Python / OS / FFmpeg versions and monitor list.
- ``stats.json``         — counts of captures, summaries, reports (no
                           content, just totals).
- ``pip_freeze.txt``     — output of ``pip freeze`` so we can match
                           library versions.

Explicitly NOT included
-----------------------
- Any PNG / MP4 capture file
- Any LLM summary text
- Any ChromaDB content
- Any keyring secret
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import zipfile
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from .. import __app_name__, __version__, paths
from ..utils.logging import get_logger

log = get_logger(__name__)

# Top-level config keys whose value is replaced with ``"<redacted>"`` in
# the diagnostic copy. Conservative — anything that could ever hold a
# secret goes here.
_REDACT_KEY_FRAGMENTS: tuple[str, ...] = (
    "api_key",
    "api-key",
    "apikey",
    "secret",
    "token",
    "password",
    "passwd",
    "azure_endpoint",
    "azure_deployment",
)


def _redact_config_text(text: str) -> str:
    """Return ``text`` with any line whose key contains a sensitive token
    replaced by ``key = "<redacted>"``. Best-effort line-based pass —
    we keep formatting otherwise intact so the user can review.
    """

    out: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        stripped = line.lstrip()
        if (
            stripped
            and not stripped.startswith("#")
            and "=" in stripped
        ):
            key = stripped.split("=", 1)[0].strip().lower()
            if any(frag in key for frag in _REDACT_KEY_FRAGMENTS):
                indent = line[: len(line) - len(stripped)]
                out.append(f'{indent}{key} = "<redacted>"')
                continue
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def _ffmpeg_version() -> str:
    """Return the first line of ``ffmpeg -version`` or a fallback string."""

    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"<unavailable: {exc.__class__.__name__}>"
    line = (result.stdout or result.stderr or "").splitlines()
    return line[0] if line else "<empty>"


def _pip_freeze() -> str:
    """Return ``pip freeze`` output (one package per line) or an error message."""

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "<pip freeze timed out>"
    if result.returncode != 0:
        return f"<pip freeze failed (rc={result.returncode})>\n{result.stderr}"
    return result.stdout


def _monitor_summary() -> list[dict[str, int]]:
    """List active monitors as ``[{w, h, x, y}, ...]`` or empty on failure.

    We import :mod:`mss` lazily so the diagnostic script still runs when
    the ``capture`` extra is not installed.
    """

    try:
        from mss import mss  # type: ignore[import-untyped]
    except Exception as exc:  # pragma: no cover - mss is required at runtime
        log.warning(f"mss not available for monitor enumeration: {exc}")
        return []
    try:
        with mss() as sct:
            # Index 0 is the union of all monitors; drop it.
            return [
                {"w": m["width"], "h": m["height"], "x": m["left"], "y": m["top"]}
                for m in sct.monitors[1:]
            ]
    except Exception as exc:
        log.warning(f"monitor enumeration failed: {exc}")
        return []


def _capture_counts(captures_root: Path) -> dict[str, int]:
    """Return counts of capture artefacts under ``captures_root``.

    Cheap walk — we only count file extensions, never read contents.
    """

    counts = {"png": 0, "mp4": 0, "wav": 0, "other": 0, "dirs": 0}
    if not captures_root.exists():
        return counts
    for entry in captures_root.rglob("*"):
        if entry.is_dir():
            counts["dirs"] += 1
            continue
        ext = entry.suffix.lower().lstrip(".")
        if ext in counts:
            counts[ext] += 1
        else:
            counts["other"] += 1
    return counts


def _recent_log_files(logs_root: Path, limit: int = 10) -> Iterable[Path]:
    if not logs_root.exists():
        return []
    files = sorted(
        (p for p in logs_root.iterdir() if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[:limit]


def collect_environment() -> dict[str, object]:
    """Gather the environment block of the report."""

    return {
        "rin_version": __version__,
        "app_name": __app_name__,
        "python_version": sys.version.splitlines()[0],
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "ffmpeg": _ffmpeg_version(),
        "monitors": _monitor_summary(),
    }


def collect_stats(root: Path) -> dict[str, object]:
    """Gather counts that hint at the user's corpus size (no contents)."""

    return {
        "captures": _capture_counts(root / "captures"),
        "reports_count": (
            sum(1 for p in (root / "reports").rglob("*.md"))
            if (root / "reports").exists()
            else 0
        ),
        "chroma_present": (root / "chroma").exists(),
        "db_present": (root / "rin.db").exists(),
        "db_size_bytes": (
            (root / "rin.db").stat().st_size
            if (root / "rin.db").exists()
            else 0
        ),
    }


def build_report(output_dir: Path | None = None) -> Path:
    """Write a diagnostic zip and return its path.

    Parameters
    ----------
    output_dir:
        Directory to write the zip into. Defaults to
        :func:`rin.paths.root_dir`.
    """

    root = paths.root_dir()
    target_dir = output_dir or root
    target_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = target_dir / f"rin-diagnostic-{stamp}.zip"

    env = collect_environment()
    stats = collect_stats(root)
    pip = _pip_freeze()

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Redacted config
        cfg_path = paths.config_path()
        if cfg_path.exists():
            try:
                text = cfg_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = cfg_path.read_text(encoding="utf-8", errors="replace")
            zf.writestr("config.toml.txt", _redact_config_text(text))
        else:
            zf.writestr("config.toml.txt", "# config.toml not present\n")

        # Recent log files
        for log_file in _recent_log_files(paths.logs_dir()):
            try:
                zf.write(log_file, arcname=f"logs/{log_file.name}")
            except OSError as exc:
                log.warning(f"could not add {log_file}: {exc}")

        zf.writestr("environment.json", json.dumps(env, indent=2, ensure_ascii=False))
        zf.writestr("stats.json", json.dumps(stats, indent=2, ensure_ascii=False))
        zf.writestr("pip_freeze.txt", pip)

        zf.writestr(
            "README.txt",
            (
                f"{__app_name__} diagnostic report\n"
                f"generated {stamp}\n\n"
                "This zip contains no captures, no summaries, no API keys.\n"
                "Review config.toml.txt before sharing if you are unsure.\n"
            ),
        )

    log.info(f"Diagnostic report written to {out_path}")
    return out_path


def _main() -> int:
    """Module entry point: ``python -m rin.utils.diagnostics``."""

    path = build_report()
    print(f"Wrote: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module CLI entry point
    raise SystemExit(_main())
