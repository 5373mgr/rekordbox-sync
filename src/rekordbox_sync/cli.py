from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click

from . import config as config_mod
from . import handshake as handshake_mod
from . import index as index_mod
from . import process_guard
from . import rekordbox_db as rekordbox_db_mod
from . import relocate as relocate_mod
from . import transfer as transfer_mod

_EXAMPLE_CONFIG = Path(__file__).resolve().parents[2] / "config.example.yaml"


def _index_dir(config_path: Path) -> Path:
    d = config_path.parent / ".rekordbox-sync"
    d.mkdir(exist_ok=True)
    return d


def _apply_sync_direction(
    diff: index_mod.Diff,
    music_source: Path,
    music_dest: Path,
    rekordbox_source_dir: Path,
    rekordbox_dest_dir: Path,
    old_root: str,
    new_root: str,
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
            click.echo(f"Backed up previous master.db to {backup}")
        shutil.copytree(staged_dir, rekordbox_dest_dir, dirs_exist_ok=True)
    finally:
        shutil.rmtree(staged_dir.parent, ignore_errors=True)


@click.group()
@click.option(
    "--config",
    "config_path",
    default="config.yaml",
    type=click.Path(path_type=Path),
    help="Path to config.yaml",
)
@click.pass_context
def main(ctx: click.Context, config_path: Path) -> None:
    ctx.obj = {"config_path": config_path}


@main.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Create config.yaml from the example template if it doesn't exist yet."""
    config_path: Path = ctx.obj["config_path"]
    if config_path.exists():
        click.echo(f"{config_path} already exists, leaving it as-is.")
        return
    shutil.copy(_EXAMPLE_CONFIG, config_path)
    click.echo(f"Created {config_path}. Edit it before running other commands.")


@main.command("relocate")
@click.pass_context
def relocate_cmd(ctx: click.Context) -> None:
    """One-time move of the music folder's contents under the configured
    root, so both machines share an identical relative folder layout."""
    cfg = config_mod.load_config(ctx.obj["config_path"])
    click.echo(f"This will move files into {cfg.local.music_root}. Continue? [y/N]")
    if input().strip().lower() != "y":
        click.echo("Aborted.")
        return
    relocate_mod.relocate_into_root(cfg.local.music_root, cfg.local.music_root)
    click.echo("Done.")


@main.command("check-rekordbox")
def check_rekordbox() -> None:
    """Report whether Rekordbox is currently running on this machine."""
    running = process_guard.is_rekordbox_running()
    click.echo("running" if running else "not running")
    sys.exit(1 if running else 0)


@main.command()
@click.pass_context
def reindex(ctx: click.Context) -> None:
    """Rebuild the local file index for the music folder."""
    cfg = config_mod.load_config(ctx.obj["config_path"])
    index_path = _index_dir(ctx.obj["config_path"]) / "music.index.sqlite3"
    manifest = index_mod.build_index(cfg.local.music_root, index_path)
    click.echo(f"Indexed {len(manifest)} files under {cfg.local.music_root}")


@main.command()
@click.option("--port", type=int, default=None, help="Overrides remote.port as the listen port")
@click.pass_context
def listen(ctx: click.Context, port: int | None) -> None:
    """Wait for the peer to initiate a sync handshake against this machine.

    Run this on the machine that is *not* driving the sync (e.g. the peer
    being pulled from, or pushed to) before the other side runs `sync`.
    """
    cfg = config_mod.load_config(ctx.obj["config_path"])
    rekordbox_running = process_guard.is_rekordbox_running()
    index_path = _index_dir(ctx.obj["config_path"]) / "music.index.sqlite3"
    manifest = index_mod.build_index(cfg.local.music_root, index_path)
    status = handshake_mod.PeerStatus(rekordbox_running=rekordbox_running, manifest=manifest)
    listen_port = port or cfg.remote.port
    click.echo(f"Listening on 0.0.0.0:{listen_port} for a sync handshake...")
    peer_status = handshake_mod.serve_once(listen_port, status)
    click.echo(
        f"Handshake done. Peer has {len(peer_status.manifest)} files indexed, "
        f"rekordbox_running={peer_status.rekordbox_running}."
    )


@main.command()
@click.option("--direction", type=click.Choice(["push", "pull"]), required=True)
@click.option("--dry-run", is_flag=True, default=False)
@click.pass_context
def sync(ctx: click.Context, direction: str, dry_run: bool) -> None:
    """Synchronize the music folder and Rekordbox library with the peer.

    One-directional only: 'push' sends this machine's state to the peer,
    'pull' brings the peer's state to this machine. Run `listen` on the
    other machine first. Requires the peer's shares (remote.music_share,
    remote.rekordbox_share) to already be reachable on the filesystem.
    """
    cfg = config_mod.load_config(ctx.obj["config_path"])
    process_guard.ensure_rekordbox_stopped()

    index_path = _index_dir(ctx.obj["config_path"]) / "music.index.sqlite3"
    local_manifest = index_mod.build_index(cfg.local.music_root, index_path)
    local_status = handshake_mod.PeerStatus(rekordbox_running=False, manifest=local_manifest)

    click.echo(f"Contacting {cfg.remote.host}:{cfg.remote.port} ...")
    peer_status = handshake_mod.request(cfg.remote.host, cfg.remote.port, local_status)

    if peer_status.rekordbox_running:
        click.echo("Peer reports Rekordbox is still running there. Aborting.", err=True)
        sys.exit(1)

    if direction == "push":
        diff = index_mod.diff_manifests(local_manifest, peer_status.manifest)
        click.echo(
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
        )
        click.echo("Push complete.")
    else:
        diff = index_mod.diff_manifests(peer_status.manifest, local_manifest)
        click.echo(
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
        )
        index_mod.build_index(cfg.local.music_root, index_path)
        click.echo("Pull complete.")


if __name__ == "__main__":
    main()
