from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from . import config as config_mod
from . import index as index_mod
from . import process_guard
from . import rekordbox_db as rekordbox_db_mod
from . import status_file as status_file_mod
from . import transfer as transfer_mod

Logger = Callable[[str], None]

EXAMPLE_CONFIG = Path(__file__).resolve().parents[2] / "config.example.yaml"


def index_dir(config_path: Path) -> Path:
    d = config_path.parent / ".rekordbox-sync"
    d.mkdir(exist_ok=True)
    return d


def init_config(config_path: Path, log: Logger) -> None:
    if config_path.exists():
        log(f"{config_path} already exists, leaving it as-is.")
        return
    shutil.copy(EXAMPLE_CONFIG, config_path)
    log(f"Created {config_path}. Edit it before running other actions.")


def reindex(cfg: config_mod.Config, config_path: Path) -> dict[str, index_mod.FileEntry]:
    index_path = index_dir(config_path) / "music.index.sqlite3"
    return index_mod.build_index(cfg.local.music_root, index_path)


def publish_status(cfg: config_mod.Config, config_path: Path, log: Logger) -> None:
    """Refresh this machine's index and publish its status (Rekordbox
    running? current file manifest) into its own music folder, where the
    peer can read it through the share path they've configured to reach us.
    No network listener involved — the peer just needs filesystem access to
    our music folder."""
    rekordbox_running = process_guard.is_rekordbox_running()
    manifest = reindex(cfg, config_path)
    status_file_mod.write_status(cfg.local.music_root, rekordbox_running, manifest)
    log(
        f"Published status: {len(manifest)} files indexed, "
        f"rekordbox_running={rekordbox_running}."
    )


def _read_peer_status(cfg: config_mod.Config, log: Logger) -> status_file_mod.PeerStatus:
    peer_status = status_file_mod.read_status(cfg.remote.music_share)
    if peer_status.is_stale:
        minutes = int(peer_status.age_seconds // 60)
        log(
            f"WARNING: peer's published status is {minutes} min old. "
            "Run 'publish' on the peer first if you want an up-to-date check."
        )
    return peer_status


def _apply_sync_direction(
    diff: index_mod.Diff,
    music_source: Path,
    music_dest: Path,
    rekordbox_source_dir: Path,
    rekordbox_dest_dir: Path,
    old_root: str,
    new_root: str,
    log: Logger,
) -> None:
    """Copy the music diff and the (path-remapped) Rekordbox data directory
    from source to dest. Used for both push and pull with source/dest
    swapped, since the two directions differ only in which side is local."""
    transfer_mod.apply_diff(diff, music_source, music_dest)

    staged_dir = rekordbox_db_mod.stage_remapped_rekordbox_dir(
        rekordbox_source_dir, old_root, new_root
    )
    try:
        backup = rekordbox_db_mod.backup_master_db(rekordbox_dest_dir / "master.db")
        if backup:
            log(f"Backed up previous master.db to {backup}")
        shutil.copytree(staged_dir, rekordbox_dest_dir, dirs_exist_ok=True)
    finally:
        shutil.rmtree(staged_dir.parent, ignore_errors=True)


def run_sync(
    cfg: config_mod.Config,
    config_path: Path,
    direction: str,
    dry_run: bool,
    log: Logger,
) -> None:
    """Synchronize the music folder and Rekordbox library with the peer.

    One-directional only: 'push' sends this machine's state to the peer,
    'pull' brings the peer's state to this machine. The peer must have run
    `publish_status` / `rekordbox-sync publish` at least once so their
    status file exists on their share. Raises RuntimeError if either side
    has Rekordbox running.
    """
    process_guard.ensure_rekordbox_stopped()

    local_manifest = reindex(cfg, config_path)
    status_file_mod.write_status(cfg.local.music_root, False, local_manifest)

    peer_status = _read_peer_status(cfg, log)

    if peer_status.rekordbox_running:
        raise RuntimeError("Peer reports Rekordbox is still running there. Aborting.")

    if direction == "push":
        diff = index_mod.diff_manifests(local_manifest, peer_status.manifest)
        log(
            f"push: {len(diff.added)} new, {len(diff.changed)} changed, "
            f"{len(diff.removed)} to remove on peer"
        )
        if dry_run:
            return

        _apply_sync_direction(
            diff,
            music_source=cfg.local.music_root,
            music_dest=cfg.remote.music_share,
            rekordbox_source_dir=cfg.local.rekordbox_data_dir,
            rekordbox_dest_dir=cfg.remote.rekordbox_share,
            old_root=str(cfg.local.music_root),
            new_root=cfg.remote.music_root,
            log=log,
        )
        log("Push complete.")
    else:
        diff = index_mod.diff_manifests(peer_status.manifest, local_manifest)
        log(
            f"pull: {len(diff.added)} new, {len(diff.changed)} changed, "
            f"{len(diff.removed)} to remove locally"
        )
        if dry_run:
            return

        _apply_sync_direction(
            diff,
            music_source=cfg.remote.music_share,
            music_dest=cfg.local.music_root,
            rekordbox_source_dir=cfg.remote.rekordbox_share,
            rekordbox_dest_dir=cfg.local.rekordbox_data_dir,
            old_root=cfg.remote.music_root,
            new_root=str(cfg.local.music_root),
            log=log,
        )
        reindex(cfg, config_path)
        log("Pull complete.")
