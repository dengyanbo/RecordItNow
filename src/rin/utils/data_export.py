"""Export and import the user-visible RIN data surface."""
from __future__ import annotations

import json
import shutil
import sqlite3
import zipfile
from pathlib import Path, PurePosixPath

from .. import paths
from .diagnostics import _redact_config_text

_ARCHIVE_PREFIXES = ("config.toml", "rin.db", "chroma/", "reports/", "summaries/")
_SUMMARIES_MEMBER = "summaries/analyses.jsonl"


def export_all(dst_zip: Path) -> Path:
    """Write a portable zip with config, DB snapshot, vector store, and reports."""

    root = paths.root_dir()
    dst_zip = Path(dst_zip)
    dst_zip.parent.mkdir(parents=True, exist_ok=True)

    snapshot_path = root / ".rin-export-snapshot.db"
    if snapshot_path.exists():
        snapshot_path.unlink()

    try:
        _snapshot_sqlite_db(paths.db_path(), snapshot_path)
        with zipfile.ZipFile(dst_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("config.toml", _redacted_config_text(paths.config_path()))
            zf.write(snapshot_path, "rin.db")
            zf.writestr(_SUMMARIES_MEMBER, _analysis_rows_jsonl(snapshot_path))
            _write_tree(zf, root / "chroma", "chroma")
            _write_tree(zf, root / "reports", "reports")
    finally:
        snapshot_path.unlink(missing_ok=True)

    return dst_zip


def import_all(src_zip: Path, *, force: bool = False) -> Path:
    """Restore an export archive into :func:`rin.paths.root_dir`."""

    root = paths.root_dir()
    root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(src_zip) as zf:
        members = [info.filename for info in zf.infolist() if info.filename and not info.is_dir()]
        if not force and any(root.iterdir()):
            raise ValueError(f"Refusing to import into non-empty directory: {root}")

        targets = {_top_level_target(name) for name in members}
        if force:
            for target in sorted(targets, key=lambda p: len(p.parts), reverse=True):
                _remove_target(root / target)

        for info in zf.infolist():
            dest = _member_destination(root, info.filename)
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, dest.open("wb") as dst:
                shutil.copyfileobj(src, dst)

    return root


def _redacted_config_text(cfg_path: Path) -> str:
    if not cfg_path.exists():
        return "# config.toml missing\n"
    return _redact_config_text(cfg_path.read_text(encoding="utf-8", errors="replace"))


def _snapshot_sqlite_db(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(str(src)) if src.exists() else sqlite3.connect(":memory:")
    try:
        dst_conn = sqlite3.connect(str(dst))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def _analysis_rows_jsonl(db_path: Path) -> str:
    query = (
        "SELECT id, capture_id, summary, ocr_text, entities_json, llm_provider, llm_model, created_at "
        "FROM analyses ORDER BY id"
    )
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'analyses'"
            ).fetchone()
            if not exists:
                return ""
            lines = [
                json.dumps(dict(row), ensure_ascii=False)
                for row in conn.execute(query)
            ]
            return "\n".join(lines) + ("\n" if lines else "")
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return ""


def _write_tree(zf: zipfile.ZipFile, src_dir: Path, prefix: str) -> None:
    if not src_dir.exists():
        return
    for path in sorted(src_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src_dir)
        arcname = PurePosixPath(prefix, *rel.parts).as_posix()
        zf.write(path, arcname)


def _top_level_target(name: str) -> Path:
    rel = _archive_relative_path(name)
    if len(rel.parts) <= 1:
        return Path(*rel.parts)
    return Path(rel.parts[0])


def _member_destination(root: Path, name: str) -> Path:
    rel = _archive_relative_path(name)
    dest = (root / Path(*rel.parts)).resolve()
    root_resolved = root.resolve()
    if not dest.is_relative_to(root_resolved):
        raise ValueError(f"Archive member escapes destination: {name}")
    return dest


def _archive_relative_path(name: str) -> PurePosixPath:
    rel = PurePosixPath(name)
    if rel.is_absolute() or any(part == ".." for part in rel.parts):
        raise ValueError(f"Unsafe archive member: {name}")
    if not any(name == prefix.rstrip("/") or name.startswith(prefix) for prefix in _ARCHIVE_PREFIXES):
        raise ValueError(f"Unsupported archive member: {name}")
    return rel


def _remove_target(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
