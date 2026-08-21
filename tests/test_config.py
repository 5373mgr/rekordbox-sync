from pathlib import Path

import pytest

from rekordbox_sync.config import load_config


def _write_config(path: Path, rekordbox_data_dir: Path | None) -> None:
    rekordbox_data_dir_yaml = (
        f"'{rekordbox_data_dir.as_posix()}'" if rekordbox_data_dir else "null"
    )
    path.write_text(
        f"""
local:
  music_root: '{(path.parent / "music").as_posix()}'
  rekordbox_data_dir: {rekordbox_data_dir_yaml}

remote:
  music_root: "/Users/foo/Music/DJ"
  music_share: '{(path.parent / "share_music").as_posix()}'
  rekordbox_share: '{(path.parent / "share_rekordbox").as_posix()}'
""",
        encoding="utf-8",
    )


def test_load_config_with_explicit_rekordbox_dir(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    rb_dir = tmp_path / "rekordbox_data"
    _write_config(config_path, rb_dir)

    cfg = load_config(config_path)

    assert cfg.local.music_root == tmp_path / "music"
    assert cfg.local.rekordbox_data_dir == rb_dir
    assert cfg.remote.music_root == "/Users/foo/Music/DJ"
    assert cfg.rekordbox_db_path == cfg.local.rekordbox_data_dir / "master.db"


def test_load_config_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "does_not_exist.yaml")
