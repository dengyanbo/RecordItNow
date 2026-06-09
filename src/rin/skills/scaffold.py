"""Scaffold + validate user-installable skills (Phase 3-A, v0.17.0).

Provides two thin, pure-Python helpers used by ``rin skill scaffold``
and ``rin skill validate`` CLI commands:

* :func:`scaffold_skill` — copy a curated ``skill.py`` template into
  ``<user-skills-dir>/<name>/skill.py`` so motivated power users can
  start from a known-good shape instead of cargo-culting from the
  bundled skills (which are GPL-incompatible to redistribute as a
  template since they ship as part of RIN itself).
* :func:`validate_skill` — load a ``skill.py`` file via the same
  ``importlib.util.spec_from_file_location`` plumbing the registry
  uses, then run a synthetic-context detect / should_close /
  render_archive smoke test. Returns a structured pass/fail report
  rather than raising — the CLI prints it.

No new runtime dependencies. No filesystem side effects beyond
``scaffold_skill`` writing under ``<user-skills-dir>``.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from .. import paths
from .base import BucketRef, CaptureInfo, Skill, SkillContext

# ---------------------------------------------------------------------------
# Template


_TEMPLATE = '''\
"""{display_name} — RIN user skill.

{description}

Drop this folder under ``%LOCALAPPDATA%\\\\RIN\\\\skills\\\\`` (Windows) or
``~/.local/share/rin/skills/`` (Linux/macOS). After restarting RIN it
will appear in Settings → Skills. Enable it there to start producing
buckets.

User skills run **in-process** with full access to capture text and
the RIN database. Audit the code you install.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from rin.skills.base import BucketRef, CaptureInfo, Skill, SkillContext


class Config(BaseModel):
    """TOML-validated config under ``[skills.{name}]`` in ``config.toml``."""

    # Add your own fields here. They will be validated on every RIN
    # launch; invalid TOML falls back to defaults with a warning.
    keywords: list[str] = Field(default_factory=lambda: ["TODO"])
    auto_archive_after_days: int = 30


class {class_name}(Skill):
    name = "{name}"
    display_name = "{display_name}"
    version = "{version}"
    description = "{description}"
    Config = Config

    def detect(self, ctx: SkillContext) -> list[BucketRef]:
        """Decide which bucket(s) this capture belongs to.

        Return an empty list to skip the capture. Each ``BucketRef``
        creates (or upserts into) a bucket keyed by ``(skill_name, key)``
        in RIN's database.
        """
        cfg = self.config or Config()
        haystack = " ".join(
            [ctx.summary or "", ctx.ocr_text or "", ctx.transcript_text or ""]
        ).lower()
        hits: list[BucketRef] = []
        for kw in cfg.keywords:
            if not kw:
                continue
            if kw.lower() in haystack:
                key = re.sub(r"[^a-z0-9]+", "-", kw.lower()).strip("-") or "bucket"
                hits.append(BucketRef(key=key, title=kw))
        return hits

    def should_close(
        self,
        bucket,
        captures: list[CaptureInfo],
        now: datetime,
    ) -> bool:
        """Return True to archive ``bucket`` on the next scheduler tick."""
        cfg = self.config or Config()
        if not captures:
            return False
        latest = max(c.started_at for c in captures)
        if now - latest > timedelta(days=cfg.auto_archive_after_days):
            return True
        return False


SKILL = {class_name}()
'''


def _class_name(name: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", name)
    return "".join(p[:1].upper() + p[1:] for p in parts if p) + "Skill"


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def scaffold_skill(
    name: str,
    *,
    display_name: str | None = None,
    description: str = "",
    version: str = "0.1.0",
    skills_dir: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Create a starter ``skill.py`` under ``<skills_dir>/<name>/``.

    Returns the path to the generated file. Raises ``ValueError`` on
    invalid ``name`` and ``FileExistsError`` when the target file
    already exists and ``overwrite`` is False.
    """
    if not _NAME_RE.match(name):
        raise ValueError(
            f"Invalid skill name {name!r}: must match [a-z][a-z0-9_]*"
        )
    base = (skills_dir or paths.skills_dir()).resolve()
    target_dir = base / name
    target_dir.mkdir(parents=True, exist_ok=True)
    skill_py = target_dir / "skill.py"
    if skill_py.exists() and not overwrite:
        raise FileExistsError(f"Already exists: {skill_py}")
    body = _TEMPLATE.format(
        name=name,
        display_name=display_name or name.replace("_", " ").title(),
        description=description or f"Custom skill: {name}",
        version=version,
        class_name=_class_name(name),
    )
    skill_py.write_text(body, encoding="utf-8")
    return skill_py


# ---------------------------------------------------------------------------
# Validation


@dataclass
class ValidationCheck:
    """One pass/fail entry in a validation report."""

    name: str
    passed: bool
    detail: str = ""


@dataclass
class ValidationReport:
    """Aggregated result of :func:`validate_skill`."""

    path: str
    checks: list[ValidationCheck] = field(default_factory=list)
    skill_name: str | None = None
    skill_display: str | None = None

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(ValidationCheck(name=name, passed=passed, detail=detail))

    def format(self) -> str:
        lines = [f"Validating: {self.path}"]
        if self.skill_name:
            lines.append(f"  Skill: {self.skill_name} ({self.skill_display or '—'})")
        for c in self.checks:
            tick = "✓" if c.passed else "✗"
            line = f"  {tick} {c.name}"
            if c.detail:
                line += f" — {c.detail}"
            lines.append(line)
        lines.append("")
        lines.append("PASS" if self.passed else "FAIL")
        return "\n".join(lines)


def _synthetic_ctx() -> SkillContext:
    return SkillContext(
        capture_id=1,
        capture_kind="screenshot",
        started_at=datetime.now(UTC),
        summary="The user is working on a sample task.",
        ocr_text="Window title: Sample\nTODO: investigate failure",
        transcript_text="",
        window_titles=("Sample",),
        config=None,
    )


def _synthetic_captures() -> list[CaptureInfo]:
    now = datetime.now(UTC)
    return [
        CaptureInfo(
            capture_id=1,
            started_at=now,
            summary="Sample capture",
            ocr_text="TODO",
            transcript_text="",
            file_paths=(),
        )
    ]


class _DummyBucket:
    """Stand-in for the SQLAlchemy ``Bucket`` row passed to skills."""

    def __init__(self, key: str = "sample", title: str = "Sample") -> None:
        self.key = key
        self.title = title
        self.opened_at = datetime.now(UTC)
        self.closed_at = None


def validate_skill(skill_py: Path) -> ValidationReport:
    """Load + smoke-test a ``skill.py`` file. Never raises.

    Catches the 5 most common authoring mistakes (missing ``SKILL``,
    wrong type, invalid ``Config`` schema, broken ``detect`` signature,
    crashing ``should_close`` / ``render_archive``).
    """
    report = ValidationReport(path=str(skill_py))

    # 1. file exists + importable
    if not skill_py.exists():
        report.add("file exists", False, f"not found: {skill_py}")
        return report
    report.add("file exists", True)

    mod_name = f"rin._validate_skill.{skill_py.parent.name}_{id(skill_py)}"
    spec = importlib.util.spec_from_file_location(mod_name, skill_py)
    if spec is None or spec.loader is None:
        report.add("import", False, "could not build module spec")
        return report
    module = importlib.util.module_from_spec(spec)
    try:
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
    except Exception as exc:
        report.add("import", False, f"{type(exc).__name__}: {exc}")
        sys.modules.pop(mod_name, None)
        return report
    finally:
        pass
    report.add("import", True)

    # 2. SKILL attribute exists and is a Skill instance
    skill = getattr(module, "SKILL", None)
    if skill is None:
        report.add("SKILL attribute", False, "module-level SKILL not defined")
        return report
    if not isinstance(skill, Skill):
        report.add(
            "SKILL attribute",
            False,
            f"expected Skill instance, got {type(skill).__name__}",
        )
        return report
    report.add("SKILL attribute", True, f"{type(skill).__name__}")
    report.skill_name = skill.name
    report.skill_display = skill.display_name

    # 3. required metadata non-empty
    missing = [
        attr
        for attr in ("name", "display_name", "version", "description")
        if not getattr(skill, attr, "").strip()
    ]
    if missing:
        report.add(
            "metadata", False, f"empty fields: {', '.join(missing)}"
        )
    else:
        report.add("metadata", True)

    # 4. Config (if present) is a BaseModel and defaults validate
    if skill.Config is not None:
        if not (isinstance(skill.Config, type) and issubclass(skill.Config, BaseModel)):
            report.add(
                "Config schema",
                False,
                "Config must be a pydantic.BaseModel subclass",
            )
        else:
            try:
                skill.config = skill.Config()
                report.add("Config schema", True, "defaults validate")
            except ValidationError as exc:
                report.add("Config schema", False, f"defaults invalid: {exc}")

    # 5. detect() returns list[BucketRef]
    try:
        result = skill.detect(_synthetic_ctx())
    except Exception as exc:
        report.add("detect()", False, f"{type(exc).__name__}: {exc}")
    else:
        if not isinstance(result, list):
            report.add(
                "detect()",
                False,
                f"expected list, got {type(result).__name__}",
            )
        elif not all(isinstance(r, BucketRef) for r in result):
            report.add(
                "detect()",
                False,
                "items must be BucketRef instances",
            )
        else:
            report.add("detect()", True, f"{len(result)} bucket(s)")

    # 6. should_close() doesn't raise on empty + populated captures
    try:
        skill.should_close(_DummyBucket(), [], datetime.now(UTC))
        skill.should_close(
            _DummyBucket(), _synthetic_captures(), datetime.now(UTC)
        )
        report.add("should_close()", True)
    except Exception as exc:
        report.add("should_close()", False, f"{type(exc).__name__}: {exc}")

    # 7. render_archive() doesn't raise + returns a string
    try:
        body = skill.render_archive(_DummyBucket(), _synthetic_captures(), None)
        if not isinstance(body, str):
            report.add(
                "render_archive()",
                False,
                f"expected str, got {type(body).__name__}",
            )
        else:
            report.add("render_archive()", True, f"{len(body)} chars")
    except Exception as exc:
        report.add("render_archive()", False, f"{type(exc).__name__}: {exc}")

    return report


def _resolve_skill_path(target: Path) -> Path:
    """Accept either ``<dir>`` or ``<dir>/skill.py`` and return the file."""
    if target.is_dir():
        return target / "skill.py"
    return target


__all__ = [
    "ValidationCheck",
    "ValidationReport",
    "_resolve_skill_path",
    "scaffold_skill",
    "validate_skill",
]
