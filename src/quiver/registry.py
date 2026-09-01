"""SQLite registry of managed AppImages plus update history.

The registry is the single source of truth for what IS managed. Anything not
in here is invisible to all mutating commands.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quiver import paths
from quiver.errors import AimError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS apps (
    alias TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    original_path TEXT,
    app_id TEXT,
    version TEXT,
    arch TEXT,
    description TEXT,
    homepage TEXT,
    exec_args TEXT NOT NULL DEFAULT '[]',
    categories TEXT NOT NULL DEFAULT '[]',
    desktop_file TEXT,
    icon_path TEXT,
    integrated INTEGER NOT NULL DEFAULT 0,
    autoupdate TEXT NOT NULL DEFAULT 'manual',
    source_type TEXT,
    source_repo TEXT,
    source_opts TEXT NOT NULL DEFAULT '{}',
    notes TEXT,
    sha256 TEXT,
    size INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_check_at TEXT,
    last_check_result TEXT
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias TEXT NOT NULL,
    action TEXT NOT NULL,
    version TEXT,
    path TEXT NOT NULL,
    sha256 TEXT,
    size INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_alias ON history(alias);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_LIST_COLUMNS = "exec_args", "categories", "source_opts", "last_check_result"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class AppEntry:
    alias: str
    name: str
    path: str
    original_path: str | None = None
    app_id: str | None = None
    version: str | None = None
    arch: str | None = None
    description: str | None = None
    homepage: str | None = None
    exec_args: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    desktop_file: str | None = None
    icon_path: str | None = None
    integrated: bool = False
    autoupdate: str = "manual"  # manual | off
    source_type: str | None = None
    source_repo: str | None = None
    source_opts: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None
    sha256: str | None = None
    size: int | None = None
    created_at: str = ""
    updated_at: str = ""
    last_check_at: str | None = None
    last_check_result: dict[str, Any] | None = None

    @property
    def source_configured(self) -> bool:
        return bool(self.source_type and self.source_repo)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HistoryEntry:
    id: int
    alias: str
    action: str
    version: str | None
    path: str
    sha256: str | None
    size: int | None
    created_at: str


def _entry_from_row(row: sqlite3.Row) -> AppEntry:
    data = dict(row)
    for col in _LIST_COLUMNS:
        try:
            data[col] = json.loads(data[col] or ("{}" if col == "source_opts" else "[]"))
        except json.JSONDecodeError:
            data[col] = {} if col == "source_opts" else []
    data["integrated"] = bool(data.get("integrated"))
    valid = {f.name for f in fields(AppEntry)}
    return AppEntry(**{k: v for k, v in data.items() if k in valid})


class Registry:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or paths.app_state_dir() / "registry.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        self.conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1')")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---- apps ------------------------------------------------------------
    def add(self, entry: AppEntry) -> AppEntry:
        if self.get(entry.alias) is not None:
            raise AimError(f"alias {entry.alias!r} is already registered")
        now = _now()
        entry.created_at = entry.created_at or now
        entry.updated_at = now
        cols = {f.name for f in fields(AppEntry)} - {"created_at", "updated_at"}
        payload = {"created_at": entry.created_at, "updated_at": entry.updated_at}
        for name in cols:
            value = getattr(entry, name)
            if name in _LIST_COLUMNS or name == "last_check_result":
                value = json.dumps(value)
            if name == "integrated":
                value = int(value)
            payload[name] = value
        placeholders = ", ".join(f":{k}" for k in payload)
        columns = ", ".join(payload)
        self.conn.execute(f"INSERT INTO apps ({columns}) VALUES ({placeholders})", payload)
        self.conn.commit()
        return entry

    def get(self, alias: str) -> AppEntry | None:
        row = self.conn.execute("SELECT * FROM apps WHERE alias = ?", (alias,)).fetchone()
        return _entry_from_row(row) if row else None

    def require(self, alias: str) -> AppEntry:
        entry = self.get(alias)
        if entry is None:
            from quiver.errors import NotFoundError

            raise NotFoundError(
                f"no managed app with alias {alias!r}",
                hint="Run `quiver list` to see registered aliases.",
            )
        return entry

    def find_by_path(self, path: str | Path) -> AppEntry | None:
        target = str(Path(path).resolve())
        for entry in self.all():
            if str(Path(entry.path).resolve()) == target:
                return entry
        return None

    def all(self) -> list[AppEntry]:
        rows = self.conn.execute("SELECT * FROM apps ORDER BY name COLLATE NOCASE").fetchall()
        return [_entry_from_row(r) for r in rows]

    def update(self, alias: str, **changes: Any) -> AppEntry:
        entry = self.require(alias)
        invalid = set(changes) - {f.name for f in fields(AppEntry)}
        if invalid:
            raise AimError(f"unknown registry fields: {sorted(invalid)}")
        changes.setdefault("updated_at", _now())
        sets: list[str] = []
        payload: dict[str, Any] = {"alias_where": alias}
        for key, value in changes.items():
            if key in _LIST_COLUMNS or key == "last_check_result":
                value = json.dumps(value)
            if key == "integrated":
                value = int(value)
            sets.append(f"{key} = :{key}")
            payload[key] = value
        self.conn.execute(f"UPDATE apps SET {', '.join(sets)} WHERE alias = :alias_where", payload)
        self.conn.commit()
        updated = self.get(alias)
        assert updated is not None and entry is not None
        return updated

    def remove(self, alias: str, *, with_history: bool = True) -> None:
        self.require(alias)
        self.conn.execute("DELETE FROM apps WHERE alias = ?", (alias,))
        if with_history:
            self.conn.execute("DELETE FROM history WHERE alias = ?", (alias,))
        self.conn.commit()

    def aliases(self) -> set[str]:
        return {row[0] for row in self.conn.execute("SELECT alias FROM apps")}

    # ---- history -----------------------------------------------------------
    def add_history(
        self,
        alias: str,
        *,
        action: str,
        path: str,
        version: str | None = None,
        sha256: str | None = None,
        size: int | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO history (alias, action, version, path, sha256, size, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (alias, action, version, path, sha256, size, _now()),
        )
        self.conn.commit()

    def history(self, alias: str) -> list[HistoryEntry]:
        rows = self.conn.execute(
            "SELECT * FROM history WHERE alias = ? ORDER BY id DESC", (alias,)
        ).fetchall()
        return [
            HistoryEntry(
                id=int(r["id"]),
                alias=r["alias"],
                action=r["action"],
                version=r["version"],
                path=r["path"],
                sha256=r["sha256"],
                size=r["size"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def prune_history(self, alias: str, keep: int) -> list[HistoryEntry]:
        """Drop oldest history rows beyond ``keep``; returns removed rows."""
        rows = self.history(alias)
        removed = rows[keep:]
        for row in removed:
            self.conn.execute("DELETE FROM history WHERE id = ?", (row.id,))
        self.conn.commit()
        return removed

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM apps").fetchone()[0])
