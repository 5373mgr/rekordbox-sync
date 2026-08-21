from pathlib import Path

from rekordbox_sync.index import STATUS_FILENAME, build_index, diff_manifests, load_manifest


def test_build_index_finds_files(tmp_path: Path) -> None:
    root = tmp_path / "music"
    root.mkdir()
    (root / "a.mp3").write_bytes(b"hello")
    (root / "sub").mkdir()
    (root / "sub" / "b.mp3").write_bytes(b"world")

    db_path = tmp_path / "index.sqlite3"
    manifest = build_index(root, db_path)

    assert set(manifest) == {"a.mp3", "sub/b.mp3"}
    assert manifest["a.mp3"].size == 5


def test_build_index_skips_rehash_when_unchanged(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "music"
    root.mkdir()
    f = root / "a.mp3"
    f.write_bytes(b"hello")
    db_path = tmp_path / "index.sqlite3"

    build_index(root, db_path)
    first = load_manifest(db_path)["a.mp3"].hash

    calls = []
    import rekordbox_sync.index as index_mod

    original = index_mod.hash_file

    def spy(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(index_mod, "hash_file", spy)
    build_index(root, db_path)

    assert calls == []  # unchanged file: no re-hash
    assert load_manifest(db_path)["a.mp3"].hash == first


def test_build_index_removes_deleted_files(tmp_path: Path) -> None:
    root = tmp_path / "music"
    root.mkdir()
    f = root / "a.mp3"
    f.write_bytes(b"hello")
    db_path = tmp_path / "index.sqlite3"

    build_index(root, db_path)
    f.unlink()
    manifest = build_index(root, db_path)

    assert manifest == {}


def test_build_index_ignores_status_file(tmp_path: Path) -> None:
    root = tmp_path / "music"
    root.mkdir()
    (root / "a.mp3").write_bytes(b"hello")
    (root / STATUS_FILENAME).write_text("{}")

    db_path = tmp_path / "index.sqlite3"
    manifest = build_index(root, db_path)

    assert set(manifest) == {"a.mp3"}


def test_diff_manifests() -> None:
    from rekordbox_sync.index import FileEntry

    source = {
        "new.mp3": FileEntry("new.mp3", 1, 1.0, "h1"),
        "same.mp3": FileEntry("same.mp3", 1, 1.0, "h2"),
        "changed.mp3": FileEntry("changed.mp3", 1, 1.0, "h3-new"),
    }
    dest = {
        "same.mp3": FileEntry("same.mp3", 1, 1.0, "h2"),
        "changed.mp3": FileEntry("changed.mp3", 1, 1.0, "h3-old"),
        "gone.mp3": FileEntry("gone.mp3", 1, 1.0, "h4"),
    }

    diff = diff_manifests(source, dest)

    assert diff.added == ["new.mp3"]
    assert diff.changed == ["changed.mp3"]
    assert diff.removed == ["gone.mp3"]
    assert set(diff.to_transfer) == {"new.mp3", "changed.mp3"}
