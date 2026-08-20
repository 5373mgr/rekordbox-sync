from __future__ import annotations

import shutil
from pathlib import Path


def relocate_into_root(source: Path, root: Path) -> None:
    """One-time move of everything under `source` into `root`.

    Used during initial setup so both machines end up with an identical
    relative folder structure under their configured music root, which is
    what makes the later path-prefix rewrite in master.db (see
    rekordbox_db.remap_track_paths) reliable instead of needing to handle
    arbitrary, divergent folder layouts.
    """
    source = Path(source).resolve()
    root = Path(root).resolve()
    if source == root:
        return

    root.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        dest = root / item.name
        if dest.exists():
            raise FileExistsError(
                f"Cannot relocate: '{dest}' already exists under the target root."
            )
        shutil.move(str(item), str(dest))
