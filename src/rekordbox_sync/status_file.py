from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .index import STATUS_FILENAME, FileEntry

# How old a peer's published status is allowed to get before we warn that it
# might not reflect the peer's current state (e.g. Rekordbox was opened
# after they last published).
STALE_AFTER_SECONDS = 10 * 60


@dataclass
class PeerStatus:
    rekordbox_running: bool
    manifest: dict[str, FileEntry]
    published_at: float

    @property
    def age_seconds(self) -> float:
        return time.time() - self.published_at

    @property
    def is_stale(self) -> bool:
        return self.age_seconds > STALE_AFTER_SECONDS


def write_status(music_root: Path, rekordbox_running: bool, manifest: dict[str, FileEntry]) -> Path:
    """Publish this machine's status into its own music folder, where the
    peer can read it via the share path they've configured to reach us."""
    payload = {
        "rekordbox_running": rekordbox_running,
        "published_at": time.time(),
        "manifest": {rel: [e.size, e.mtime, e.hash] for rel, e in manifest.items()},
    }
    status_path = Path(music_root) / STATUS_FILENAME
    status_path.write_text(json.dumps(payload), encoding="utf-8")
    return status_path


def read_status(music_share: Path) -> PeerStatus:
    """Read the peer's last-published status from their shared music folder."""
    status_path = Path(music_share) / STATUS_FILENAME
    if not status_path.exists():
        raise FileNotFoundError(
            f"No status file found at {status_path}. The peer needs to run "
            "'publish' (or a sync) at least once before this machine can sync with it."
        )
    data = json.loads(status_path.read_text(encoding="utf-8"))
    manifest = {
        rel: FileEntry(rel, size, mtime, digest)
        for rel, (size, mtime, digest) in data["manifest"].items()
    }
    return PeerStatus(
        rekordbox_running=data["rekordbox_running"],
        manifest=manifest,
        published_at=data["published_at"],
    )
