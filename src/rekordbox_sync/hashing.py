from __future__ import annotations

from pathlib import Path

import xxhash

_CHUNK_SIZE = 1024 * 1024


def hash_file(path: Path) -> str:
    """Fast, non-cryptographic content hash used for change detection.

    Not suitable for security purposes — only for telling whether a file's
    content changed between two scans.
    """
    hasher = xxhash.xxh3_64()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest()
