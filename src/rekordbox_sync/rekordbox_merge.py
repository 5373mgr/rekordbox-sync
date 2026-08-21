from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from pyrekordbox.db6 import tables

Logger = Callable[[str], None]

# Fields copied wholesale between tracks that exist on both sides, in
# either direction, whichever side is newer wins the whole set. Deliberately
# excludes identity/FK-ish fields (paths, IDs) which are handled separately.
_TRACK_METADATA_FIELDS = [
    "Title", "BPM", "Length", "TrackNo", "DiscNo", "Rating", "Commnt",
    "ColorID", "KeyID", "ReleaseYear", "Subtitle", "ISRC",
]


def _normalize_root(root: str) -> str:
    return str(root).replace("\\", "/").rstrip("/")


def _relative_key(folder_path: str | None, root: str) -> str | None:
    if not folder_path:
        return None
    folder_path = folder_path.replace("\\", "/")
    prefix = _normalize_root(root) + "/"
    if folder_path.startswith(prefix):
        return folder_path[len(prefix) :]
    return None


def _dest_path(root: str, rel: str) -> str:
    return f"{_normalize_root(root)}/{rel}"


def _resolve_artist(dest_db: Any, name: str | None) -> str | None:
    if not name:
        return None
    existing = dest_db.get_artist(Name=name).one_or_none()
    if existing is not None:
        return existing.ID
    return dest_db.add_artist(name=name).ID


def _resolve_album(dest_db: Any, name: str | None, artist_id: str | None) -> str | None:
    if not name:
        return None
    existing = dest_db.get_album(Name=name).one_or_none()
    if existing is not None:
        return existing.ID
    return dest_db.add_album(name=name, artist=artist_id).ID


def _resolve_genre(dest_db: Any, name: str | None) -> str | None:
    if not name:
        return None
    existing = dest_db.get_genre(Name=name).one_or_none()
    if existing is not None:
        return existing.ID
    return dest_db.add_genre(name=name).ID


def _resolve_label(dest_db: Any, name: str | None) -> str | None:
    if not name:
        return None
    existing = dest_db.get_label(Name=name).one_or_none()
    if existing is not None:
        return existing.ID
    return dest_db.add_label(name=name).ID


def _copy_lookup_fields(dest_db: Any, source_db: Any, source_content: Any) -> dict:
    """Resolve Artist/Album/Genre/Label references by *name* into the
    destination database (get-or-create). These tables assign their own
    per-database IDs, so a raw ID copy would point at the wrong row -- or,
    worse, a coincidentally existing unrelated one. KeyID/ColorID reference
    Rekordbox's fixed, shipped-with-the-app lookup tables and are assumed
    identical across installations, so those are copied as-is."""

    def artist_name(artist_id: str | None) -> str | None:
        if not artist_id:
            return None
        # get_X(ID=...) resolves straight to the row (or None) rather than
        # a Query -- unlike get_X(Name=...) used elsewhere in this module.
        artist = source_db.get_artist(ID=artist_id)
        return artist.Name if artist else None

    kwargs: dict = {}
    artist_id = _resolve_artist(dest_db, artist_name(source_content.ArtistID))
    kwargs["ArtistID"] = artist_id
    kwargs["ComposerID"] = _resolve_artist(dest_db, artist_name(source_content.ComposerID))
    kwargs["RemixerID"] = _resolve_artist(dest_db, artist_name(source_content.RemixerID))
    kwargs["OrgArtistID"] = _resolve_artist(dest_db, artist_name(source_content.OrgArtistID))

    album = source_db.get_album(ID=source_content.AlbumID) if source_content.AlbumID else None
    kwargs["AlbumID"] = _resolve_album(dest_db, album.Name if album else None, artist_id)

    genre = (
        source_db.get_genre(ID=source_content.GenreID)
        if source_content.GenreID
        else None
    )
    kwargs["GenreID"] = _resolve_genre(dest_db, genre.Name if genre else None)

    label = (
        source_db.get_label(ID=source_content.LabelID) if source_content.LabelID else None
    )
    kwargs["LabelID"] = _resolve_label(dest_db, label.Name if label else None)

    kwargs["KeyID"] = source_content.KeyID
    kwargs["ColorID"] = source_content.ColorID
    return kwargs


def _copy_cues(dest_db: Any, source_db: Any, source_content_id: str, dest_content: Any) -> None:
    # Note: Rekordbox6Database.get_content_cue() queries the *different*
    # `ContentCue` table (a single undecoded Cues blob column), not the
    # per-point `DjmdCue` table HOT CUE/Memory CUE data actually lives in.
    cues = source_db.query(tables.DjmdCue).filter_by(ContentID=source_content_id).all()
    for cue in cues:
        new_cue = tables.DjmdCue.create(
            ID=str(uuid4()),
            ContentID=dest_content.ID,
            InMsec=cue.InMsec,
            InFrame=cue.InFrame,
            InMpegFrame=cue.InMpegFrame,
            InMpegAbs=cue.InMpegAbs,
            OutMsec=cue.OutMsec,
            OutFrame=cue.OutFrame,
            OutMpegFrame=cue.OutMpegFrame,
            OutMpegAbs=cue.OutMpegAbs,
            Kind=cue.Kind,
            Color=cue.Color,
            ColorTableIndex=cue.ColorTableIndex,
            ActiveLoop=cue.ActiveLoop,
            Comment=cue.Comment,
            BeatLoopSize=cue.BeatLoopSize,
            CueMicrosec=cue.CueMicrosec,
            InPointSeekInfo=cue.InPointSeekInfo,
            OutPointSeekInfo=cue.OutPointSeekInfo,
            ContentUUID=dest_content.UUID,
            UUID=str(uuid4()),
        )
        dest_db.add(new_cue)


def _copy_new_track(
    dest_db: Any,
    source_db: Any,
    source_content: Any,
    local_reachable_path: Path,
    dest_os_path: str,
) -> Any:
    """Create `source_content` in `dest_db`. `local_reachable_path` is where
    the audio file can actually be read from *by this process* (needed for
    add_content's file-size/type check); `dest_os_path` is the path value
    that should end up stored in FolderPath, which is the destination
    machine's own view and can differ from `local_reachable_path` when
    writing into a peer's database over a share."""
    kwargs = _copy_lookup_fields(dest_db, source_db, source_content)
    for field in _TRACK_METADATA_FIELDS:
        value = getattr(source_content, field, None)
        if value is not None:
            kwargs[field] = value

    new_content = dest_db.add_content(local_reachable_path, **kwargs)

    # A brand-new track has no analysis yet (Analysed=0, no AnalysisDataPath),
    # so `update_content_path` -- which also tries to rewrite the ANLZ files
    # -- doesn't apply here; just fix up the path fields directly.
    normalized = dest_os_path.replace("\\", "/")
    if new_content.FolderPath != normalized:
        new_content.FolderPath = normalized
        new_content.OrgFolderPath = normalized
        new_content.FileNameL = normalized.rsplit("/", 1)[-1]

    _copy_cues(dest_db, source_db, source_content.ID, new_content)
    return new_content


def _update_existing_track(dest_content: Any, source_content: Any) -> None:
    """Whole-row last-write-wins: overwrite dest_content's editable fields
    with source_content's (the newer one)."""
    for field in _TRACK_METADATA_FIELDS:
        value = getattr(source_content, field, None)
        if value is not None:
            setattr(dest_content, field, value)


@dataclass
class TrackMergeStats:
    added_to_local: int = 0
    added_to_peer: int = 0
    updated_local: int = 0
    updated_peer: int = 0


def merge_tracks(
    local_db: Any,
    peer_db: Any,
    local_root: str,
    peer_root: str,
    local_music_dir: Path,
    peer_music_share: Path,
    log: Logger,
) -> TrackMergeStats:
    """Union-merge DjmdContent rows (+ their cues) between two databases,
    matched by file path -- not by row ID, which is only unique within a
    single database. Requires the file-level merge to have already run, so
    a newly-added track's audio file physically exists at its destination.
    Tracks existing on both sides are reconciled by last-write-wins on
    `updated_at`. Never deletes a track from either side."""
    stats = TrackMergeStats()

    local_tracks = {
        rel: c
        for c in local_db.get_content()
        if (rel := _relative_key(c.FolderPath, local_root)) is not None
    }
    peer_tracks = {
        rel: c
        for c in peer_db.get_content()
        if (rel := _relative_key(c.FolderPath, peer_root)) is not None
    }

    for rel in sorted(set(local_tracks) | set(peer_tracks)):
        local_content = local_tracks.get(rel)
        peer_content = peer_tracks.get(rel)

        if local_content is not None and peer_content is None:
            log(f"[tracks] new on this machine, adding to peer: {rel}")
            _copy_new_track(
                peer_db,
                local_db,
                local_content,
                local_reachable_path=peer_music_share / rel,
                dest_os_path=_dest_path(peer_root, rel),
            )
            stats.added_to_peer += 1
        elif peer_content is not None and local_content is None:
            log(f"[tracks] new on peer, adding here: {rel}")
            _copy_new_track(
                local_db,
                peer_db,
                peer_content,
                local_reachable_path=local_music_dir / rel,
                dest_os_path=_dest_path(str(local_music_dir), rel),
            )
            stats.added_to_local += 1
        else:
            local_updated = local_content.updated_at or ""
            peer_updated = peer_content.updated_at or ""
            if local_updated == peer_updated:
                continue
            if local_updated > peer_updated:
                _update_existing_track(peer_content, local_content)
                stats.updated_peer += 1
            else:
                _update_existing_track(local_content, peer_content)
                stats.updated_local += 1

    local_db.commit()
    peer_db.commit()
    return stats


@dataclass
class PlaylistMergeStats:
    created_local: int = 0
    created_peer: int = 0
    added_local: int = 0
    added_peer: int = 0


def _normal_playlists(db: Any) -> list:
    return db.get_playlist(Attribute=0).all()


def merge_playlists(
    local_db: Any, peer_db: Any, local_root: str, peer_root: str, log: Logger
) -> PlaylistMergeStats:
    """Union-merge playlist membership, matching playlists by name (flat --
    folder hierarchy isn't considered) and tracks by file path. Creates a
    matching playlist on the other side if it doesn't exist yet. Never
    removes an existing playlist or membership. Run this after
    `merge_tracks` so tracks referenced by a peer-only playlist already
    exist locally (and vice versa)."""
    stats = PlaylistMergeStats()

    local_by_name = {p.Name: p for p in _normal_playlists(local_db)}
    peer_by_name = {p.Name: p for p in _normal_playlists(peer_db)}

    for name in sorted(set(local_by_name) | set(peer_by_name)):
        local_playlist = local_by_name.get(name)
        peer_playlist = peer_by_name.get(name)

        if local_playlist is None:
            local_playlist = local_db.create_playlist(name)
            stats.created_local += 1
            log(f"[playlists] created here: {name}")
        if peer_playlist is None:
            peer_playlist = peer_db.create_playlist(name)
            stats.created_peer += 1
            log(f"[playlists] created on peer: {name}")

        local_paths = {
            rel
            for song in local_db.get_playlist_songs(PlaylistID=local_playlist.ID)
            if (content := local_db.get_content(ID=song.ContentID)) is not None
            and (rel := _relative_key(content.FolderPath, local_root)) is not None
        }
        peer_paths = {
            rel
            for song in peer_db.get_playlist_songs(PlaylistID=peer_playlist.ID)
            if (content := peer_db.get_content(ID=song.ContentID)) is not None
            and (rel := _relative_key(content.FolderPath, peer_root)) is not None
        }

        for rel in sorted(peer_paths - local_paths):
            content = local_db.get_content(FolderPath=_dest_path(local_root, rel)).one_or_none()
            if content is not None:
                local_db.add_to_playlist(local_playlist, content)
                stats.added_local += 1
                log(f"[playlists] added to '{name}' here: {rel}")

        for rel in sorted(local_paths - peer_paths):
            content = peer_db.get_content(FolderPath=_dest_path(peer_root, rel)).one_or_none()
            if content is not None:
                peer_db.add_to_playlist(peer_playlist, content)
                stats.added_peer += 1
                log(f"[playlists] added to '{name}' on peer: {rel}")

    local_db.commit()
    peer_db.commit()
    return stats
