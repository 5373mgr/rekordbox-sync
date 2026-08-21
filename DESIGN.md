# rekordbox-sync 設計ドキュメント

2台のPC（Windows / macOS 混在可）間で、Rekordboxの楽曲フォルダとライブラリデータ（プレイリスト・HOT CUE・レーティング等）を同期するためのツール。

## ゴール

- 楽曲フォルダ（例: `D:\DJ Itunes`）の2PC間差分同期
- Rekordboxライブラリデータ（`master.db`）の2PC間同期
- Mac ⇔ Windows 間の同期にも対応

## 非ゴール（明示的に採用しない方式）

- **Rekordbox公式 Cloud Library Sync**: 楽曲保管にDropbox必須のため不採用。追加サブスクも不要にしたい
- **ツール内蔵のVPN（WireGuard等の組み込み）**: NAT越え・鍵配布・エンドポイント検出など、Tailscale等が既に解決している問題を自前で背負うことになり、OSS公開時のセキュリティレビュー負担も増えるため不採用
- **クラウドストレージ（GoogleDrive/AWS等）を経由した中継同期**: 直接到達可能なネットワーク（LAN/VPN）経由の同期のみをサポートする。クラウド中継は将来的にも実装しない

## 前提条件

- 2PCは同期実行時に、片方が設定した共有パス（`remote.music_share` / `remote.rekordbox_share`）経由で**もう片方のフォルダにファイルシステムとしてアクセスできる**こと（同一LAN上のSMB共有、またはユーザー自身が構築したVPN＝Tailscale等の上に構築した共有、いずれでも可）。ネットワーク到達性・共有の構築自体はツールの責務外とする
- **ツールはネットワークポートを一切開かない**。状態確認（後述のPublish/Status）も実データ転送も、すべて上記の共有フォルダ経由で行う
- 同期は**手動トリガー**（常駐デーモンではなく、ユーザーが同期したいタイミングで実行するCLI/GUI）
- 同期モードは3種類: **push（自分→相手、上書き）**・**pull（相手→自分、上書き）**・**merge（両側を合流、後述）**

## アーキテクチャ概要

```
[PC A]                                          [PC B]
 ┌───────────────────────┐                ┌───────────────────────┐
 │ rekordbox-sync (Python)│                │ rekordbox-sync (Python)│
 │  - Local Index (SQLite)│                │  - Local Index (SQLite)│
 │  - Rekordbox process   │                │  - Rekordbox process   │
 │    guard                │                │    guard                │
 │  - master.db path      │                │  - master.db path      │
 │    rewriter             │                │    rewriter             │
 │  - status file          │                │  - status file          │
 │    (自分の音楽フォルダに書く)│                │    (自分の音楽フォルダに書く)│
 └──────────┬──────────────┘                └──────────┬──────────────┘
            │                                            │
            └───── 共有フォルダ経由 (SMB等) ────────────────┘
                 status読み取り・実データ転送とも同じ経路
```

### コンポーネント

1. **Local Index（SQLite, 各PCローカル）**
   - 対象: 楽曲フォルダ全体 ＋ Rekordboxデータフォルダ
   - スキーマ: `relative_path, size, mtime, hash, last_indexed_at`
   - ハッシュは非暗号高速ハッシュ（xxHash / BLAKE3系）を使用。サイズ・mtimeが前回と一致するファイルは再ハッシュしない（rsync/rclone同様の最適化）。ファイル数・総容量が大きいライブラリでも2回目以降のスキャンは高速

2. **Status file（確認専用、ネットワークポート不使用）**
   - 各PCは自分の楽曲フォルダ直下に `.rekordbox-sync-status.json`（Rekordbox起動状況・公開日時・自分のマニフェスト要約）を書き込む（`publish` コマンド、またはSync実行時に自動で最新化）
   - 相手側はこのファイルを、共有フォルダ越しに**読むだけ**で確認する。TCP接続やポート開放は一切不要
   - 公開から一定時間（既定10分）経過している場合は「古い可能性がある」警告をログに出す（相手が`publish`し忘れている可能性の検知）
   - このファイル自体はLocal Indexの対象から除外され、楽曲ファイルとして差分転送されることはない
   - **音楽フォルダへの読み書きアクセスさえあれば成立する。実データ転送と全く同じ経路を使う**

3. **Transfer Executor（実データ転送）**
   - 到達可能な場合: SMB共有 or 直接ファイルコピー（差分のみ、Local Indexの比較結果に基づく）
   - 転送前に対象がRekordbox実行中でないことを両PCで確認できていることが前提

4. **Rekordbox Process Guard**
   - OS別にプロセス一覧を確認し、Rekordboxが起動中なら同期を中断する
   - Windows: `rekordbox.exe` / macOS: `rekordbox` プロセス名で検出（`psutil`使用）

5. **master.db 同期とパス書き換え**
   - `master.db`（Rekordbox 6.6.5以降はSQLCipher暗号化）は [pyrekordbox](https://github.com/dylanljones/pyrekordbox) を利用して読み書きする（暗号鍵の追従をコミュニティに委ねられるため自前実装しない）
   - 転送先PCの絶対パス体系がWindows/Macで異なる問題への対応:
     - 初回セットアップで両PCの音楽ルートフォルダ配下を**共通の相対構造**に揃える（案4を採用）
     - 同期時、`master.db`内の各トラックパスについて「自PCのルートパス」プレフィックスを「相手PCのルートパス」プレフィックスに一括置換する
     - パス区切り文字（`\` / `/`）も併せて変換する
   - 上書き前に受信側で現行`master.db`をタイムスタンプ付きバックアップとして退避（誤方向同期からの復旧用）
   - WALファイル（`master.db-wal` / `-shm`）が残っている場合も同期対象に含める（Rekordbox正常終了時は通常チェックポイントされて消えるはずだが、保険として）

6. **Merge（両側合流）**
   - 想定ユースケース: 自宅PCで楽曲整理をしつつ、出先のノートPCで購入・インポートした曲やプレイリストを両方に反映したい場合
   - **祖先スナップショットは持たず、常に「現在の自分」と「現在の相手」の2状態だけで判断する**。同じパス/トラックが片方にしかなければ常に「新規」として扱い、**削除は一切伝播しない**（安全側に倒す設計）
   - 楽曲ファイル: `merge.py` が2-way union + 内容が食い違う場合は新しい方（mtimeが新しい方）を採用
   - Rekordboxトラック: `rekordbox_merge.py` がファイルパス（パス変換後の相対パス）をキーにマッチングし、片方にしかないトラックはHOT CUE/Memory CUE（`DjmdCue`）ごと相手DBへコピー。Artist/Album/Genre/LabelはIDがDB間で対応しないため名前で解決（無ければ作成）。KeyID/ColorIDはRekordbox組み込みの固定参照テーブルとみなしそのままコピー。両側に存在するトラックは`updated_at`が新しい方の内容で上書き
   - プレイリスト: 名前でマッチングし（フォルダ階層は考慮しない）、存在しない側には作成、メンバーシップは2-wayで合流。削除は伝播しない
   - **両方のPCの`master.db`を書き換えるため、実行前に両方をバックアップする**（push/pullは片方のみ書き換え）
   - トラックのマージ→プレイリストのマージの順で実行する必要がある（プレイリストが参照するトラックが先に両側に存在している前提のため）

### Rekordboxデータフォルダの既定パス

| OS | パス |
|---|---|
| Windows | `%APPDATA%\Pioneer\rekordbox\` |
| macOS | `~/Library/Pioneer/rekordbox/` |

フォルダ全体を同期対象にする（`master.db`単体ではなく、解析キャッシュ等の付随データも含めるため）。

## 設定ファイル（config.yaml, gitignore対象）

```yaml
local:
  music_root: "D:/DJ Itunes"        # 例: Windows側
  # music_root: "/Users/foo/Music/DJ"  # 例: macOS側
  rekordbox_data_dir: null           # 未指定時はOS既定値を使用

remote:
  music_root: "/Users/foo/Music/DJ"        # 相手PC側のルートパス（パス書き換えに使用）
  music_share: "//100.x.x.x/DJ Itunes"     # 自分から見た相手の楽曲フォルダ共有パス
  rekordbox_share: "//100.x.x.x/rekordbox-data"  # 同、Rekordboxデータフォルダ
```

ホスト名・ポートの指定は存在しない（ネットワークポートを使わないため）。GUIでは
`local_music_root` / `local_rekordbox_data_dir` / `remote_music_share` /
`remote_rekordbox_share` の4項目はExplorerのフォルダ選択ダイアログで指定できる
（`remote_music_root` のみ相手PC自身のOS上のパス文字列であり、このPCからは参照
できないためテキスト入力のまま）。

認証情報やホスト固有情報はリポジトリにコミットしない。`config.example.yaml` をテンプレートとして同梱する。

## パッケージ構成（想定）

```
rekordbox-sync/
├── DESIGN.md
├── pyproject.toml
├── config.example.yaml
├── .gitignore
├── run.py                     # PyInstaller用 CLI エントリポイント
├── run_gui.py                 # PyInstaller用 GUI エントリポイント
├── src/
│   └── rekordbox_sync/
│       ├── __init__.py
│       ├── orchestrator.py       # 同期処理の本体（CLI/GUI 共通）
│       ├── cli.py                # CLIエントリポイント（orchestratorの薄いラッパー）
│       ├── gui.py                # Tkinter製の簡易GUI（同じくorchestratorを呼ぶ）
│       ├── config.py             # config.yaml ロード
│       ├── index.py              # Local Index (SQLite) 管理
│       ├── hashing.py            # 差分検出用ハッシュ計算
│       ├── process_guard.py      # Rekordbox起動チェック (psutil)
│       ├── status_file.py        # 確認用ステータスファイル (ネットワーク不使用)
│       ├── transfer.py           # 差分転送実行 (push/pull用)
│       ├── merge.py              # 楽曲ファイルの2-way union merge
│       ├── rekordbox_db.py       # master.db 読み書き・パス書き換え (pyrekordbox)
│       ├── rekordbox_merge.py    # トラック/プレイリストの2-way merge (pyrekordbox)
│       └── relocate.py           # 初回の音楽フォルダ再配置処理
├── tests/
└── .github/
    └── workflows/
        └── build-installers.yml  # Windows/macOS インストーラビルド (CLI+GUI)
```

GUIは「設定編集」と「Publish/Sync実行ボタン」のみに絞った簡易UIとし、詳細な進捗ログは
テキストエリアに流す。索引作成・Rekordbox起動チェック・バックアップ等はSync実行時に
`orchestrator.py`側で自動的に行われ、GUI/CLIどちらから使っても同じ動作になる。

## CI/CD（GitHub Actions）

- `windows-latest` / `macos-latest` のマトリクスビルド
- PyInstaller でOSごとの単体実行ファイルを生成
  - Windows: `.exe`（必要なら Inno Setup 等でインストーラ化）
  - macOS: `.app`（`.dmg`にまとめる）
- タグpush（`v*`）をトリガーに、GitHub Releasesへ成果物を添付

## 既知のリスク・制約

- `pyrekordbox`はRekordboxの非公開DB形式に依存するリバースエンジニアリング実装のため、Rekordboxアップデートで暗号化方式が変わると追従が必要になる可能性がある
- push/pullは片方向上書きのため、方向を誤ると片方の変更が失われる（バックアップ退避で復旧は可能）
- ネットワーク到達性・共有フォルダの構築（VPN、SMB共有等）はユーザー側の前提条件であり、ツールはそれを構築しない
- status fileはPublish時点のスナップショットであり、相手が`publish`し忘れていると古い情報のまま同期してしまう可能性がある（一定時間経過で警告は出すが、強制はしない）
- Mergeは削除を一切伝播しない設計のため、意図的に消したファイル/トラック/プレイリストが相手側に残り続ける場合がある（安全側の妥協）
- Mergeのプレイリスト同一性判定は名前のみで、フォルダ階層は考慮しない。同名だが意味の異なるプレイリストがあると誤って合流する可能性がある
- `pyrekordbox`の`Rekordbox6Database.get_content_cue()`は`DjmdCue`（HOT CUE/Memory CUE本体）とは別の`ContentCue`テーブル（未デコードのblob）を指すため、cueデータの読み書きは`DjmdCue`を直接クエリする必要がある（本プロジェクトでは対応済み）

## 未確定事項

- インストーラの署名（特にmacOSのnotarization）の要否
