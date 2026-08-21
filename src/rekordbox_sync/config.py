from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path

import yaml


def default_rekordbox_data_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        import os

        appdata = os.environ["APPDATA"]
        return Path(appdata) / "Pioneer" / "rekordbox"
    if system == "Darwin":
        return Path.home() / "Library" / "Pioneer" / "rekordbox"
    raise RuntimeError(f"Unsupported OS: {system}")


@dataclass
class LocalConfig:
    music_root: Path
    rekordbox_data_dir: Path


@dataclass
class RemoteConfig:
    music_root: str  # kept as string: it's a path on the *other* machine's OS
    music_share: Path  # how this machine reaches the peer's music folder
    rekordbox_share: Path  # how this machine reaches the peer's rekordbox data folder


@dataclass
class Config:
    local: LocalConfig
    remote: RemoteConfig

    @property
    def rekordbox_db_path(self) -> Path:
        return self.local.rekordbox_data_dir / "master.db"


def load_config(path: Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config.example.yaml to config.yaml first."
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    local_raw = raw["local"]
    rekordbox_data_dir = local_raw.get("rekordbox_data_dir")
    local = LocalConfig(
        music_root=Path(local_raw["music_root"]),
        rekordbox_data_dir=(
            Path(rekordbox_data_dir) if rekordbox_data_dir else default_rekordbox_data_dir()
        ),
    )

    remote_raw = raw["remote"]
    remote = RemoteConfig(
        music_root=remote_raw["music_root"],
        music_share=Path(remote_raw["music_share"]),
        rekordbox_share=Path(remote_raw["rekordbox_share"]),
    )

    return Config(local=local, remote=remote)
