"""GitHub releases version-check for RIN.

Pings the GitHub Releases REST API once per 24 h (or on demand) to
find out whether a newer RIN is available. The result is purely
informational — we never download or install anything; the user gets
a tray balloon and clicks through to the browser to download the
installer manually.

Stdlib-only on purpose (urllib + json) so this works in any RIN env
without an extra dependency.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .. import __version__, paths

log = logging.getLogger("rin.updater")

GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/dengyanbo/RecordItNow/releases/latest"
CHECK_INTERVAL = timedelta(hours=24)
DEFAULT_TIMEOUT_SECONDS = 5.0
_INSTALLER_RE = re.compile(r"RIN-v[\d.]+-windows-installer\.zip")


@dataclass(frozen=True)
class UpdateInfo:
    """Information about a newer GitHub release."""

    latest: str
    html_url: str
    asset_url: str | None
    asset_size_mb: float | None
    published_at: str | None


def parse_version(raw: str) -> tuple[int, ...]:
    """Parse '0.9.0' / 'v0.9.0' / '0.9.0-rc1' → (0, 9, 0).

    Pre-release suffixes are ignored. Returns ``(0,)`` for unparseable
    input so comparison always succeeds.
    """

    try:
        text = raw.strip()
        if text.startswith(("v", "V")):
            text = text[1:]
        core = text.split("-", 1)[0]
        return tuple(int(part) for part in core.split("."))
    except (AttributeError, TypeError, ValueError):
        return (0,)


def is_newer(remote: str, local: str) -> bool:
    """True iff remote version is strictly newer than local."""

    remote_parts = parse_version(remote)
    local_parts = parse_version(local)
    width = max(len(remote_parts), len(local_parts))
    return remote_parts + (0,) * (width - len(remote_parts)) > local_parts + (0,) * (
        width - len(local_parts)
    )


def _state_path() -> Path:
    """Path to the throttle / last-check JSON file."""

    return paths.root_dir() / ".update-check.json"


def _read_state() -> dict:
    """Read the throttle state file, return {} on any error."""

    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(state: dict) -> None:
    """Atomically write the throttle state file. Swallow IO errors."""

    path = _state_path()
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError as exc:
        log.debug("Could not write update-check state: %s", exc)


def _should_check(force: bool) -> bool:
    """True if force=True OR last successful check was > CHECK_INTERVAL ago."""

    if force:
        return True

    last_checked = _read_state().get("last_checked")
    if not isinstance(last_checked, str):
        return True

    try:
        checked_at = datetime.fromisoformat(last_checked)
    except ValueError:
        return True
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=UTC)

    return checked_at < datetime.now(UTC) - CHECK_INTERVAL


def _fetch_latest(timeout: float) -> dict | None:
    """HTTP GET on GITHUB_LATEST_RELEASE_URL with a UA header.

    Returns the parsed JSON dict, or None on network/parse/HTTP errors.
    Sets the User-Agent to "RIN/<__version__> (https://github.com/dengyanbo/RecordItNow)".
    Honors HTTPS_PROXY via urllib's default ProxyHandler.
    """

    request = urllib.request.Request(
        GITHUB_LATEST_RELEASE_URL,
        headers={
            "User-Agent": f"RIN/{__version__} (https://github.com/dengyanbo/RecordItNow)",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        log.warning("Could not check GitHub releases for updates: %s", exc)
        return None
    return payload if isinstance(payload, dict) else None


def _build_info(payload: dict) -> UpdateInfo | None:
    """Convert raw GitHub release JSON → UpdateInfo. Skips pre-releases.

    The installer asset has name matching r'RIN-v[\\d.]+-windows-installer\\.zip'.
    """

    if payload.get("prerelease") is True or payload.get("draft") is True:
        return None

    tag_name = payload.get("tag_name")
    html_url = payload.get("html_url")
    if not isinstance(tag_name, str) or not tag_name:
        return None
    if not isinstance(html_url, str) or not html_url:
        return None

    latest = tag_name[1:] if tag_name.startswith(("v", "V")) else tag_name
    asset_url: str | None = None
    asset_size_mb: float | None = None
    for asset in payload.get("assets", []):
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        if not isinstance(name, str) or _INSTALLER_RE.fullmatch(name) is None:
            continue
        browser_download_url = asset.get("browser_download_url")
        if isinstance(browser_download_url, str):
            asset_url = browser_download_url
        size = asset.get("size")
        if isinstance(size, int | float):
            asset_size_mb = round(size / (1024 * 1024), 1)
        break

    published_at = payload.get("published_at")
    return UpdateInfo(
        latest=latest,
        html_url=html_url,
        asset_url=asset_url,
        asset_size_mb=asset_size_mb,
        published_at=published_at if isinstance(published_at, str) else None,
    )


def check_for_update(
    *,
    force: bool = False,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    current_version: str | None = None,
) -> UpdateInfo | None:
    """Top-level: throttle → fetch → parse → compare.

    Returns:
        - UpdateInfo if a newer non-prerelease version exists.
        - None if up-to-date, throttled, offline, prerelease-only, or any error.

    Always updates the throttle state on a SUCCESSFUL fetch (even if up-to-date).
    On error: does NOT update the throttle (so the next call can retry).
    """

    if not _should_check(force):
        return None

    payload = _fetch_latest(timeout)
    if payload is None:
        return None

    state = _read_state()
    state["last_checked"] = datetime.now(UTC).isoformat()
    _write_state(state)

    info = _build_info(payload)
    if info is None:
        return None

    if is_newer(info.latest, current_version or __version__):
        return info
    return None
