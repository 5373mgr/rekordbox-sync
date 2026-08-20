from __future__ import annotations

import shutil
from pathlib import Path

from .index import Diff


def apply_diff(
    diff: Diff,
    source_root: Path,
    dest_root: Path,
    delete_removed: bool = True,
    dry_run: bool = False,
) -> None:
    """Copy the added/changed files from `source_root` to `dest_root`,
    and optionally delete files at `dest_root` that no longer exist in the
    source (making `dest_root` mirror `source_root`).
    """
    source_root = Path(source_root)
    dest_root = Path(dest_root)

    for rel in diff.to_transfer:
        src = source_root / rel
        dst = dest_root / rel
        if dry_run:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    if delete_removed:
        for rel in diff.removed:
            dst = dest_root / rel
            if dry_run:
                continue
            if dst.exists():
                dst.unlink()
