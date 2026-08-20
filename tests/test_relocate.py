from pathlib import Path

import pytest

from rekordbox_sync.relocate import relocate_into_root


def test_relocate_moves_files_into_root(tmp_path: Path) -> None:
    source = tmp_path / "old_location"
    source.mkdir()
    (source / "track.mp3").write_bytes(b"data")
    (source / "sub").mkdir()
    (source / "sub" / "other.mp3").write_bytes(b"data2")

    root = tmp_path / "new_root"

    relocate_into_root(source, root)

    assert (root / "track.mp3").exists()
    assert (root / "sub" / "other.mp3").exists()


def test_relocate_is_noop_when_already_at_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "track.mp3").write_bytes(b"data")

    relocate_into_root(root, root)

    assert (root / "track.mp3").exists()


def test_relocate_refuses_to_overwrite_existing(tmp_path: Path) -> None:
    source = tmp_path / "old_location"
    source.mkdir()
    (source / "track.mp3").write_bytes(b"data")

    root = tmp_path / "new_root"
    root.mkdir()
    (root / "track.mp3").write_bytes(b"already here")

    with pytest.raises(FileExistsError):
        relocate_into_root(source, root)
