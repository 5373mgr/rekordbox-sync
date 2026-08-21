from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, scrolledtext, ttk
from typing import Callable

import yaml

from . import config as config_mod
from . import orchestrator

_FIELDS = [
    # (key, label, default, browsable)
    ("local_music_root", "楽曲フォルダ (このPC)", "", True),
    ("local_rekordbox_data_dir", "Rekordboxデータフォルダ (空欄=自動)", "", True),
    ("remote_music_root", "楽曲フォルダ (相手PC自身のパス)", "", False),
    ("remote_music_share", "楽曲フォルダの共有パス (自分から見た相手)", "", True),
    ("remote_rekordbox_share", "Rekordboxデータの共有パス (自分から見た相手)", "", True),
]


def _load_raw(path: Path) -> dict:
    source = path if path.exists() else orchestrator.EXAMPLE_CONFIG
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    local = data.get("local", {})
    remote = data.get("remote", {})
    return {
        "local_music_root": local.get("music_root", ""),
        "local_rekordbox_data_dir": local.get("rekordbox_data_dir") or "",
        "remote_music_root": remote.get("music_root", ""),
        "remote_music_share": remote.get("music_share", ""),
        "remote_rekordbox_share": remote.get("rekordbox_share", ""),
    }


def _save_raw(path: Path, values: dict) -> None:
    data = {
        "local": {
            "music_root": values["local_music_root"],
            "rekordbox_data_dir": values["local_rekordbox_data_dir"] or None,
        },
        "remote": {
            "music_root": values["remote_music_root"],
            "music_share": values["remote_music_share"],
            "rekordbox_share": values["remote_rekordbox_share"],
        },
    }
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


class App(tk.Tk):
    """Minimal GUI: edit the settings that matter, then hit Publish/Sync.
    All actual logic lives in `orchestrator.py` — this module only wires
    the form and buttons to those calls and renders progress. No network
    port involved anywhere: reachability is purely through the shared
    folders configured below."""

    def __init__(self) -> None:
        super().__init__()
        self.title("rekordbox-sync")
        self.geometry("640x560")
        self.minsize(520, 440)

        self.config_path = Path("config.yaml")
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._busy = False
        self._field_vars: dict[str, tk.StringVar] = {}

        self._build_widgets()
        self._load_form()
        self.after(100, self._drain_log_queue)

    def _build_widgets(self) -> None:
        path_row = ttk.Frame(self, padding=8)
        path_row.pack(fill="x")
        ttk.Label(path_row, text="config.yaml:").pack(side="left")
        self.config_label = ttk.Label(path_row, text=str(self.config_path))
        self.config_label.pack(side="left", padx=4)
        ttk.Button(path_row, text="選択...", command=self._choose_config).pack(side="left")

        form = ttk.LabelFrame(self, text="設定", padding=8)
        form.pack(fill="x", padx=8, pady=4)
        form.columnconfigure(1, weight=1)
        for row, (key, label, default, browsable) in enumerate(_FIELDS):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=default)
            ttk.Entry(form, textvariable=var).grid(
                row=row, column=1, sticky="ew", padx=4, pady=2
            )
            self._field_vars[key] = var
            if browsable:
                ttk.Button(
                    form, text="参照...", command=lambda v=var: self._browse_into(v)
                ).grid(row=row, column=2, pady=2)

        self._save_button = ttk.Button(form, text="設定を保存", command=self._on_save)
        self._save_button.grid(row=len(_FIELDS), column=0, columnspan=3, pady=(6, 0))

        sync_row = ttk.LabelFrame(self, text="同期", padding=8)
        sync_row.pack(fill="x", padx=8, pady=4)
        self.direction = tk.StringVar(value="push")
        ttk.Radiobutton(
            sync_row, text="Push (自分→相手)", variable=self.direction, value="push"
        ).pack(side="left")
        ttk.Radiobutton(
            sync_row, text="Pull (相手→自分)", variable=self.direction, value="pull"
        ).pack(side="left")
        self.dry_run = tk.BooleanVar(value=False)
        ttk.Checkbutton(sync_row, text="Dry run", variable=self.dry_run).pack(
            side="left", padx=8
        )

        self._publish_button = ttk.Button(
            sync_row, text="Publish (状態を公開)", command=self._on_publish
        )
        self._publish_button.pack(side="left", padx=8)
        self._sync_button = ttk.Button(sync_row, text="Sync 実行", command=self._on_sync)
        self._sync_button.pack(side="left")

        self.log_text = scrolledtext.ScrolledText(self, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # -- logging -----------------------------------------------------

    def _log(self, message: str) -> None:
        self._log_queue.put(message)

    def _drain_log_queue(self) -> None:
        while not self._log_queue.empty():
            message = self._log_queue.get_nowait()
            self.log_text.configure(state="normal")
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(100, self._drain_log_queue)

    # -- background task plumbing ------------------------------------

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for button in (self._save_button, self._publish_button, self._sync_button):
            button.configure(state=state)

    def _run_in_background(self, task: Callable[[], None]) -> None:
        if self._busy:
            self._log("他の操作が実行中です。完了までお待ちください。")
            return

        def wrapper() -> None:
            self._set_busy(True)
            try:
                task()
            except Exception as exc:  # surfaced to the user via the log pane
                self._log(f"ERROR: {exc}")
            finally:
                self._set_busy(False)

        threading.Thread(target=wrapper, daemon=True).start()

    def _load_config(self) -> config_mod.Config | None:
        try:
            return config_mod.load_config(self.config_path)
        except FileNotFoundError as exc:
            self._log(f"ERROR: {exc}")
            return None

    # -- form <-> config.yaml -------------------------------------------

    def _load_form(self) -> None:
        try:
            values = _load_raw(self.config_path)
        except Exception as exc:
            self._log(f"設定の読み込みに失敗しました: {exc}")
            return
        for key, var in self._field_vars.items():
            var.set(values.get(key, ""))

    def _browse_into(self, var: tk.StringVar) -> None:
        path = filedialog.askdirectory(initialdir=var.get() or None)
        if path:
            var.set(path)

    def _choose_config(self) -> None:
        path = filedialog.askopenfilename(
            initialfile="config.yaml", filetypes=[("YAML", "*.yaml"), ("All files", "*.*")]
        )
        if path:
            self.config_path = Path(path)
            self.config_label.configure(text=str(self.config_path))
            self._load_form()

    def _on_save(self) -> None:
        values = {key: var.get().strip() for key, var in self._field_vars.items()}
        _save_raw(self.config_path, values)
        self._log(f"設定を {self.config_path} に保存しました。")

    # -- sync actions -----------------------------------------------

    def _on_publish(self) -> None:
        def task() -> None:
            cfg = self._load_config()
            if not cfg:
                return
            orchestrator.publish_status(cfg, self.config_path, self._log)

        self._run_in_background(task)

    def _on_sync(self) -> None:
        def task() -> None:
            cfg = self._load_config()
            if not cfg:
                return
            orchestrator.run_sync(
                cfg, self.config_path, self.direction.get(), self.dry_run.get(), self._log
            )

        self._run_in_background(task)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
