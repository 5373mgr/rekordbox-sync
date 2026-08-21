"""Entry point used for PyInstaller builds of the GUI (avoids relative-import
issues that come from freezing `rekordbox_sync/gui.py` directly as the
target)."""

from rekordbox_sync.gui import main

if __name__ == "__main__":
    main()
