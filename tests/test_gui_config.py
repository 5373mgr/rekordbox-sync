from pathlib import Path

from rekordbox_sync.gui import _load_raw, _save_raw


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    values = {
        "local_music_root": "D:/DJ Itunes",
        "local_rekordbox_data_dir": "",
        "remote_music_root": "/Users/foo/Music/DJ",
        "remote_music_share": "//100.1.2.3/DJ Itunes",
        "remote_rekordbox_share": "//100.1.2.3/rekordbox-data",
    }

    _save_raw(config_path, values)
    loaded = _load_raw(config_path)

    assert loaded == values


def test_load_raw_falls_back_to_example_when_missing(tmp_path: Path) -> None:
    values = _load_raw(tmp_path / "does_not_exist.yaml")

    assert values["local_music_root"]  # populated from config.example.yaml
    assert "remote_host" not in values
