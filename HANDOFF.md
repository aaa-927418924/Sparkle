# AI Clip Save App — 引継ぎ書

## プロジェクト概要

**AI Clip Save** は、完全ローカル（オフライン）で動作する個人向けクリップ保存アプリケーション。
Chrome 拡張機能から Web ページを保存・管理できる。fabric.so ライクな Pinterest 風 UI。

- **保存対象**: URL・タイトル・サムネイル・コメント・タグ・カテゴリ・お気に入り
- **管理機能**: 検索・カテゴリ/タグ/お気に入りフィルター・プロジェクト管理・タスク管理・Markdown ノート
- **ファイル**: ローカルファイルのアップロード（コピー or 参照）、動画サムネイル自動生成（ffmpeg）
- **Chrome 拡張機能**: 現在のページ情報取得、スクリーンショット範囲選択によるサムネイル作成、タグ履歴

---

## 技術スタック

| 層 | 技術 |
|---|---|
| バックエンド | Python 3.10+ / FastAPI + uvicorn |
| データベース | SQLite (`%APPDATA%\AIClipSaveApp\clips.db`) |
| フロントエンド | Vanilla HTML / CSS / JS（ビルド不要） |
| Chrome 拡張機能 | Manifest V3（service worker + content script + popup） |
| exe ビルド | PyInstaller（onefile, noconsole） |
| システムトレイ | pystray + PIL |
| サムネイル | Pillow, ffmpeg（動画） |
| エディタ | marked.js（Markdown レンダリング） |

---

## プロジェクト構造

```
AI-clip-save-app/
├── main.py                 # FastAPI エントリポイント（開発用）
├── app_entry.py            # exe エントリポイント（トレイ＋uvicorn）
├── db.py                   # SQLite スキーマ・マイグレーション
├── schemas.py              # Pydantic モデル
├── routers.py              # 全 API ルート（~1150行）
├── crud.py                 # カテゴリ・タグの get_or_create
├── paths.py                # パス解決（appdata / resource / exe）
├── maintenance.py          # タスク期限切れ・サムネイル削除の定期処理
├── ffmpeg_bootstrap.py     # ffmpeg 自動ダウンロード
│
├── frontend/               # SPA（FastAPI が静的に配信）
│   ├── index.html          # ホーム（クリップ一覧）
│   ├── notes.html          # ノート＋タスク一覧
│   ├── note-editor.html    # ノート編集
│   ├── projects.html       # プロジェクト一覧
│   ├── app.js              # ホームページロジック
│   ├── notes.js            # ノート＋タスクロジック
│   ├── note-editor.js      # ノートエディタロジック
│   ├── projects.js         # プロジェクトロジック
│   ├── pins.js             # ピン・サイドバー・設定・テーマ（共通）
│   ├── search-history.js   # 検索履歴（共通）
│   ├── style.css           # 全スタイル
│   └── icons/              # SVG アイコン
│
├── extension/              # Chrome 拡張機能
│   ├── manifest.json       # MV3
│   ├── background.js       # スクショ連携
│   ├── content.js          # 範囲選択オーバーレイ
│   ├── popup.html          # 保存フォーム
│   ├── popup.js            # 保存フォームロジック
│   ├── popup.css           # 保存フォームスタイル
│   └── icons/              # 拡張機能アイコン
│
├── build_exe.bat           # exe ビルドスクリプト
└── requirements.txt        # Python 依存関係
```

---

## データベース（SQLite）

`clips.db` は `%APPDATA%\AIClipSaveApp\` に自動生成される。

**主要テーブル**: `clips`, `categories`, `tags`, `clip_tags`, `projects`, `tasks`, `notes`, `note_clips`, `settings`

テーブル定義の詳細は `db.py` の `_migrate()` 関数参照。

---

## API 概要

全エンドポイントは `routers.py` に定義。`/` 以下にマウント。

| Method | Path | 用途 |
|--------|------|------|
| GET/POST | `/categories` | カテゴリ一覧・作成 |
| GET/POST | `/tags` | タグ一覧・作成 |
| GET/POST | `/clips` | クリップ一覧・作成 |
| PUT | `/clips/{id}` | クリップ更新（partial。`model_fields_set` で判定） |
| DELETE | `/clips/{id}` | クリップ削除＋ファイル後片付け |
| PATCH | `/clips/{id}/favorite` | お気に入りトグル |
| POST | `/clips/local` | ファイルアップロード |
| GET/POST/PUT/DELETE | `/projects/**` | プロジェクト CRUD |
| GET/POST/PUT/DELETE | `/tasks/**` | タスク CRUD |
| GET/POST/PUT/DELETE | `/notes/**` | ノート CRUD |
| GET/PUT | `/settings/{key}` | 設定読み書き |
| POST | `/uploads/thumbnail` | Base64 サムネイルアップロード |
| POST | `/dialog/open-files` | ネイティブファイル選択ダイアログ |

**静的マウント**: `/uploads` → アップロードファイル実体、`/` → frontend/

---

## 会話の要約（完了した修正）

### 1. タグ入力のドロップダウン改善（拡張機能 popup）

**問題**: `<datalist>` を使っていたが、ブラウザごとに表示が異なり操作性が悪い。

**対応**:
- datalist → 独自の `.suggest-list`（絶対配置のカスタムドロップダウン）に置き換え
- 入力と同時に前方/部分一致フィルター
- ↑↓EnterTabEscape キーボード操作対応
- 右クリックで候補を閉じてフォーカス解除

### 2. タグ履歴機能（拡張機能 popup）

**問題**: すべての既存タグがアルファベット順に出るだけで、よく使うタグが優先されない。

**対応**:
- `chrome.storage.local` に使用済みタグ履歴を保存（新しい順、最大 50 件）
- サジェストのソースを全タグ → 履歴のみに変更
- 履歴にないタグを入力しても初回使用時に自動記録
- バックエンド再起動・ブラウザ再起動で消えない

### 3. サジェストの表示位置とポップアップサイズ

**問題**: 候補がポップアップ枠をはみ出して見えなかったり、Chrome の 800x600 制限でポップアップ全体がスクロールしたりする。

**対応**:
- 枠内に収まるよう表示件数を動的計算（`window.innerHeight - inputBottom`）
- 項目の高さを調整し、`overflow: hidden` でスクロールバー完全非表示
- ラベル (`for="..."`) のクリックでフォーカスが移る問題を修正（`for` 属性削除）

### 4. YouTube サムネイル取得

**問題**: YouTube でおすすめ動画に SPA 遷移したとき `og:image` が前の動画のまま残り、古いサムネイルが表示される。また一部の動画で `maxresdefault.jpg` が存在せずグレーのデフォルトサムネイルになる。

**対応**:
- `getYouTubeThumbnail(url)` を `getOgImage()` より優先（URL から video ID を抜いてサムネイル URL 生成）
- `maxresdefault.jpg` 読み込み後 `naturalWidth <= 120` なら `hqdefault.jpg` にフォールバック

### 5. クリップタイトル編集（frontend + backend）

**問題**: 編集モーダルにタイトルフィールドがなく、保存後にタイトルを変更できない。

**対応**:
- `schemas.py`: `ClipUpdate` に `title: Optional[str] = None` 追加
- `routers.py`: `update_clip` に `title` の UPDATE 処理追加
- `frontend/index.html`: 編集モーダルのタイトル直下に `#editTitle` input 追加
- `frontend/app.js`: `editEls` に `title` 追加、`openEditModal` で値をセット、save 時に payload に含める

---

## 拡張機能 タグ入力の動作フロー

```
入力欄フォーカス/クリック → renderTagSuggest("")
  ↓
履歴一覧が表示（使用済みタグのみ、新しい順、最大7件）
  ↓
クリックまたは Enter で選択 → addTag(name) → closeTagSuggest()
  ↓
入力欄にフォーカスが残ったまま履歴が非表示
  ↓
入力欄をもう一度クリック → click イベント → renderTagSuggest("") → 再表示
```

- 枠外クリック → `document mousedown` で検出 → `closeTagSuggest()`
- 右クリック → `contextmenu` で検出 → `blur()` + `closeTagSuggest()`
- 履歴データは `chrome.storage.local` に永続化（`recordTagHistory()`）

---