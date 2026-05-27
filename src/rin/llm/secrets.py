"""Credential lookup: env-var first, then OS keyring.

Env var wins so CI/dev can override without touching the Credential
Manager, and so users running RIN as a service can inject secrets at
launch. Keyring keeps API keys out of ``config.toml``.
"""
from __future__ import annotations

import contextlib
import os

try:
    import keyring as _keyring
    import keyring.errors as _keyring_errors
except ImportError:  # pragma: no cover - keyring is optional
    _keyring = None
    _keyring_errors = None

SERVICE = "rin"


def get_secret(name: str, *, env_var: str | None = None) -> str | None:
    """Return the secret value for ``name`` or ``None`` if not set.

    Lookup order:
    1. ``env_var`` if provided and present in the environment.
    2. OS keyring under service ``rin``, username ``name``.
    """

    if env_var:
        val = os.environ.get(env_var)
        if val:
            return val
    if _keyring is None:
        return None
    try:
        return _keyring.get_password(SERVICE, name)
    except Exception:
        return None


def set_secret(name: str, value: str) -> None:
    if _keyring is None:
        raise RuntimeError("keyring package not installed; cannot persist secret")
    _keyring.set_password(SERVICE, name, value)


def delete_secret(name: str) -> None:
    if _keyring is None:
        return
    with contextlib.suppress(Exception):
        _keyring.delete_password(SERVICE, name)
