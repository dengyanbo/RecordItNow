"""Optional AES-256-GCM encryption for capture files.

Capture plaintext is protected with a 32-byte master key stored at
``paths.root_dir() / ".master.key.enc"``. On Windows the key file is sealed
with DPAPI, so copying the drive to another machine does not expose capture
plaintext. The performance target is to keep screenshot overhead below roughly
100 ms on a typical laptop; that target is informational and not verified here.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .. import paths

try:  # pragma: no cover - exercised indirectly in is_available() tests.
    import win32crypt
except ImportError:  # pragma: no cover - non-Windows fallback.
    win32crypt = None


class CaptureCipher:
    """Encrypts capture payloads with a DPAPI-wrapped per-user AES key."""

    _DESCRIPTION = "RIN capture master key"
    _KEY_BYTES = 32
    _NONCE_BYTES = 12

    def __init__(self, key_path: Path | None = None) -> None:
        self._key_path = key_path or (paths.root_dir() / ".master.key.enc")
        self._master_key = self._load_or_create_key() if self.is_available() else None

    @staticmethod
    def is_available() -> bool:
        return sys.platform == "win32" and win32crypt is not None

    def encrypt_bytes(self, plaintext: bytes) -> bytes:
        if self._master_key is None:
            return plaintext
        nonce = os.urandom(self._NONCE_BYTES)
        ciphertext = AESGCM(self._master_key).encrypt(nonce, plaintext, None)
        return nonce + ciphertext

    def decrypt_bytes(self, ciphertext: bytes) -> bytes:
        if self._master_key is None:
            return ciphertext
        if len(ciphertext) < self._NONCE_BYTES:
            raise ValueError("Ciphertext missing AES-GCM nonce")
        nonce = ciphertext[: self._NONCE_BYTES]
        payload = ciphertext[self._NONCE_BYTES :]
        return AESGCM(self._master_key).decrypt(nonce, payload, None)

    def encrypt_file(self, src: Path, dst: Path) -> None:
        self._transform_file(src, dst, self.encrypt_bytes)

    def decrypt_file(self, src: Path, dst: Path) -> None:
        self._transform_file(src, dst, self.decrypt_bytes)

    def _load_or_create_key(self) -> bytes:
        if self._key_path.exists():
            _description, plaintext = win32crypt.CryptUnprotectData(
                self._key_path.read_bytes(),
                None,
                None,
                None,
                0,
            )
            key = bytes(plaintext)
            if len(key) != self._KEY_BYTES:
                raise ValueError("DPAPI-unwrapped master key has an unexpected length")
            return key

        key = os.urandom(self._KEY_BYTES)
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        wrapped = win32crypt.CryptProtectData(key, self._DESCRIPTION, None, None, None, 0)
        self._key_path.write_bytes(wrapped)
        return key

    def _transform_file(
        self,
        src: Path,
        dst: Path,
        transform: Callable[[bytes], bytes],
    ) -> None:
        payload = transform(Path(src).read_bytes())
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        scratch = dst.with_name(dst.name + ".tmp")
        scratch.write_bytes(payload)
        scratch.replace(dst)
