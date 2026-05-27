"""Copilot CLI provider tests.

We don't actually invoke the real binary — that would require an
authenticated session and is non-deterministic. Instead we stub
``shutil.which`` and ``subprocess.run`` to make sure we build the right
command line and parse responses correctly.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rin.llm.base import LLMError, Message, ProviderUnavailable
from rin.llm.copilot_cli import CopilotCLIProvider


@pytest.fixture
def fake_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rin.llm.copilot_cli.shutil.which", lambda _: "C:/fake/copilot.exe")


def _make_run(stdout: str = "", stderr: str = "", returncode: int = 0):
    captured: dict = {}

    def runner(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)

    return runner, captured


def test_missing_binary_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rin.llm.copilot_cli.shutil.which", lambda _: None)
    with pytest.raises(ProviderUnavailable):
        CopilotCLIProvider().analyze_text("hi")


def test_analyze_text_builds_command(fake_binary, monkeypatch: pytest.MonkeyPatch) -> None:
    runner, captured = _make_run(stdout="hello world\n")
    monkeypatch.setattr("rin.llm.copilot_cli.subprocess.run", runner)
    provider = CopilotCLIProvider(model="gpt-5.2", reasoning_effort="high")
    out = provider.analyze_text("What is 2+2?", system="Be terse.")
    assert out == "hello world"
    args = captured["args"]
    assert "-p" in args
    assert "--silent" in args
    assert "--allow-all-tools" in args
    assert "--no-ask-user" in args
    assert args[args.index("--model") + 1] == "gpt-5.2"
    assert args[args.index("--effort") + 1] == "high"
    prompt = args[args.index("-p") + 1]
    assert "Be terse." in prompt
    assert "What is 2+2?" in prompt


def test_effort_omitted_when_not_set(fake_binary, monkeypatch: pytest.MonkeyPatch) -> None:
    runner, captured = _make_run(stdout="ok")
    monkeypatch.setattr("rin.llm.copilot_cli.subprocess.run", runner)
    CopilotCLIProvider().analyze_text("hi")
    assert "--effort" not in captured["args"]


def test_analyze_image_attaches_file(fake_binary, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    runner, captured = _make_run(stdout="A code editor.\nTEXT: main.py")
    monkeypatch.setattr("rin.llm.copilot_cli.subprocess.run", runner)
    result = CopilotCLIProvider().analyze_image(img)
    assert result.summary == "A code editor."
    assert result.text == "main.py"
    args = captured["args"]
    assert "--attachment" in args
    assert str(img) in args


def test_nonzero_exit_raises_llmerror(fake_binary, monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _ = _make_run(stderr="not authenticated", returncode=1)
    monkeypatch.setattr("rin.llm.copilot_cli.subprocess.run", runner)
    with pytest.raises(LLMError) as exc:
        CopilotCLIProvider().analyze_text("hi")
    assert "not authenticated" in str(exc.value)


def test_timeout_raises_llmerror(fake_binary, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=1)

    monkeypatch.setattr("rin.llm.copilot_cli.subprocess.run", boom)
    with pytest.raises(LLMError):
        CopilotCLIProvider(timeout_seconds=1).analyze_text("hi")


def test_chat_flattens_messages(fake_binary, monkeypatch: pytest.MonkeyPatch) -> None:
    runner, captured = _make_run(stdout="ok")
    monkeypatch.setattr("rin.llm.copilot_cli.subprocess.run", runner)
    CopilotCLIProvider().chat(
        [
            Message(role="system", content="Be brief."),
            Message(role="user", content="Hi."),
            Message(role="assistant", content="Hello!"),
            Message(role="user", content="What's next?"),
        ]
    )
    prompt = captured["args"][captured["args"].index("-p") + 1]
    assert "[SYSTEM]" in prompt
    assert "[USER]" in prompt
    assert "[ASSISTANT]" in prompt
    assert "Be brief." in prompt
    assert "What's next?" in prompt
