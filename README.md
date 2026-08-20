# rekordbox-sync

2台のPC（Windows / macOS 混在可）間で、Rekordboxの楽曲フォルダとライブラリデータ
（プレイリスト・HOT CUE・レーティング等）を同期するためのCLIツール。

設計の背景・アーキテクチャの詳細は [DESIGN.md](DESIGN.md) を参照。

## 前提条件

- 2台のPCが同期実行時に**ネットワーク的に相互到達可能**であること（同一LAN、または
  Tailscale等ユーザー自身が構築したVPN）。このツールはネットワーク経路自体は構築しない
- 相手PCの楽曲フォルダ・Rekordboxデータフォルダに、OSのファイル共有機能（SMB等）で
  あらかじめアクセスできる状態になっていること
- 同期は手動トリガー。常駐デーモンではない

## インストール

```bash
pip install -e ".[dev]"
```

または [Releases](../../releases) から各OS向けのビルド済み実行ファイルを利用。

## 使い方

```bash
# 初回: config.yaml を作成して編集
rekordbox-sync init

# (初回のみ) 音楽フォルダを設定したルート配下に揃える
rekordbox-sync relocate

# 受け側で待ち受け
rekordbox-sync listen

# 送り側で同期を実行
rekordbox-sync sync --direction push   # 自分 -> 相手
rekordbox-sync sync --direction pull   # 相手 -> 自分

# 内容を確認するだけ(実際には転送しない)
rekordbox-sync sync --direction push --dry-run
```

`sync` は片方向のみで、双方向マージは行わない。同期方向を誤ると片方の変更が失われる点に
注意（`master.db`は上書き前に自動でタイムスタンプ付きバックアップが作られる）。

## 開発

```bash
pip install -e ".[dev]"
pytest
```

## ライセンス

MIT
