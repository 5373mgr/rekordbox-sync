from __future__ import annotations

import psutil

_REKORDBOX_NAMES = {"rekordbox", "rekordbox.exe"}


def is_rekordbox_running() -> bool:
    for proc in psutil.process_iter(["name"]):
        name = (proc.info.get("name") or "").lower()
        if name in _REKORDBOX_NAMES:
            return True
    return False


def ensure_rekordbox_stopped() -> None:
    if is_rekordbox_running():
        raise RuntimeError(
            "Rekordbox is currently running on this machine. "
            "Close it before syncing to avoid a corrupted or inconsistent database."
        )
