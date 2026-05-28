from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag

from rin import paths
from rin.utils.encryption import CaptureCipher


def test_encrypt_decrypt_bytes_round_trip() -> None:
    cipher = CaptureCipher()
    plaintext = (b"screen-capture-bytes" * 64) + b"\x00\x01\x02"
    ciphertext = cipher.encrypt_bytes(plaintext)

    assert ciphertext != plaintext
    assert CaptureCipher().decrypt_bytes(ciphertext) == plaintext
    assert (paths.root_dir() / ".master.key.enc").exists()


def test_encrypt_bytes_uses_a_fresh_nonce_each_time() -> None:
    cipher = CaptureCipher()
    plaintext = b"same payload"

    first = cipher.encrypt_bytes(plaintext)
    second = cipher.encrypt_bytes(plaintext)

    assert first != second
    assert first[:12] != second[:12]


def test_tampered_ciphertext_raises_invalid_tag() -> None:
    cipher = CaptureCipher()
    ciphertext = bytearray(cipher.encrypt_bytes(b"top secret"))
    ciphertext[-1] ^= 0x01

    try:
        CaptureCipher().decrypt_bytes(bytes(ciphertext))
    except InvalidTag:
        return
    raise AssertionError("tampered ciphertext must raise InvalidTag")


def test_encrypt_file_decrypt_file_round_trip_for_five_megabytes(tmp_path) -> None:
    cipher = CaptureCipher()
    plaintext = os.urandom(5 * 1024 * 1024)
    src = tmp_path / "capture.bin"
    encrypted = tmp_path / "capture.bin.enc"
    decrypted = tmp_path / "capture.roundtrip.bin"
    src.write_bytes(plaintext)

    cipher.encrypt_file(src, encrypted)
    CaptureCipher().decrypt_file(encrypted, decrypted)

    assert decrypted.read_bytes() == plaintext


def test_is_available_is_true_on_this_windows_machine() -> None:
    assert CaptureCipher.is_available() is True
