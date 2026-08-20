from pathlib import Path

from rekordbox_sync.hashing import hash_file


def test_hash_file_is_deterministic(tmp_path: Path) -> None:
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello world" * 1000)
    assert hash_file(f) == hash_file(f)


def test_hash_file_differs_for_different_content(tmp_path: Path) -> None:
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"hello")
    b.write_bytes(b"world")
    assert hash_file(a) != hash_file(b)
