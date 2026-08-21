import time
from pathlib import Path

import pytest

from rekordbox_sync.index import FileEntry
from rekordbox_sync.status_file import read_status, write_status


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    music_root = tmp_path / "music"
    music_root.mkdir()
    manifest = {"a.mp3": FileEntry("a.mp3", 5, 123.0, "hash-a")}

    write_status(music_root, rekordbox_running=True, manifest=manifest)
    status = read_status(music_root)

    assert status.rekordbox_running is True
    assert status.manifest["a.mp3"].hash == "hash-a"
    assert not status.is_stale


def test_read_status_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_status(tmp_path / "no_status_here")


def test_is_stale_reflects_age(tmp_path: Path) -> None:
    music_root = tmp_path / "music"
    music_root.mkdir()
    write_status(music_root, rekordbox_running=False, manifest={})

    status = read_status(music_root)
    status.published_at = time.time() - 3600  # pretend it was published an hour ago

    assert status.is_stale
