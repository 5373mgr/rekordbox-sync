from pathlib import Path

from rekordbox_sync.index import FileEntry
from rekordbox_sync.merge import apply_file_merge, plan_file_merge


def test_plan_file_merge_unions_one_sided_additions() -> None:
    local = {"a.mp3": FileEntry("a.mp3", 1, 1.0, "hash-a")}
    peer = {"b.mp3": FileEntry("b.mp3", 1, 1.0, "hash-b")}

    plan = plan_file_merge(local, peer)

    assert plan.to_peer == ["a.mp3"]
    assert plan.to_local == ["b.mp3"]
    assert plan.conflicts == []


def test_plan_file_merge_skips_identical_content() -> None:
    local = {"a.mp3": FileEntry("a.mp3", 1, 1.0, "same-hash")}
    peer = {"a.mp3": FileEntry("a.mp3", 1, 2.0, "same-hash")}

    plan = plan_file_merge(local, peer)

    assert plan.to_peer == []
    assert plan.to_local == []
    assert plan.conflicts == []


def test_plan_file_merge_resolves_conflict_by_newer_mtime() -> None:
    local = {"a.mp3": FileEntry("a.mp3", 1, 200.0, "hash-local")}
    peer = {"a.mp3": FileEntry("a.mp3", 1, 100.0, "hash-peer")}

    plan = plan_file_merge(local, peer)

    assert plan.to_peer == ["a.mp3"]  # local is newer, wins
    assert plan.to_local == []
    assert plan.conflicts == ["a.mp3"]


def test_apply_file_merge_copies_both_directions(tmp_path: Path) -> None:
    local_root = tmp_path / "local"
    peer_share = tmp_path / "peer"
    local_root.mkdir()
    peer_share.mkdir()
    (local_root / "a.mp3").write_bytes(b"from local")
    (peer_share / "b.mp3").write_bytes(b"from peer")

    local = {"a.mp3": FileEntry("a.mp3", 10, 1.0, "hash-a")}
    peer = {"b.mp3": FileEntry("b.mp3", 10, 1.0, "hash-b")}
    plan = plan_file_merge(local, peer)

    apply_file_merge(plan, local_root, peer_share)

    assert (peer_share / "a.mp3").read_bytes() == b"from local"
    assert (local_root / "b.mp3").read_bytes() == b"from peer"


def test_apply_file_merge_dry_run_copies_nothing(tmp_path: Path) -> None:
    local_root = tmp_path / "local"
    peer_share = tmp_path / "peer"
    local_root.mkdir()
    peer_share.mkdir()
    (local_root / "a.mp3").write_bytes(b"from local")

    plan = plan_file_merge(
        {"a.mp3": FileEntry("a.mp3", 10, 1.0, "hash-a")}, {}
    )

    apply_file_merge(plan, local_root, peer_share, dry_run=True)

    assert not (peer_share / "a.mp3").exists()
