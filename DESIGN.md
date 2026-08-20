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

- 2PCは同期実行時に**ネットワーク的に相互到達可能**であること（同一LAN、またはユーザー自身が構築したVPN＝Tailscale/ZeroTire/WireGuard等、いずれでも可）。到達性の確立はツールの責務外とし、ツールは「設定されたホストに疎通できるか」のみを確認する
- 同期は**手動トリガー**（常駐デーモンではなく、ユーザーが同期したいタイミングで実行するCLI/GUI）
- 双方向マージは行わない。同期実行のたびに **push（自分→相手）** か **pull（相手→自分）** を明示的に選ぶ片方向運用とする

## アーキテクチャ概要

```
[PC A]                                          [PC B]
 ┌───────────────────────┐                ┌───────────────────────┐
 │ rekordbox-sync (Python)│                │ rekordbox-sync (Python)│
 │  - Local Index (SQLite)│◄──handshake───►│  - Local Index (SQLite)│
 │  - Rekordbox process   │   (確認のみ)    │  - Rekordbox process   │
 │    guard                │                │    guard                │
 │  - master.db path      │                │  - master.db path      │
 │    rewriter             │                │    rewriter             │
 └──────────┬──────────────┘                └──────────┬──────────────┘
            │                                            │
            └──────────── 実データ転送 (SMB/直接コピー) ───┘
                    ※ハンドシェイクとは別チャネル
```

### コンポーネント

1. **Local Index（SQLite, 各PCローカル）**
   - 対象: 楽曲フォルダ全体 ＋ Rekordboxデータフォルダ
   - スキーマ: `relative_path, size, mtime, hash, last_indexed_at`
   - ハッシュは非暗号高速ハッシュ（xxHash / BLAKE3系）を使用。サイズ・mtimeが前回と一致するファイルは再ハッシュしない（rsync/rclone同様の最適化）。ファイル数・総容量が大きいライブラリでも2回目以降のスキャンは高速

2. **Handshake（確認専用の通信）**
   - 同期実行時のみ、設定されたホスト:ポートに接続する軽量プロトコル（JSON over TCP想定）
   - 交換する情報: 自分のマニフェスト要約、Rekordboxプロセスが停止しているか
   - 直接到達できることが前提。到達不可の場合は同期不可（クラウド中継のフォールバックは採用しない）
   - **このチャネルは確認・調停のみに使う。実データはここを通さない**

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
  host: "100.x.x.x"                  # Tailscale等で到達可能なホスト
  port: 51820
  music_root: "/Users/foo/Music/DJ"  # 相手PC側のルートパス（パス書き換えに使用）
```

認証情報やホスト固有情報はリポジトリにコミットしない。`config.example.yaml` をテンプレートとして同梱する。

## パッケージ構成（想定）

```
rekordbox-sync/
├── DESIGN.md
├── pyproject.toml
├── config.example.yaml
├── .gitignore
├── src/
│   └── rekordbox_sync/
│       ├── __init__.py
│       ├── cli.py                # エントリポイント
│       ├── config.py             # config.yaml ロード
│       ├── index.py              # Local Index (SQLite) 管理
│       ├── hashing.py            # 差分検出用ハッシュ計算
│       ├── process_guard.py      # Rekordbox起動チェック (psutil)
│       ├── handshake.py          # 確認用ソケット通信
│       ├── transfer.py           # 差分転送実行
│       ├── rekordbox_db.py       # master.db 読み書き・パス書き換え (pyrekordbox)
│       └── relocate.py           # 初回の音楽フォルダ再配置処理
├── tests/
└── .github/
    └── workflows/
        └── build-installers.yml  # Windows/macOS インストーラビルド
```

## CI/CD（GitHub Actions）

- `windows-latest` / `macos-latest` のマトリクスビルド
- PyInstaller でOSごとの単体実行ファイルを生成
  - Windows: `.exe`（必要なら Inno Setup 等でインストーラ化）
  - macOS: `.app`（`.dmg`にまとめる）
- タグpush（`v*`）をトリガーに、GitHub Releasesへ成果物を添付

## 既知のリスク・制約

- `pyrekordbox`はRekordboxの非公開DB形式に依存するリバースエンジニアリング実装のため、Rekordboxアップデートで暗号化方式が変わると追従が必要になる可能性がある
- 双方向マージ非対応のため、同期方向を誤ると片方の変更が失われる（バックアップ退避で復旧は可能）
- ネットワーク到達性の確立（VPN等）はユーザー側の前提条件であり、ツールはそれを構築しない

## 未確定事項

- Handshakeプロトコルの詳細（メッセージフォーマット、ポート、認証の要否）
- インストーラの署名（特にmacOSのnotarization）の要否
