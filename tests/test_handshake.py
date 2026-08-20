import socket
import threading

from rekordbox_sync.handshake import PeerStatus, request, serve_once
from rekordbox_sync.index import FileEntry


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_handshake_exchanges_status_both_ways() -> None:
    port = _free_port()
    server_status = PeerStatus(
        rekordbox_running=False,
        manifest={"a.mp3": FileEntry("a.mp3", 1, 1.0, "hash-a")},
    )
    client_status = PeerStatus(
        rekordbox_running=True,
        manifest={"b.mp3": FileEntry("b.mp3", 2, 2.0, "hash-b")},
    )

    result_holder: dict[str, PeerStatus] = {}

    def run_server() -> None:
        result_holder["server_saw"] = serve_once(port, server_status, timeout=10)

    thread = threading.Thread(target=run_server)
    thread.start()

    # Give the server a moment to bind before the client connects.
    import time

    time.sleep(0.2)

    client_saw = request("127.0.0.1", port, client_status, timeout=10)
    thread.join(timeout=10)

    assert client_saw.rekordbox_running is False
    assert client_saw.manifest["a.mp3"].hash == "hash-a"

    assert result_holder["server_saw"].rekordbox_running is True
    assert result_holder["server_saw"].manifest["b.mp3"].hash == "hash-b"
