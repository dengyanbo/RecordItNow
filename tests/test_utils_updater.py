"""Tests for the GitHub release updater helper."""
from __future__ import annotations

import json
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from rin.utils import updater


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args) -> None:
        return None


def _payload(
    tag: str = "v0.9.0",
    *,
    assets: list[dict] | None = None,
    prerelease: bool = False,
    draft: bool = False,
) -> dict:
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/dengyanbo/RecordItNow/releases/tag/{tag}",
        "published_at": "2025-01-01T00:00:00Z",
        "prerelease": prerelease,
        "draft": draft,
        "assets": assets or [],
    }


def _patch_state_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    state_path = tmp_path / ".update-check.json"
    monkeypatch.setattr("rin.utils.updater._state_path", lambda: state_path)
    return state_path


def test_parse_version_basic() -> None:
    assert updater.parse_version("0.8.1") == (0, 8, 1)
    assert updater.parse_version("v0.9.0") == (0, 9, 0)
    assert updater.parse_version("1.2.3-rc1") == (1, 2, 3)
    assert updater.parse_version("garbage") == (0,)


def test_is_newer_strictly_greater() -> None:
    assert updater.is_newer("0.9.0", "0.8.1") is True
    assert updater.is_newer("0.8.1", "0.8.1") is False
    assert updater.is_newer("0.8.0", "0.8.1") is False


def test_build_info_skips_prerelease() -> None:
    assert updater._build_info(_payload(prerelease=True)) is None


def test_build_info_skips_draft() -> None:
    assert updater._build_info(_payload(draft=True)) is None


def test_build_info_extracts_installer_asset() -> None:
    installer = {
        "name": "RIN-v0.9.0-windows-installer.zip",
        "browser_download_url": "https://example.com/RIN-v0.9.0-windows-installer.zip",
        "size": 10 * 1024 * 1024,
    }
    source = {
        "name": "RecordItNow-v0.9.0-source.zip",
        "browser_download_url": "https://example.com/source.zip",
        "size": 123,
    }

    info = updater._build_info(_payload(assets=[source, installer]))

    assert info is not None
    assert info.latest == "0.9.0"
    assert info.asset_url == "https://example.com/RIN-v0.9.0-windows-installer.zip"
    assert info.asset_size_mb == 10.0
    assert info.published_at == "2025-01-01T00:00:00Z"


def test_build_info_no_installer_asset_yields_none_url() -> None:
    source = {
        "name": "RecordItNow-v0.9.0-source.zip",
        "browser_download_url": "https://example.com/source.zip",
        "size": 123,
    }

    info = updater._build_info(_payload(assets=[source]))

    assert info is not None
    assert info.asset_url is None
    assert info.asset_size_mb is None


def test_fetch_latest_returns_none_on_url_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        updater.urllib.request,
        "urlopen",
        Mock(side_effect=urllib.error.URLError("offline")),
    )

    assert updater._fetch_latest(timeout=0.1) is None


def test_fetch_latest_returns_none_on_http_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        updater.urllib.request,
        "urlopen",
        Mock(
            side_effect=urllib.error.HTTPError(
                url="https://example.com",
                code=403,
                msg="Forbidden",
                hdrs={},
                fp=None,
            )
        ),
    )

    assert updater._fetch_latest(timeout=0.1) is None


def test_fetch_latest_returns_none_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        updater.urllib.request,
        "urlopen",
        Mock(side_effect=TimeoutError("timed out")),
    )

    assert updater._fetch_latest(timeout=0.1) is None


def test_check_for_update_throttles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state_path = _patch_state_path(monkeypatch, tmp_path)
    state_path.write_text(
        json.dumps({"last_checked": datetime.now(UTC).isoformat()}),
        encoding="utf-8",
    )
    fetch_latest = Mock(return_value=_payload())
    monkeypatch.setattr(updater, "_fetch_latest", fetch_latest)

    assert updater.check_for_update(force=False, current_version="0.8.1") is None
    fetch_latest.assert_not_called()


def test_check_for_update_bypasses_throttle_on_force(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = _patch_state_path(monkeypatch, tmp_path)
    state_path.write_text(
        json.dumps({"last_checked": datetime.now(UTC).isoformat()}),
        encoding="utf-8",
    )
    fetch_latest = Mock(return_value=_payload("v0.9.0"))
    monkeypatch.setattr(updater, "_fetch_latest", fetch_latest)

    info = updater.check_for_update(force=True, current_version="0.8.1")

    assert info is not None
    assert info.latest == "0.9.0"
    fetch_latest.assert_called_once_with(updater.DEFAULT_TIMEOUT_SECONDS)


def test_check_for_update_returns_info_when_newer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_state_path(monkeypatch, tmp_path)
    monkeypatch.setattr(updater, "_fetch_latest", Mock(return_value=_payload("v0.9.0")))

    info = updater.check_for_update(force=True, current_version="0.8.1")

    assert isinstance(info, updater.UpdateInfo)
    assert info.latest == "0.9.0"


def test_check_for_update_returns_none_when_up_to_date(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_state_path(monkeypatch, tmp_path)
    monkeypatch.setattr(updater, "_fetch_latest", Mock(return_value=_payload("v0.8.1")))

    assert updater.check_for_update(force=True, current_version="0.8.1") is None


def test_check_for_update_updates_state_on_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = _patch_state_path(monkeypatch, tmp_path)
    monkeypatch.setattr(updater, "_fetch_latest", Mock(return_value=_payload("v0.8.1")))

    assert updater.check_for_update(force=True, current_version="0.8.1") is None

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "last_checked" in state


def test_check_for_update_does_not_update_state_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = _patch_state_path(monkeypatch, tmp_path)
    original_state = {"last_checked": "2000-01-01T00:00:00+00:00"}
    state_path.write_text(json.dumps(original_state), encoding="utf-8")
    monkeypatch.setattr(updater, "_fetch_latest", Mock(return_value=None))

    assert updater.check_for_update(force=True, current_version="0.8.1") is None

    assert json.loads(state_path.read_text(encoding="utf-8")) == original_state
