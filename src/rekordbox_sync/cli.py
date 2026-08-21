from __future__ import annotations

import sys
from pathlib import Path

import click

from . import config as config_mod
from . import orchestrator
from . import process_guard
from . import relocate as relocate_mod


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
    orchestrator.init_config(ctx.obj["config_path"], click.echo)


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
    manifest = orchestrator.reindex(cfg, ctx.obj["config_path"])
    click.echo(f"Indexed {len(manifest)} files under {cfg.local.music_root}")


@main.command()
@click.pass_context
def publish(ctx: click.Context) -> None:
    """Reindex the music folder and publish this machine's status (a small
    file written into the music folder itself) for the peer to read.

    Run this on the machine you're about to pull from, or push to, before
    running `sync` on the other side. No network port involved — the peer
    reads this status through the share path they've configured to reach
    this machine.
    """
    cfg = config_mod.load_config(ctx.obj["config_path"])
    orchestrator.publish_status(cfg, ctx.obj["config_path"], click.echo)


@main.command()
@click.option("--direction", type=click.Choice(["push", "pull"]), required=True)
@click.option("--dry-run", is_flag=True, default=False)
@click.pass_context
def sync(ctx: click.Context, direction: str, dry_run: bool) -> None:
    """Synchronize the music folder and Rekordbox library with the peer.

    One-directional only: 'push' sends this machine's state to the peer,
    'pull' brings the peer's state to this machine. Run `publish` on the
    other machine first. Requires the peer's shares (remote.music_share,
    remote.rekordbox_share) to already be reachable on the filesystem.
    """
    cfg = config_mod.load_config(ctx.obj["config_path"])
    try:
        orchestrator.run_sync(cfg, ctx.obj["config_path"], direction, dry_run, click.echo)
    except RuntimeError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)


@main.command()
@click.option("--dry-run", is_flag=True, default=False)
@click.pass_context
def merge(ctx: click.Context, dry_run: bool) -> None:
    """Two-way merge with the peer: union new files/tracks/playlists onto
    both sides, resolving same-path conflicts by last-write-wins. Never
    deletes anything on either side. Mutates both machines' master.db (both
    are backed up first). Run `publish` on the other machine first.
    """
    cfg = config_mod.load_config(ctx.obj["config_path"])
    try:
        orchestrator.run_merge(cfg, ctx.obj["config_path"], dry_run, click.echo)
    except RuntimeError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
