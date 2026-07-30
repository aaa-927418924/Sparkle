# AI Clip Save API (backend)

個人用クリップ保存アプリのバックエンド。Chrome 拡張から送られた Web ページ情報
(URL・コメント・タグ・カテゴリ) を SQLite に保存し、Pinterest 風 UI から
一覧・検索できるようにするための CRUD API のみを提供する。

フロントエンド・拡張機能・AI 検索機能は含まない (将来の拡張ステップで別途実装)。

## 技術スタック

- Python 3.10+
- FastAPI
- SQLite (ファイルベース、追加インストール不要)
- uvicorn (開発用サーバー)
- pydantic

将来 fastembed による自然言語検索・タグ提案を追加することを想定し、
`clips` テーブルに `embedding` (BLOB) カラムをあらかじめ用意している。

## ファイル構成

```
db.py        SQLite 接続・スキーマ定義 (DB ファイルはプロジェクト直下の clips.db)
schemas.py   Pydantic のリクエスト/レスポンス定義
crud.py      カテゴリ・タグの get_or_create ヘルパー (将来拡張用)
routers.py   API エンドポイント定義
main.py      FastAPI アプリ起動・DB 初期化
requirements.txt
```

DB ファイルのパスは `db.py` の冒頭 `DB_PATH` で一元管理している。

## セットアップ

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 起動

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

起動時に自動で `clips.db` が作成 (テーブル初期化) される。
ブラウザで http://127.0.0.1:8000/docs を開くと Swagger UI で API 仕様を
確認・試行できる。

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
- 将来 PyInstaller で単一 exe にまとめることを想定し、外部設定ファイルや
  複雑な依存関係を避け、DB パスもコード内で固定管理している。
