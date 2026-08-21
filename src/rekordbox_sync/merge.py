from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .index import FileEntry


@dataclass(frozen=True)
class MergePlan:
    to_peer: list[str]
    to_local: list[str]
    conflicts: list[str]  # subset of to_peer/to_local resolved by last-write-wins


def plan_file_merge(
    local: dict[str, FileEntry], peer: dict[str, FileEntry]
) -> MergePlan:
    """Two-way union merge: a file missing on one side is copied over, and a
    file that differs on both sides is resolved by last-write-wins (newer
    mtime). Never deletes — a file present on only one side is always
    treated as "new", never as "the other side deleted it"."""
    to_peer: list[str] = []
    to_local: list[str] = []
    conflicts: list[str] = []

    for rel in sorted(set(local) | set(peer)):
        l = local.get(rel)
        p = peer.get(rel)
        if l is None:
            to_local.append(rel)
        elif p is None:
            to_peer.append(rel)
        elif l.hash != p.hash:
            conflicts.append(rel)
            if l.mtime >= p.mtime:
                to_peer.append(rel)
            else:
                to_local.append(rel)
        # else: identical content on both sides, nothing to do

    return MergePlan(to_peer=to_peer, to_local=to_local, conflicts=conflicts)


def apply_file_merge(
    plan: MergePlan, local_root: Path, peer_share: Path, dry_run: bool = False
) -> None:
    local_root = Path(local_root)
    peer_share = Path(peer_share)

    for rel in plan.to_peer:
        if dry_run:
            continue
        dst = peer_share / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_root / rel, dst)

    for rel in plan.to_local:
        if dry_run:
            continue
        dst = local_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(peer_share / rel, dst)
