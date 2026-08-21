from __future__ import annotations

import shutil
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

pyrekordbox = pytest.importorskip("pyrekordbox")
from pyrekordbox import Rekordbox6Database  # noqa: E402
from pyrekordbox.db6 import tables  # noqa: E402

from rekordbox_sync.rekordbox_merge import merge_playlists, merge_tracks  # noqa: E402


def _relax_not_null_constraints() -> None:
    """pyrekordbox's table definitions use `Mapped[str]` (not
    `Mapped[Optional[str]]`) for several columns that also declare
    `default=None`, so SQLAlchemy 2.0 infers NOT NULL from the type
    annotation while the convenience methods (e.g. add_content) still leave
    them unset. Against a real master.db this is moot -- the table already
    exists with whatever constraints Rekordbox itself created -- but our
    freshly `create_all()`-generated test schema would otherwise enforce a
    stricter constraint than production ever does. Non-primary-key columns
    are relaxed to nullable=True to match that real-world leniency."""
    for table in tables.Base.metadata.tables.values():
        for column in table.columns:
            if not column.primary_key:
                column.nullable = True


def _make_db(db_path: Path) -> Rekordbox6Database:
    """A schema-only, unencrypted Rekordbox DB for testing -- avoids needing
    a real SQLCipher-encrypted master.db just to exercise the merge logic."""
    db_path.touch()
    db = Rekordbox6Database(path=str(db_path), unlock=False)
    _relax_not_null_constraints()
    tables.Base.metadata.create_all(db.engine)
    device = tables.DjmdDevice.create(
        ID=str(uuid4()),
        MasterDBID=str(uuid4()),
        Name="Test",
        UUID=str(uuid4()),
        usn=0,
        rb_local_usn=0,
    )
    db.add(device)
    menu_item = tables.DjmdMenuItems.create(
        ID="1", Class=0, Name="TRACK", UUID=str(uuid4()), usn=0, rb_local_usn=0
    )
    db.add(menu_item)
    # pyrekordbox's own commit() bumps this counter; a real Rekordbox
    # install seeds it, our schema-only fixture needs to do it too.
    # pyrekordbox's DateTime column type crashes binding None (it calls
    # value.astimezone() unconditionally), so every DateTime field on any
    # row we create here needs an explicit value, not just the mixin ones.
    db.add(
        tables.AgentRegistry.create(
            registry_id="localUpdateCount",
            id_1="",
            id_2="",
            int_1=0,
            int_2=0,
            str_1="",
            str_2="",
            date_1=datetime.now(),
            date_2=datetime.now(),
            text_1="",
            text_2="",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
    )
    db.commit()
    return db


@pytest.fixture
def local_music(tmp_path: Path) -> Path:
    d = tmp_path / "local_music"
    d.mkdir()
    return d


@pytest.fixture
def peer_music(tmp_path: Path) -> Path:
    d = tmp_path / "peer_music"
    d.mkdir()
    return d


@pytest.fixture
def local_db(tmp_path: Path):
    db_dir = tmp_path / "local_rb"
    db_dir.mkdir()
    db = _make_db(db_dir / "master.db")
    yield db
    db.close()


@pytest.fixture
def peer_db(tmp_path: Path):
    db_dir = tmp_path / "peer_rb"
    db_dir.mkdir()
    db = _make_db(db_dir / "master.db")
    yield db
    db.close()


PEER_ROOT = "/Users/foo/Music/DJ"  # arbitrary stand-in for the peer's own OS path


def _seed_track(db, local_path: Path, os_path: str, **kwargs):
    """add_content needs a path it can actually stat(); tests simulating a
    track that "already exists on the peer" want its FolderPath to read as
    the peer's own (unreachable-from-here) OS path instead."""
    content = db.add_content(local_path, **kwargs)
    content.FolderPath = os_path
    return content


def test_merge_tracks_resolves_artist_and_genre_by_name(
    local_db, peer_db, local_music: Path, peer_music: Path
) -> None:
    (local_music / "tagged.mp3").write_bytes(b"audio data")
    (peer_music / "tagged.mp3").write_bytes(b"audio data")
    artist = local_db.add_artist(name="DJ Someone")
    genre = local_db.add_genre(name="Techno")
    local_db.add_content(
        local_music / "tagged.mp3",
        Title="Tagged Track",
        ArtistID=artist.ID,
        GenreID=genre.ID,
    )
    local_db.commit()

    merge_tracks(
        local_db, peer_db, str(local_music), PEER_ROOT, local_music, peer_music, log=lambda m: None
    )

    peer_content = peer_db.get_content(Title="Tagged Track").one()
    peer_artist = peer_db.get_artist(ID=peer_content.ArtistID)
    peer_genre = peer_db.get_genre(ID=peer_content.GenreID)
    assert peer_artist.Name == "DJ Someone"
    assert peer_genre.Name == "Techno"
    # Artist/genre IDs are per-database -- must not be copied verbatim.
    assert peer_artist.ID != artist.ID
    assert peer_genre.ID != genre.ID


def test_merge_tracks_adds_new_local_track_to_peer(
    local_db, peer_db, local_music: Path, peer_music: Path
) -> None:
    (local_music / "new.mp3").write_bytes(b"audio data")
    (peer_music / "new.mp3").write_bytes(b"audio data")  # file-merge already ran
    local_db.add_content(local_music / "new.mp3", Title="New Track", Rating=3)
    local_db.commit()

    stats = merge_tracks(
        local_db, peer_db, str(local_music), PEER_ROOT, local_music, peer_music, log=lambda m: None
    )

    assert stats.added_to_peer == 1
    assert stats.added_to_local == 0
    peer_content = peer_db.get_content(Title="New Track").one()
    assert peer_content.FolderPath == f"{PEER_ROOT}/new.mp3"
    assert peer_content.Rating == 3


def test_merge_tracks_adds_new_peer_track_to_local(
    local_db, peer_db, local_music: Path, peer_music: Path
) -> None:
    (peer_music / "fresh.mp3").write_bytes(b"audio data")
    (local_music / "fresh.mp3").write_bytes(b"audio data")  # file-merge already ran
    _seed_track(peer_db, peer_music / "fresh.mp3", f"{PEER_ROOT}/fresh.mp3", Title="Fresh Track")
    peer_db.commit()

    stats = merge_tracks(
        local_db, peer_db, str(local_music), PEER_ROOT, local_music, peer_music, log=lambda m: None
    )

    assert stats.added_to_local == 1
    local_content = local_db.get_content(Title="Fresh Track").one()
    assert local_content.FolderPath == str(local_music / "fresh.mp3").replace("\\", "/")


def test_merge_tracks_copies_cues_with_new_track(
    local_db, peer_db, local_music: Path, peer_music: Path
) -> None:
    (local_music / "cued.mp3").write_bytes(b"audio data")
    (peer_music / "cued.mp3").write_bytes(b"audio data")
    content = local_db.add_content(local_music / "cued.mp3", Title="Cued Track")
    local_db.commit()
    local_db.add(
        tables.DjmdCue.create(
            ID=str(uuid4()), ContentID=content.ID, InMsec=1000, Kind=0, ContentUUID=content.UUID,
            UUID=str(uuid4()),
        )
    )
    local_db.commit()

    merge_tracks(
        local_db, peer_db, str(local_music), PEER_ROOT, local_music, peer_music, log=lambda m: None
    )

    # Note: Rekordbox6Database.get_content_cue() queries the *different*
    # `ContentCue` table (a single Cues blob column pyrekordbox doesn't
    # decode), not `DjmdCue` (the per-point table our production code
    # reads/writes) -- query DjmdCue directly here to check the real result.
    peer_content = peer_db.get_content(Title="Cued Track").one()
    cues = peer_db.query(tables.DjmdCue).filter_by(ContentID=peer_content.ID).all()
    assert len(cues) == 1
    assert cues[0].InMsec == 1000


def test_merge_tracks_resolves_conflict_by_updated_at(
    local_db, peer_db, local_music: Path, peer_music: Path
) -> None:
    (local_music / "both.mp3").write_bytes(b"audio data")
    (peer_music / "both.mp3").write_bytes(b"audio data")

    peer_content = _seed_track(
        peer_db, peer_music / "both.mp3", f"{PEER_ROOT}/both.mp3", Title="Both", Rating=1
    )
    peer_db.commit()
    time.sleep(0.01)
    local_content = local_db.add_content(local_music / "both.mp3", Title="Both", Rating=5)
    local_db.commit()  # local row is newer

    stats = merge_tracks(
        local_db, peer_db, str(local_music), PEER_ROOT, local_music, peer_music, log=lambda m: None
    )

    assert stats.updated_peer == 1
    assert stats.updated_local == 0
    peer_db.session.refresh(peer_content)
    assert peer_content.Rating == 5


def test_merge_playlists_creates_and_unions_membership(
    local_db, peer_db, local_music: Path, peer_music: Path
) -> None:
    # Simulate a track that already exists on both sides (e.g. merge_tracks
    # already ran), then a playlist referencing it that only exists locally.
    (local_music / "b.mp3").write_bytes(b"b")
    shutil.copy2(local_music / "b.mp3", peer_music / "b.mp3")
    local_content_b = local_db.add_content(local_music / "b.mp3", Title="B")
    local_db.commit()
    peer_content_b = _seed_track(peer_db, peer_music / "b.mp3", f"{PEER_ROOT}/b.mp3", Title="B")
    peer_db.commit()

    playlist = local_db.create_playlist("Road Trip")
    local_db.add_to_playlist(playlist, local_content_b)
    local_db.commit()

    stats = merge_playlists(
        local_db, peer_db, str(local_music), PEER_ROOT, log=lambda m: None
    )

    assert stats.created_peer == 1
    assert stats.added_peer == 1
    peer_playlist = peer_db.get_playlist(Name="Road Trip").one()
    songs = peer_db.get_playlist_songs(PlaylistID=peer_playlist.ID).all()
    assert len(songs) == 1
    assert songs[0].ContentID == peer_content_b.ID
