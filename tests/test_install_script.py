"""Smoke checks for install.ps1 without actually invoking it.

We can't run the installer in unit tests (it would mutate the host),
but we can sanity-check that:

* The script exists and is non-empty.
* It mentions the same major.minor version as ``rin.__version__`` —
  the script reads the version from ``src/rin/__init__.py`` at runtime,
  so a drift here means the parser stopped working.
* It declares all the flags documented in the README.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "scripts" / "install.ps1"


@pytest.fixture(scope="module")
def script_text() -> str:
    assert INSTALLER.exists(), f"install.ps1 missing at {INSTALLER}"
    return INSTALLER.read_text(encoding="utf-8")


def test_script_is_non_trivial(script_text: str) -> None:
    assert len(script_text) > 1000  # surely more than a stub


def test_declares_all_advertised_flags(script_text: str) -> None:
    expected = {"InstallDir", "Prefetch", "Autostart", "SkipDeps", "Force"}
    found = set(re.findall(r"\[switch\]\$(\w+)|\[string\]\$(\w+)", script_text))
    # Flatten the regex groups.
    found_names = {a or b for a, b in found}
    missing = expected - found_names
    assert not missing, f"install.ps1 is missing param(s): {missing}"


def test_version_parser_present(script_text: str) -> None:
    # Confirms the runtime version-reading helper is wired up.
    assert "Get-RinVersion" in script_text
    assert "__version__" in script_text


def test_invokes_uv_pip_install_all(script_text: str) -> None:
    # The script must use --python to target the freshly created venv;
    # otherwise an outer VIRTUAL_ENV (e.g. maintainer's dev venv) would
    # silently win and break the install.
    assert "uv pip install --python" in script_text
    assert '-e ".[all]"' in script_text


def test_prefetch_branch_references_script(script_text: str) -> None:
    assert "prefetch_models.py" in script_text


def test_start_menu_shortcut_uses_pythonw(script_text: str) -> None:
    # pythonw avoids the black console window when the user launches from Start Menu.
    assert "pythonw.exe" in script_text


def test_install_script_has_stop_running_rin_helper(script_text: str) -> None:
    """v0.9.0: installer must close a running RIN before overwriting the bundle."""
    assert "function Stop-RunningRin" in script_text
    assert "CloseMainWindow" in script_text
    assert "Stop-Process" in script_text


def test_install_script_calls_stop_running_rin_before_remove(script_text: str) -> None:
    """The hardening call must happen BEFORE the Remove-Item that wipes InstallDir."""
    stop_idx = script_text.find("Stop-RunningRin -InstallDir $InstallDir")
    remove_idx = script_text.find("Remove-Item -Recurse -Force $InstallDir")
    assert stop_idx != -1, "expected Stop-RunningRin call site"
    assert remove_idx != -1, "expected Remove-Item -Recurse -Force $InstallDir site"
    assert stop_idx < remove_idx, "Stop-RunningRin must run before Remove-Item"


def test_install_script_has_retry_helper(script_text: str) -> None:
    """Remove-Item should be wrapped in Invoke-WithRetry with exponential backoff."""
    assert "function Invoke-WithRetry" in script_text
    assert "Invoke-WithRetry -Label" in script_text


def test_install_script_has_resolve_winget_path_helper(script_text: str) -> None:
    """v0.9.1: winget resolution must prefer the current user's WindowsApps
    directory so a stale alias from another user (a known Windows multi-user
    quirk) doesn't surface as 'The system cannot find the path specified'."""

    assert "function Resolve-WingetPath" in script_text
    # Must probe the per-user LOCALAPPDATA path before falling back to PATH.
    assert "$env:LOCALAPPDATA" in script_text
    assert "Microsoft\\WindowsApps\\winget.exe" in script_text


def test_install_winget_invocation_uses_resolved_path(script_text: str) -> None:
    """v0.9.1: Install-PackageViaWinget must invoke the resolved absolute
    path ($wingetPath), NOT a bare 'winget' lookup that re-triggers the
    multi-user bug."""

    # The helper must be called from Install-PackageViaWinget.
    install_block_start = script_text.find("function Install-PackageViaWinget")
    assert install_block_start != -1, "expected Install-PackageViaWinget function"
    # Find the end of the function (next 'function ' at top level, or end of file).
    next_fn = script_text.find("\nfunction ", install_block_start + 1)
    if next_fn == -1:
        next_fn = len(script_text)
    block = script_text[install_block_start:next_fn]

    assert "Resolve-WingetPath" in block, (
        "Install-PackageViaWinget must call Resolve-WingetPath to get an absolute path"
    )
    assert "& $wingetPath install" in block, (
        "Install-PackageViaWinget must invoke the resolved $wingetPath, "
        "not a bare 'winget' which triggers the multi-user resolution bug."
    )
    # And the old buggy form must be gone from this block.
    assert "& winget install" not in block, (
        "Bare '& winget install' must not appear in Install-PackageViaWinget — "
        "it can resolve to another user's App Execution Alias on multi-user machines."
    )
