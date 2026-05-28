"""Tests for the progress widgets (Spinner + BusyOverlay)."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from rin.ui.progress import BusyOverlay, Spinner
from rin.ui.theme import DARK, LIGHT


def test_spinner_constructs_with_defaults(qapp) -> None:
    sp = Spinner()
    assert sp.width() == Spinner.DEFAULT_SIZE
    assert sp.height() == Spinner.DEFAULT_SIZE
    assert not sp.is_running()


def test_spinner_explicit_size_and_accent(qapp) -> None:
    sp = Spinner(size=40, accent="#FF0080")
    assert sp.width() == 40
    assert sp.height() == 40


def test_spinner_start_stop_cycle(qapp) -> None:
    sp = Spinner()
    sp.start()
    assert sp.is_running()
    sp.start()  # idempotent
    assert sp.is_running()
    sp.stop()
    assert not sp.is_running()
    sp.stop()  # idempotent
    assert not sp.is_running()


def test_spinner_set_accent_does_not_raise(qapp) -> None:
    sp = Spinner()
    sp.set_accent("#000000")
    sp.set_accent("#FFFFFF")
    # No assertion on internal state — just confirm the call survives.


def test_spinner_minimum_size_enforced(qapp) -> None:
    # The clamp prevents an unrenderable 4 px spinner.
    sp = Spinner(size=4)
    assert sp.width() == 12


def test_busy_overlay_constructs_hidden(qapp) -> None:
    parent = QWidget()
    parent.resize(400, 300)
    overlay = BusyOverlay(parent, message="Loading…")
    # Starts hidden so it doesn't intercept parent input until shown.
    assert overlay.isHidden()
    assert overlay.message() == "Loading…"


def test_busy_overlay_set_message_round_trip(qapp) -> None:
    parent = QWidget()
    overlay = BusyOverlay(parent)
    assert overlay.message() == ""
    overlay.set_message("Generating…")
    assert overlay.message() == "Generating…"


def test_busy_overlay_set_theme_does_not_raise(qapp) -> None:
    parent = QWidget()
    overlay = BusyOverlay(parent, theme=LIGHT)
    overlay.set_theme(DARK)
    overlay.set_theme(LIGHT)


def test_busy_overlay_tracks_parent_resize_via_event_filter(qapp) -> None:
    parent = QWidget()
    parent.resize(400, 300)
    parent.show()
    qapp.processEvents()
    overlay = BusyOverlay(parent)
    overlay.show()
    qapp.processEvents()
    # Resize the parent and let the event filter run.
    parent.resize(640, 480)
    qapp.processEvents()
    qapp.processEvents()  # second drain — Qt sometimes batches resize events
    assert overlay.width() == 640
    assert overlay.height() == 480
    overlay.hide()
    parent.hide()
