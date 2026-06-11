"""GitHub Copilot CLI provider.

Invokes the ``copilot`` binary as a subprocess in non-interactive mode
(``-p / --prompt`` + ``--silent`` + ``--no-color`` + ``--allow-all-tools``).
Image analysis uses ``--attachment <path>`` which the CLI natively
supports.

Caveats
-------
* The CLI must already be installed and the user must have signed in via
  ``copilot login``. If the binary is missing we raise
  :class:`ProviderUnavailable`; if the binary exists but auth has expired,
  the subprocess will fail and we raise :class:`LLMError` with stderr.
* No streaming — we run to completion and read stdout.
* Each invocation is a fresh session; we don't try to reuse Copilot
  session IDs across RIN analyses.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..utils.proc import no_window_kwargs
from .base import (
    ImageAnalysis,
    LLMError,
    Message,
    Provider,
    ProviderCapabilities,
    ProviderUnavailable,
)

DEFAULT_BINARY = "copilot"


class CopilotCLIProvider(Provider):
    name = "copilot_cli"

    def __init__(
        self,
        *,
        model: str | None = None,
        reasoning_effort: str | None = None,
        timeout_seconds: int = 60,
        binary: str = DEFAULT_BINARY,
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort or None
        self.timeout_seconds = timeout_seconds
        self.binary = binary

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_vision=True,
            supports_chat=True,
            max_context_tokens=128_000,
        )

    # --- public API ---------------------------------------------------------------

    def analyze_image(self, image_path: Path, *, prompt: str | None = None) -> ImageAnalysis:
        p = prompt or (
            "You are analyzing a desktop screenshot for a personal activity log. "
            "Produce a concise 2-4 sentence summary of what the user appears to be "
            "doing and the apps/content visible. Then on a new line beginning with "
            "'TEXT:' list any salient on-screen text (titles, errors, URLs)."
        )
        out = self._run(p, attachments=[image_path])
        summary, text = _split_summary_and_text(out)
        return ImageAnalysis(summary=summary, text=text)

    def analyze_text(self, prompt: str, *, system: str | None = None) -> str:
        full = f"{system.strip()}\n\n{prompt}" if system else prompt
        return self._run(full)

    def chat(self, messages: list[Message]) -> str:
        # The CLI has no native multi-turn JSON API in non-interactive mode;
        # we flatten the conversation into a single prompt.
        rendered_parts: list[str] = []
        for m in messages:
            tag = m.role.upper()
            rendered_parts.append(f"[{tag}]\n{m.content.strip()}")
        rendered_parts.append("[ASSISTANT]")
        return self._run("\n\n".join(rendered_parts))

    # --- internals ----------------------------------------------------------------

    def _binary_path(self) -> str:
        resolved = shutil.which(self.binary)
        if not resolved:
            raise ProviderUnavailable(
                f"Copilot CLI binary {self.binary!r} not found on PATH. "
                "Install from https://docs.github.com/copilot/how-tos/copilot-cli"
            )
        return resolved

    def _run(self, prompt: str, *, attachments: list[Path] | None = None) -> str:
        binary = self._binary_path()
        args: list[str] = [
            binary,
            "-p",
            prompt,
            "--silent",
            "--no-color",
            "--allow-all-tools",
            "--no-ask-user",
            "--no-auto-update",
        ]
        if self.model:
            args.extend(["--model", self.model])
        if self.reasoning_effort:
            args.extend(["--effort", self.reasoning_effort])
        for a in attachments or []:
            args.extend(["--attachment", str(a)])
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                # Force UTF-8 with replacement so Copilot CLI output (which
                # can contain non-ASCII chars — Chinese, emoji, smart quotes)
                # never crashes the subprocess reader thread on Windows
                # where the default would be cp1252.
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                # Suppress the flashing console window on Windows. The
                # analysis loop invokes this unattended on every capture;
                # without this a cmd window pops up each time. No-op off-Windows.
                **no_window_kwargs(),
            )
        except FileNotFoundError as exc:
            raise ProviderUnavailable(str(exc)) from exc
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"Copilot CLI timed out after {self.timeout_seconds}s") from exc
        if proc.returncode != 0:
            raise LLMError(
                f"Copilot CLI exited {proc.returncode}: "
                f"{(proc.stderr or proc.stdout or '').strip()[:500]}"
            )
        return (proc.stdout or "").strip()


def _split_summary_and_text(out: str) -> tuple[str, str]:
    """Split provider output into (summary, on-screen text) blocks."""

    if "TEXT:" not in out:
        return out.strip(), ""
    head, _, tail = out.partition("TEXT:")
    return head.strip(), tail.strip()
