from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from pyrekordbox import Rekordbox6Database


def backup_master_db(db_path: Path) -> Path | None:
    """Copy `master.db` into a timestamped backup next to it, so a sync in
    the wrong direction can be recovered from. Returns None if `db_path`
    doesn't exist yet (e.g. first sync to a fresh machine).
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"master.db.{stamp}.bak"
    shutil.copy2(db_path, backup_path)
    return backup_path


def remap_track_paths(db_path: Path, old_root: str, new_root: str) -> int:
    """Rewrite every track's absolute path from `old_root` to `new_root` in
    place, in both the DjmdContent table and the corresponding ANLZ analysis
    files.

    `check_path=False` is required: the rewritten path is only valid on the
    *destination* machine, which generally does not exist on the machine
    running this rewrite. `db_path` must live inside a full copy of the
    Rekordbox data directory (its `share/` subfolder must sit next to it),
    since that's where the ANLZ files pyrekordbox also updates are found.
    """
    old_root = old_root.replace("\\", "/").rstrip("/")
    new_root = new_root.replace("\\", "/").rstrip("/")

    db = Rekordbox6Database(path=str(db_path))
    try:
        changed = 0
        for content in db.get_content():
            folder_path = content.FolderPath
            if folder_path and folder_path.startswith(old_root + "/"):
                new_path = new_root + folder_path[len(old_root) :]
                db.update_content_path(
                    content, new_path, check_path=False, save=True, commit=False
                )
                changed += 1
        db.commit()
        return changed
    finally:
        db.close()


def stage_remapped_rekordbox_dir(source_dir: Path, old_root: str, new_root: str) -> Path:
    """Copy the whole Rekordbox data directory into a temp staging area and
    rewrite track paths there, leaving the original untouched. Returns the
    path to the staged directory; the caller is responsible for cleaning it
    up (e.g. `shutil.rmtree(staged.parent)`) once it's been copied to the
    destination.
    """
    source_dir = Path(source_dir)
    staging_parent = Path(tempfile.mkdtemp(prefix="rekordbox_sync_"))
    staged_dir = staging_parent / source_dir.name
    shutil.copytree(source_dir, staged_dir)
    remap_track_paths(staged_dir / "master.db", old_root, new_root)
    return staged_dir
