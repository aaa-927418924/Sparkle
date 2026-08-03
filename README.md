# Sparkle

個人用クリップ保存アプリ。Chrome 拡張から送られた Web ページ情報
(URL・コメント・タグ・カテゴリ) を SQLite に保存し、Windows ネイティブウィンドウから
一覧・検索・メモ・プロジェクト管理を行う。

## 技術スタック

- Python 3.10+
- FastAPI
- SQLite (ファイルベース、追加インストール不要)
- uvicorn (内蔵ローカルサーバー)
- pydantic
- pywebview + WebView2 (Windows デスクトップウィンドウ)
- pystray (タスクトレイ)

将来 fastembed による自然言語検索・タグ提案を追加することを想定し、
`clips` テーブルに `embedding` (BLOB) カラムをあらかじめ用意している。

## ファイル構成

```
db.py        SQLite 接続・スキーマ定義 (DB ファイルはアプリデータ内の clips.db)
schemas.py   Pydantic のリクエスト/レスポンス定義
crud.py      カテゴリ・タグの get_or_create ヘルパー (将来拡張用)
routers.py   API エンドポイント定義
main.py      FastAPI アプリ起動・DB 初期化
app_entry.py Windows用の内蔵ウィンドウ・タスクトレイ起動
frontend/    クリップ、メモ、プロジェクトの画面
requirements.txt
```

DB・アップロードファイルは `%APPDATA%\Sparkle` に保存する。
パスの決定は `paths.py`、DBファイルの参照は `db.py` の `DB_PATH` で一元管理している。

## セットアップ

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 開発用起動

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

起動時に自動で `clips.db` が作成 (テーブル初期化) される。
ブラウザで http://127.0.0.1:8000/docs を開くと Swagger UI で API 仕様を
確認・試行できる。

## Windows アプリとして起動

```powershell
.\.venv\Scripts\Activate.ps1
python app_entry.py
```

または `start.bat` をダブルクリックすると、`dist\Sparkle.exe` があれば exe版、
無ければ仮想環境のソース版を起動する。

アプリは `127.0.0.1:8000` のローカルサーバーを内蔵ウィンドウで表示する。
ウィンドウを閉じるとタスクトレイへ隠れ、トレイメニューから再表示または終了できる。
2 回起動した場合は、新しいウィンドウを増やさず既存のウィンドウを前面に表示する。

Windows の Microsoft Edge WebView2 Runtime が必要。通常の Windows 11 環境では
既にインストールされていることが多く、未導入の場合は Microsoft の WebView2 Runtime
をインストールしてから起動する。

### 既存データの移行

以前の保存先やバックアップが残っている状態でSparkleを初回起動すると、移行ダイアログが表示される。
「Sparkleへ移行する」を押すと、AppDataのDB・アップロードファイル、DocumentsのMarkdownエクスポート、
旧バックアップ名、旧スタートアップ登録を検証してから一括移行する。移行後は旧保存先を削除し、
旧バックアップの内容はそのまま保ったままファイル名だけSparkleへ変更する。

移行または初期設定が完了した直後に、Chrome拡張機能の案内が表示される。
案内は「導入しない」で閉じることができる。開発版では、Chromeの拡張機能画面で
デベロッパーモードをオンにし、「パッケージ化されていない拡張機能を読み込む」から
プロジェクト内の`extension`フォルダを選択する。

初期設定のデバッグ表示は次で起動できる。初期設定画面からChrome拡張の案内も表示できる。

```powershell
.\dist\Sparkle.exe --debug-setup
```

Chrome拡張の案内だけを確認したい場合は次を使う。

```powershell
.\dist\Sparkle.exe --debug-extension-guide
```

## exe ビルド

依存パッケージと PyInstaller を仮想環境へインストールしたあと、次を実行する。

```powershell
.\build_exe.bat
```

`dist\Sparkle.exe` に単一 exe が生成される。ビルドスクリプトはプロジェクト内の
`.venv313` を優先し、無ければ `.venv` を使用する。

## Tailscale経由でスマホから使う場合

サーバー本体は安全のため `127.0.0.1:8000` で待ち受けたまま、Tailscale Serveで
Tailscale内だけにTCP転送する。

1. PCでSparkleを起動する。
2. PCで次を実行する。

```powershell
tailscale serve --bg --tcp=8000 tcp://127.0.0.1:8000
```

3. スマホで、Tailscale管理画面に表示されるPCのデバイス名を使い、次を開く。

```text
http://<PCのデバイス名>.<tailnet名>.ts.net:8000/Home
```

このポートは通常のHTTPなので、URLは `https://` ではなく `http://` で開く。
設定確認は `tailscale serve status`、この転送だけの停止は次で行える。

```powershell
tailscale serve --tcp=8000 tcp://127.0.0.1:8000 off
```

## データモデル

- **clips**: id, url, title, thumbnail_url, comment, category_id(FK), is_favorite, embedding(BLOB), created_at
- **categories**: id, name (UNIQUE)
- **tags**: id, name (UNIQUE)
- **clip_tags**: clip_id(FK), tag_id(FK)  — 多対多の中間テーブル

カテゴリは 1 クリップにつき 1 つ。タグは複数可。

## API 仕様

### Categories

| Method | Path | 説明 |
|--------|------|------|
| GET | `/categories` | カテゴリ一覧 |
| POST | `/categories` | カテゴリ作成。`body: {"name": "..."}` |

### Tags

| Method | Path | 説明 |
|--------|------|------|
| GET | `/tags` | タグ一覧 |
| POST | `/tags` | タグ作成。`body: {"name": "..."}` |

### Clips

| Method | Path | 説明 |
|--------|------|------|
| POST | `/clips` | クリップ作成 |
| GET | `/clips` | 一覧 (カテゴリ・タグでフィルタ可) |
| GET | `/clips/{id}` | 単一取得 |
| PUT | `/clips/{id}` | コメント・タグ・カテゴリ編集 |
| DELETE | `/clips/{id}` | 削除 |
| PATCH | `/clips/{id}/favorite` | お気に入り ON/OFF 切り替え |

#### POST /clips

```json
{
  "url": "https://example.com/article",
  "title": "Example Article",
  "thumbnail_url": "https://example.com/thumb.png",
  "comment": "あとで読む",
  "category": "tech",
  "tags": ["ai", "reading"]
}
```

- `category` / `tags` は**名前で指定**する。存在しない場合は自動作成される (ID 不要)。
- 事前に `/categories` や `/tags` で登録しておく必要はない。

#### GET /clips (フィルタ)

- `?category=tech` でカテゴリ名絞り込み
- `?tag=ai` でタグ名絞り込み
- 両方指定可 (AND 条件)

#### PUT /clips/{id}

```json
{
  "comment": "更新コメント",
  "category": "news",
  "tags": ["ml"]
}
```

- 全フィールド任意。指定されたフィールドのみ更新。
- `tags` を指定するとタグが丸ごと差し替えられる (名前指定・自動作成)。

#### PATCH /clips/{id}/favorite

現在の値を反転させる。レスポンス: `{"id": 1, "is_favorite": true}`

### レスポンス例 (ClipOut)

```json
{
  "id": 1,
  "url": "https://example.com/article",
  "title": "Example Article",
  "thumbnail_url": "https://example.com/thumb.png",
  "comment": "あとで読む",
  "category_id": 1,
  "is_favorite": false,
  "created_at": "2026-07-20T12:00:00",
  "tags": [{"id": 2, "name": "reading"}, {"id": 3, "name": "ai"}]
}
```

## 備考

- サーバーは PC ローカル (localhost) での利用を前提としている。
- 外部設定ファイルや複雑な依存関係を避け、単一 exe にまとめてもデータを
  アプリ本体の外へ保存できる構成にしている。


## AI向けMarkdownエクスポート

データベースが変更されると、次のフォルダへAIツール向けのMarkdownスナップショットを自動保存します。自動更新は常に有効です。

`%USERPROFILE%\Documents\Sparkle\ai-export\`

主なファイルは次のとおりです。

- `README.md` / `index.md`: 使い方と全体の入口
- `all.md`: クリップ、メモ、タスク、プロジェクトをまとめた全文
- `clips.md` / `notes.md` / `tasks.md` / `projects.md`: 種類別のデータ
- `taxonomy.md`: カテゴリ、タグ、関連付けの一覧

ClaudeのFileSystemMCPではこのフォルダを読み取り対象にし、OpenCodeでは同フォルダのMarkdownを参照させてください。通常のClaude、ChatGPT、Geminiでは、必要なMarkdownファイルをチャットへアップロードして利用できます。埋め込みベクトルやアプリ内部の絶対パスなど、AIに不要な内部情報は出力しません。
