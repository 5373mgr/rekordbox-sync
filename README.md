# rekordbox-sync

2台のPC（Windows / macOS 混在可）間で、Rekordboxの楽曲フォルダとライブラリデータ
（プレイリスト・HOT CUE・レーティング等）を同期するためのツール。GUI（設定編集＋
Publish/Sync実行ボタンのみの簡易UI）とCLIの両方を用意しており、どちらも同じ
同期ロジック（`orchestrator.py`）を呼び出す。**ネットワークポートは一切使わない**
（状態確認・実データ転送とも、あらかじめ構成したファイル共有経由で行う）。

設計の背景・アーキテクチャの詳細は [DESIGN.md](DESIGN.md) を参照。

## 前提条件

- 相手PCの楽曲フォルダ・Rekordboxデータフォルダに、OSのファイル共有機能（SMB等、
  同一LANまたはTailscale等ユーザー自身が構築したVPN上に構成したもの）で
  あらかじめアクセスできる状態になっていること。このツールはネットワーク経路や
  共有自体は構築しない
- 同期は手動トリガー。常駐デーモンではない

## インストール

[Releases](../../releases) からOS向けのインストーラーを取得するのが手軽。

- **Windows**: `rekordbox-sync-setup.exe` を実行（CLI/GUI両方を `Program Files\rekordbox-sync`
  にインストールし、Start Menuにショートカットを作成。「PATHに追加」タスクを
  チェックすればターミナルから `rekordbox-sync` を直接呼べるようになる）
- **macOS**: `rekordbox-sync.pkg` を実行（GUIを `/Applications` に、CLIを
  `/usr/local/bin/rekordbox-sync` にインストール）。署名していないため、初回起動時に
  Gatekeeperにブロックされる場合はFinderで対象を右クリック→「開く」を選ぶか、
  `xattr -d com.apple.quarantine /Applications/rekordbox-sync-gui.app` を実行する

ソースから使う場合:

```bash
pip install -e ".[dev]"
```

## 使い方（GUI）

```bash
rekordbox-sync-gui
```

起動すると設定フォームが表示される。既存の `config.yaml` があれば自動で読み込み、
なければ `config.example.yaml` の内容で初期表示する。フォルダを指定する項目は
「参照...」ボタンでExplorer/Finderから選べる。フォームを編集して「設定を保存」
すると `config.yaml` に書き込まれる。

- **Publish（状態を公開）**: 相手からのsyncを受け付ける側で先に押しておく
  （Rekordbox起動状況とライブラリの索引を、自分の楽曲フォルダ内に書き出すだけ。
  待ち受けやポート開放は不要）
- **Sync 実行**: Push（自分→相手、上書き）/ Pull（相手→自分、上書き）/
  Merge（両側を合流、削除は伝播しない）を選び、必要なら Dry run をチェックして実行する

Rekordboxの起動チェック・ライブラリの索引作成・`master.db`のバックアップと
パス書き換えは、いずれもSync実行時に内部で自動的に行われる。

## 使い方（CLI）

```bash
# 初回: config.yaml を作成して編集
rekordbox-sync init

# (初回のみ) 音楽フォルダを設定したルート配下に揃える
rekordbox-sync relocate

# 受け側で状態を公開(ポート開放不要、共有経由で読まれるだけ)
rekordbox-sync publish

# 送り側で同期を実行(片方向・上書き)
rekordbox-sync sync --direction push   # 自分 -> 相手
rekordbox-sync sync --direction pull   # 相手 -> 自分

# 両側を合流させる(新規は両方に反映、削除は伝播しない)
rekordbox-sync merge

# 内容を確認するだけ(実際には転送しない)
rekordbox-sync sync --direction push --dry-run
rekordbox-sync merge --dry-run
```

`sync`（push/pull）は片方向の上書きで、方向を誤ると片方の変更が失われる点に注意
（`master.db`は上書き前に自動でタイムスタンプ付きバックアップが作られる）。

`merge` は自宅PCで楽曲整理をしつつ、出先のノートPCで購入・インポートした曲や
作成したプレイリストがある、といったケース向け。新規ファイル・新規トラック・
プレイリストのメンバーシップは両側に合流し、同じファイルが両側で食い違っていれば
新しい方（mtime基準）を採用する。**削除は一切伝播しない**（安全側の設計）。
`push`/`pull`と異なり両方の`master.db`を書き換えるため、両方とも事前にバックアップされる。

## 開発

```bash
pip install -e ".[dev]"
pytest
```

## ライセンス

MIT
