from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .hashing import hash_file

# Written by status_file.py directly into the music root; never treated as
# a library file so it's not diffed/transferred like a track would be.
STATUS_FILENAME = ".rekordbox-sync-status.json"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    relative_path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    hash TEXT NOT NULL,
    last_indexed_at REAL NOT NULL
)
"""


@dataclass(frozen=True)
class FileEntry:
    relative_path: str
    size: int
    mtime: float
    hash: str


@dataclass(frozen=True)
class Diff:
    added: list[str]
    changed: list[str]
    removed: list[str]

    @property
    def to_transfer(self) -> list[str]:
        return [*self.added, *self.changed]


def _connect(index_db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(index_db_path)
    conn.execute(_SCHEMA)
    return conn


def build_index(root: Path, index_db_path: Path) -> dict[str, FileEntry]:
    """Scan `root` and update the on-disk index at `index_db_path`.

    Files whose size and mtime are unchanged since the last scan are not
    re-hashed, so repeat scans of large libraries stay fast. Returns the
    resulting manifest.
    """
    root = Path(root)
    conn = _connect(index_db_path)
    try:
        existing: dict[str, FileEntry] = {
            row[0]: FileEntry(row[0], row[1], row[2], row[3])
            for row in conn.execute("SELECT relative_path, size, mtime, hash FROM files")
        }

        seen: set[str] = set()
        now = time.time()
        for path in root.rglob("*"):
            if not path.is_file() or path.name == STATUS_FILENAME:
                continue
            rel = path.relative_to(root).as_posix()
            seen.add(rel)
            stat = path.stat()
            size, mtime = stat.st_size, stat.st_mtime

            prior = existing.get(rel)
            if prior is not None and prior.size == size and prior.mtime == mtime:
                continue  # unchanged: reuse existing hash, no write needed

            digest = hash_file(path)
            conn.execute(
                "INSERT INTO files (relative_path, size, mtime, hash, last_indexed_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(relative_path) DO UPDATE SET "
                "size=excluded.size, mtime=excluded.mtime, hash=excluded.hash, "
                "last_indexed_at=excluded.last_indexed_at",
                (rel, size, mtime, digest, now),
            )
            existing[rel] = FileEntry(rel, size, mtime, digest)

        stale = set(existing) - seen
        if stale:
            conn.executemany(
                "DELETE FROM files WHERE relative_path = ?", [(rel,) for rel in stale]
            )
            for rel in stale:
                del existing[rel]

        conn.commit()
        return existing
    finally:
        conn.close()


def load_manifest(index_db_path: Path) -> dict[str, FileEntry]:
    conn = _connect(index_db_path)
    try:
        return {
            row[0]: FileEntry(row[0], row[1], row[2], row[3])
            for row in conn.execute("SELECT relative_path, size, mtime, hash FROM files")
        }
    finally:
        conn.close()


def diff_manifests(
    source: dict[str, FileEntry], dest: dict[str, FileEntry]
) -> Diff:
    """Compute what's needed to make `dest` match `source`."""
    added = [rel for rel in source if rel not in dest]
    changed = [
        rel for rel in source if rel in dest and source[rel].hash != dest[rel].hash
    ]
    removed = [rel for rel in dest if rel not in source]
    return Diff(added=added, changed=changed, removed=removed)
