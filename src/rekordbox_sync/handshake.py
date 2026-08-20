from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any

from .index import FileEntry

_BUFFER_SIZE = 65536

# This channel carries readiness flags and file manifests (paths/sizes/hashes)
# only. It never carries actual file bytes — bulk transfer happens over a
# separately configured share (see config.RemoteConfig.music_share).


@dataclass
class PeerStatus:
    rekordbox_running: bool
    manifest: dict[str, FileEntry]

    def to_wire(self) -> dict[str, Any]:
        return {
            "rekordbox_running": self.rekordbox_running,
            "manifest": {
                rel: [e.size, e.mtime, e.hash] for rel, e in self.manifest.items()
            },
        }

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> PeerStatus:
        manifest = {
            rel: FileEntry(rel, size, mtime, digest)
            for rel, (size, mtime, digest) in data["manifest"].items()
        }
        return cls(rekordbox_running=data["rekordbox_running"], manifest=manifest)


def _send(sock: socket.socket, payload: dict[str, Any]) -> None:
    sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))


def _recv(sock: socket.socket) -> dict[str, Any]:
    chunks: list[bytes] = []
    while True:
        chunk = sock.recv(_BUFFER_SIZE)
        if not chunk:
            break
        chunks.append(chunk)
        if chunk.endswith(b"\n"):
            break
    return json.loads(b"".join(chunks).decode("utf-8"))


def serve_once(port: int, local_status: PeerStatus, timeout: float = 300.0) -> PeerStatus:
    """Block until one peer connects, exchange status, return the peer's status."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", port))
        server.listen(1)
        server.settimeout(timeout)
        conn, _addr = server.accept()
        with conn:
            conn.settimeout(timeout)
            peer_data = _recv(conn)
            _send(conn, local_status.to_wire())
    return PeerStatus.from_wire(peer_data)


def request(host: str, port: int, local_status: PeerStatus, timeout: float = 30.0) -> PeerStatus:
    """Connect to the peer, exchange status, return the peer's status."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        _send(sock, local_status.to_wire())
        peer_data = _recv(sock)
    return PeerStatus.from_wire(peer_data)
