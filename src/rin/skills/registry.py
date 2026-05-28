"""Discover bundled + user-installed skills, validate config, return active.

Bundled skills live under ``rin.skills.builtin.*`` and are loaded by
importing each subpackage (the package's ``__init__`` must export a
module-level ``SKILL`` instance).

User-installed skills live under ``paths.skills_dir()`` (default
``%LOCALAPPDATA%\\RIN\\skills``). Each subdirectory must contain a
``skill.py`` file that exports ``SKILL`` at module level. They are
loaded via :func:`importlib.util.spec_from_file_location` so the
``skills`` folder does **not** need to be on ``sys.path``.

Discovery is best-effort: a skill that fails to import or validate is
logged + skipped without breaking the rest.
"""
from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from .. import paths
from ..config import RinConfig
from ..utils.logging import get_logger
from .base import Skill

log = get_logger(__name__)


@dataclass
class LoadedSkill:
    """A discovered skill plus the source it came from (for UI hints)."""

    skill: Skill
    source: str           # "builtin" | "user"
    source_path: str      # module path or filesystem path


def discover(cfg: RinConfig | None = None) -> list[LoadedSkill]:
    """Return every discoverable skill, with config bound + validated.

    Pass ``cfg`` to seed each skill with its
    ``[skills.<name>]`` TOML section. ``cfg=None`` is allowed for
    test-only paths; skills get ``Config()`` defaults.
    """

    found: list[LoadedSkill] = []
    found.extend(_load_builtin())
    user_dir = _user_skills_dir(cfg)
    if user_dir is not None:
        found.extend(_load_user(user_dir))

    # Bind config to every loaded skill.
    if cfg is not None:
        for ls in found:
            _bind_config(ls.skill, cfg)

    return found


def active_skills(cfg: RinConfig) -> list[LoadedSkill]:
    """Subset of :func:`discover` filtered by ``cfg.skills.enabled``."""

    wanted = set(cfg.skills.enabled or [])
    return [ls for ls in discover(cfg) if ls.skill.name in wanted]


# ---------------------------------------------------------------------------


def _load_builtin() -> Iterable[LoadedSkill]:
    try:
        import rin.skills.builtin as builtin_pkg
    except ImportError as exc:
        log.warning(f"Bundled skills package missing: {exc}")
        return []
    out: list[LoadedSkill] = []
    for _finder, name, ispkg in pkgutil.iter_modules(builtin_pkg.__path__):
        if not ispkg:
            continue  # only treat sub-packages as skills (allow helper modules)
        modname = f"rin.skills.builtin.{name}"
        try:
            mod = importlib.import_module(modname)
        except Exception as exc:
            log.warning(f"Bundled skill {modname!r} failed to import: {exc}")
            continue
        skill = getattr(mod, "SKILL", None)
        if not isinstance(skill, Skill):
            log.warning(f"Bundled skill {modname!r} missing module-level SKILL")
            continue
        out.append(LoadedSkill(skill=skill, source="builtin", source_path=modname))
    return out


def _user_skills_dir(cfg: RinConfig | None) -> Path | None:
    if cfg is not None and cfg.skills.user_skills_dir:
        candidate = Path(cfg.skills.user_skills_dir).expanduser()
        if candidate.is_dir():
            return candidate
        # Fall through to default if the user-supplied path is missing.
        log.warning(
            f"skills.user_skills_dir={candidate} does not exist; using default"
        )
    try:
        return paths.skills_dir()
    except Exception as exc:
        log.warning(f"Cannot resolve default skills dir: {exc}")
        return None


def _load_user(skills_dir: Path) -> Iterable[LoadedSkill]:
    if not skills_dir.is_dir():
        return []
    out: list[LoadedSkill] = []
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith((".", "_")):
            continue
        skill_py = entry / "skill.py"
        if not skill_py.exists():
            continue
        try:
            skill = _load_skill_py(entry.name, skill_py)
        except Exception as exc:
            log.warning(f"User skill {entry.name!r} failed to load: {exc}")
            continue
        if skill is None:
            continue
        out.append(LoadedSkill(skill=skill, source="user", source_path=str(skill_py)))
    return out


def _load_skill_py(folder_name: str, skill_py: Path) -> Skill | None:
    # Use a unique module name so two user skills with the same internal
    # name don't collide in ``sys.modules``.
    mod_name = f"rin._user_skills.{folder_name}"
    spec = importlib.util.spec_from_file_location(mod_name, skill_py)
    if spec is None or spec.loader is None:
        log.warning(f"Cannot build module spec for {skill_py}")
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    skill = getattr(module, "SKILL", None)
    if not isinstance(skill, Skill):
        log.warning(f"User skill {folder_name!r} missing module-level SKILL")
        return None
    return skill


def _bind_config(skill: Skill, cfg: RinConfig) -> None:
    """Validate the skill's TOML section against its ``Config`` schema."""

    if skill.Config is None:
        skill.config = None
        return
    raw = cfg.skills.config_for_skill(skill.name) or {}
    try:
        skill.config = skill.Config.model_validate(raw)
    except ValidationError as exc:
        log.warning(
            f"Skill {skill.name!r} config invalid; using defaults: {exc}"
        )
        skill.config = skill.Config()


__all__ = ["LoadedSkill", "active_skills", "discover"]
