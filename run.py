"""Entry point used for PyInstaller builds (avoids relative-import issues
that come from freezing `rekordbox_sync/cli.py` directly as the target)."""

from rekordbox_sync.cli import main

if __name__ == "__main__":
    main()
