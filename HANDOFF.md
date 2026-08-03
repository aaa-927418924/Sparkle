# Sparkle 開発引継ぎ書

最終更新: 2026-08-03（現行ブランチ確認時点）

この文書は、`C:\Users\PC_User.DESKTOP-N70PB5O\Documents\OpenCode\Sparkle` の開発を OpenCode 側へ引き継ぐための現行仕様書です。UI、バックエンド、SQLite、Windows ネイティブ層、Chrome 拡張、移行、初期設定、ビルド、既知の注意点をまとめています。

## 0. 最初に確認すること

### 名前とリポジトリ

- 現在のアプリ名は **Sparkle**。
- 旧アプリ名は **AIClipSaveApp / AI Clip Save App**。
- 旧名称は移行互換のため意図的にコード内に残っている。`AIClipSaveApp` を全検索して無条件に削除してはいけない。
- リポジトリ実体: `C:\Users\PC_User.DESKTOP-N70PB5O\Documents\OpenCode\Sparkle`
- 旧フォルダ名 `AI-clip-save-app` は正式な作業場所ではない。絶対パスを固定しないこと。
- 現在のブランチ: `codex/native-windows-app`
- 引継ぎ書作成直前のソース側 HEAD: `5f0fa83 feat: add category history to extension`
- `Icon.png` は追跡対象。`Icon old.png`、`Icon old2.png`、`Icon old3.png`、`Icon old4.png` は旧アイコン比較用の未追跡ファイルで、コミットしない。

### アプリの目的

Sparkle は、Web ページの情報やローカルファイルをユーザー PC 内の SQLite に保存して整理する Windows ネイティブアプリ。Chrome 拡張から URL・タイトル・サムネイル・コメント・カテゴリ・タグ・お気に入りを保存し、アプリ側で検索、プロジェクト、タスク、Markdown メモを管理する。

基本方針:

1. データは原則ローカル保存。
2. FastAPI が localhost で API と静的 UI を配信し、pywebview/WebView2 がネイティブウィンドウとして表示。
3. フロントエンドは Vanilla HTML/CSS/JavaScript。npm 等のフロントビルドはない。
4. Chrome 拡張との標準通信先は `http://127.0.0.1:8000`。
5. 認証なしのローカルアプリなので、既定の localhost bind を広域公開しない。別端末から使う場合は README の Tailscale Serve 方式を使う。

重要なUI方針:

- ダークテーマ固定。テーマ切替ボタンは削除済み。
- Windows 標準タイトルバーは使わず、frameless window + 独自タイトルバー。
- 閉じるボタンは終了ではなくタスクトレイへ隠す。完全終了はトレイメニュー。
- Ctrl/Cmd + ホイール等の WebView ズームは無効。表示倍率は100%固定。
- ブラウザ標準の autocomplete/保存候補は全画面で無効化。
- 削除、設定リセット、履歴削除、重複アップロード確認は独自ポップアップ。ブラウザ標準 confirm を使わない。
- ファイルドロップを受け付けるのはホーム（index.html）のみ。その他のページは drop をキャンセルする。

## 1. 全体構成

    Chrome 拡張
      popup.html/js ─────┐
      content.js         ├─ HTTP JSON → FastAPI (main.py / routers.py)
      background.js ─────┘                 │
                                           ├─ SQLite: %APPDATA%\Sparkle\clips.db
                                           ├─ uploads: %APPDATA%\Sparkle\uploads\
                                           └─ AI export: Documents\Sparkle\ai-export\
                                                    ▲
    Sparkle.exe ← app_entry.py ← pywebview/WebView2

### 起動経路

1. `start.bat` が `dist\Sparkle.exe` を探す。
2. exe があれば exe、無ければ `.venv313` → `.venv` の Python で `app_entry.py` を起動。
3. `app_entry.py` が DPI Awareness V2、Uvicorn、WebView2、独自タイトルバー、トレイを初期化。
4. `/health` が応答してから WebView を開く。
5. `/Home` が移行、初期設定、移行後案内の状態を見てページを決める。

開発 API/UI のみ確認する場合:

    uvicorn main:app --reload --host 127.0.0.1 --port 8000

ブラウザで `http://127.0.0.1:8000/Home`。native window、トレイ、DPI、ネイティブファイルパス bridge を確認する時は `start.bat` または exe を使う。

## 2. リポジトリ構造

    Sparkle/
    ├─ main.py                    # FastAPI、静的ページ、起動初期化
    ├─ app_entry.py               # Windows native 起動、pywebview、トレイ、DPI
    ├─ db.py                      # SQLite 接続、schema、段階的 migration
    ├─ migration.py               # AIClipSaveApp → Sparkle 移行
    ├─ setup.py                   # 初期設定/移行後 onboarding marker
    ├─ paths.py                   # パス解決
    ├─ routers.py                 # CRUD、ファイル、backup/import、設定 API
    ├─ schemas.py                 # Pydantic 入出力型
    ├─ crud.py                    # get-or-create 等
    ├─ maintenance.py             # 自動削除/孤立サムネイル掃除
    ├─ ai_export.py               # AI向け Markdown 自動生成
    ├─ ffmpeg_bootstrap.py        # ffmpeg 非同期取得
    ├─ build_exe.bat
    ├─ Sparkle.spec
    ├─ start.bat
    ├─ reset_for_migration_test.bat
    ├─ reset_for_new_user_test.bat
    ├─ requirements.txt
    ├─ README.md
    ├─ Icon.png
    ├─ frontend/
    │  ├─ index.html / app.js          # ホーム・クリップ
    │  ├─ notes.html / notes.js        # タスク・メモ
    │  ├─ note-editor.html / .js       # Markdown メモ編集
    │  ├─ projects.html / projects.js  # プロジェクト
    │  ├─ settings.html                # 設定ページ
    │  ├─ pins.js                      # 共通サイドバー/設定/ピン
    │  ├─ codex-shell.js/.css          # native bridge/共通挙動
    │  ├─ style.css                    # 共通CSS
    │  ├─ home-figma.css
    │  ├─ notes-figma.css
    │  ├─ page-transition.js
    │  ├─ search-history.js
    │  ├─ migration.* / setup.* / extension-guide.*
    │  ├─ vendor/marked.min.js
    │  └─ icons/
    └─ extension/
       ├─ manifest.json                # Manifest V3
       ├─ popup.html/js/css
       ├─ background.js
       ├─ content.js
       ├─ options.html/js
       └─ icons/

`build/`、`dist/`、`uploads/`、DB、ログ、`extension.zip` は `.gitignore` 対象。生成物の有無を Git のソース変更と混同しない。

## 3. パスと rename 互換

### 現在の保存先

`paths.py` の `APP_NAME = "Sparkle"` が基準。

    %APPDATA%\Sparkle\
    ├─ clips.db
    ├─ uploads\local\              # copy 保存ファイル
    ├─ uploads\thumbnails\         # 生成サムネイル
    ├─ bin\ffmpeg.exe               # 必要時に自動取得
    ├─ webview\                     # WebView2 cache/storage
    ├─ app.log
    └─ stdio.log

    %USERPROFILE%\Documents\Sparkle\ai-export\
    ├─ README.md
    ├─ index.md
    ├─ all.md
    ├─ clips.md
    ├─ notes.md
    ├─ tasks.md
    ├─ projects.md
    └─ taxonomy.md

### 旧保存先と残すべき文字列

    %APPDATA%\AIClipSaveApp\
    %USERPROFILE%\Documents\AIClipSaveApp\

`migration.py` は旧 DB、旧 Documents、旧 backup（`AIClipSaveApp-backup-*.zip`）、旧 DB（`AIClipSaveApp-*.db`）、旧 exe、旧 Windows Run キー `AIClipSaveApp` を検出する。これらの文字列を新名称へ無条件に置換すると移行不能になる。

新しく作るものは `Sparkle` 名を使う。新 backup は `Sparkle-backup-...zip`、exe は `Sparkle.exe`、Run キーも `Sparkle`。

起動時には現行 `%APPDATA%\Sparkle` や uploads 階層だけが自動生成されることがある。`migration.py` は空の `uploads\local`/`thumbnails`、WebView2 の `webview` 等を実ユーザーデータ競合から除外するため、空フォルダだけなら移行を進められる。

## 4. SQLite (`db.py`)

DB パスは `%APPDATA%\Sparkle\clips.db`。必ず `get_connection()` を使う。

接続の特徴:

- `check_same_thread=False`。
- `PRAGMA foreign_keys=ON`。
- `sqlite3.Row`。
- `TrackedConnection` が書き込み commit 後に `ai_export.request_export()` を呼ぶ。
- rollback で dirty 状態を解除。

主なテーブル:

- `categories(id, name UNIQUE)`
- `tags(id, name UNIQUE)`
- `clips(id, url, title, thumbnail_url, comment, category_id, is_favorite, embedding, created_at, clip_type, file_ref, file_size, project_id)`
- `clip_tags(clip_id, tag_id)`
- `tasks(id, title, is_done, clip_id, created_at, due_date, priority, completed_at, project_id)`
- `notes(id, title, body, created_at, updated_at, task_id, project_id)`
- `note_clips(note_id, clip_id)`
- `task_notes(task_id, note_id)`
- `projects(id, name, description, is_done, done_snapshot, created_at)`
- `project_clips(project_id, clip_id)`
- `project_notes(project_id, note_id)`
- `settings(key, value)`

現在はリンクテーブルが多対多の正規経路。ただし旧互換の `clips.project_id`、`tasks.project_id`、`notes.project_id`、`notes.task_id` も残っているため、読み書きで両方を考慮する。

`_migrate()` は存在確認しながら次を追加してきた: notes.task_id、tasks の期限/優先度/完了日時、clips の local file 情報、task/note/project の project_id、リンクテーブル、旧単一値のリンクテーブルへのコピー、インデックス。既存DBの列削除・再作成は避ける。

## 5. FastAPI / API

### モジュール責務

- `main.py`: FastAPI、CORS、静的ファイル、ページルート、起動初期化。
- `routers.py`: ほぼ全業務 API、Windows picker、ローカルファイル、ZIP。
- `schemas.py`: Pydantic。
- `maintenance.py`: 完了タスク自動削除（3日/1週間/1か月/なし）、孤立サムネイル。
- `ai_export.py`: read-only DB から Markdown。
- `setup.py`: `.initial-setup-complete.json` と `.post-migration-onboarding.json`。
- `migration.py`: 旧名称からの安全な移行。

### エンドポイント一覧

共通:

- `GET /health`
- `POST /app/activate`
- `GET /migration/status`, `POST /migration/run`
- `GET /setup/status`, `POST /setup/complete`, `POST /setup/post-migration/complete`

カテゴリ/タグ:

- `GET/POST /categories`、`DELETE /categories/{id}`
- `GET/POST /tags`、`DELETE /tags/{id}`

クリップ:

- `GET/POST /clips`、`GET /clips/{id}`、`PUT /clips/{id}`、`DELETE /clips/{id}`
- `PATCH /clips/{id}/favorite`
- `POST /clips/local`（copy）、`POST /clips/local/reference`（absolute path reference）
- `GET /clips/{id}/path`、`GET /clips/{id}/file`
- `POST /clips/{id}/open`、`POST /clips/{id}/explorer`
- `GET /clips/{id}/text-preview`

ローカル clip URL は `local://copy/<stored-name>` または `local://reference/<absolute-path>`。copy は `%APPDATA%\Sparkle\uploads\local` に UUID+拡張子で保存。reference は元絶対パスを保持するだけなので元ファイル移動でリンク切れになる。画像は Pillow、動画は ffmpeg、テキストは先頭プレビュー。

プロジェクト:

- `GET /projects?done=true|false`
- `POST /projects`、`GET/PUT/DELETE /projects/{id}`
- `PATCH /projects/{id}/toggle`
- `POST/DELETE /projects/{project_id}/clips/{clip_id}`
- `POST/DELETE /projects/{project_id}/notes/{note_id}`

完了化時は未完了タスクを `done_snapshot` に保存して完了にし、取り消し時は snapshot のタスクだけ復元する。

タスク:

- `GET /tasks?done=...&project_id=...&exclude_project=...`
- `POST /tasks`、`GET/PUT/DELETE /tasks/{id}`、`PATCH /tasks/{id}/toggle`
- priority は 1〜5。期限、completed_at、clip/project link を扱う。

メモ:

- `GET /notes?project_id=...&exclude_project=...`
- `POST /notes`、`GET/PUT/DELETE /notes/{id}`
- `clip_ids`、`task_ids`、`project_ids` で複数リンク。旧 `task_id`/`project_id` も互換処理。

設定・AI export:

- `GET/PUT /settings/{key}`。
- `file_save_method`: `copy` / `reference`。
- `task_auto_delete`: `3d` / `1w` / `1m` / `never`。
- `ai_export_enabled`: true/false。無効化すると生成 Markdown/temp だけ削除し、DB/元データは保持。
- `GET /data/ai-export/status`、`POST /data/ai-export`、`POST /data/ai-export/open`。
- AI export の「今すぐ更新」UIは削除済みだが、手動 API は互換性のため残す。

DB/ZIP:

- `POST /data/export`、`POST /data/import`（DB snapshot/merge、import max 512MB）。
- `POST /data/export-backup`（DB + uploads、modern folder picker、atomic ZIP）。
- `POST /data/import-backup`（ZIP max 2GB、展開後 max 4GB、path traversal/symlink 検査）。
- import は現行設定を優先し、キー衝突で現在設定を上書きしない。

その他:

- `POST /uploads/thumbnail`
- `POST /dialog/open-files`（Windows 複数ファイル picker）
- `POST /maintenance/cleanup`
- `/uploads` → upload directory、`/` → frontend static。

backup/import 中はフロントの operation lock がポインタ・キーボード・ページ移動・beforeunload を止める。「アプリを閉じないでください」画面を消したり、途中リロードを許可しない。

セキュリティ: 認証なし/localhost 前提。reference の絶対パスは AI export に出さない。ZIP の安全検査を弱めない。

## 6. Windows ネイティブ層 (`app_entry.py`)

### サイズと DPI

- per-monitor DPI Awareness V2（fallback あり）。
- 通常: default `1510 x 820`、minimum `960 x 640`。
- Migration/Setup/ExtensionGuide: default `958 x 885`、minimum `720 x 560`。
- 作業領域と DPI に合わせて起動時に縮小するが、アスペクト比固定ではなく自由にリサイズ可能。
- onboarding 完了で通常プロファイルへ戻す。
- `SPARKLE_PORT` は有効な範囲ならポート変更、それ以外は8000。

### native window

- `frameless=True`, `easy_drag=False`, `resizable=True`, `zoomable=False`。
- custom titlebar に Sparkle アイコンと最小化/最大化/閉じる。
- 最大化中にタイトルバーまたはサイドバー空白をドラッグすると、最大化解除後にカーソル基準で復元位置へ置いて移動。
- sidebar 固定ボタン・小さい縦余白は drag 対象外、広い空白は drag 対象。
- `_enable_native_resize()` が frameless WebView に native resize style/frame を付与。
- close は hide。tray の「終了」のみ destroy + server stop。
- 二重起動なら既存 `/health` を検出し `/app/activate`、新プロセスは終了。

### file drop bridge / tray

- WebView2 の `postMessageWithAdditionalObjects` または pywebview DOM bridge で dropped file の絶対 path/name/size を受ける。
- 最新 drop のみを扱い、絶対パスを検証。
- tray icon は root `Icon.png`、失敗時 fallback。
- Run key は Sparkle。旧 Run key は migration で更新。

## 7. 共通フロントエンド

### `pins.js`

- localStorage key `pins`。item は `{id,type,order,name?,counts?}`、type は clip/note/project。
- `pins_ts` の storage event で別ページ/タブへ通知。
- metadata を先に保存してプレースホルダーちらつきを防ぐ。
- project は clip/task/note counts を表示。
- `window.refreshPinnedData(type,id)`、`refreshAllPinned()`、`refreshAllPinnedProjects()` で編集直後に sidebar/tooltip を更新。
- 右クリック「ピン止めを解除」は UI/localStorage を即時更新。
- 並べ替えは置換ではなく `pin-drop-before` / `pin-drop-after` の要素間線。
- native `title` tooltip は hydrated 後に削除し、独自 tooltip を使う。

設定の主な localStorage: `autoCreateNoteOnTask`、`autoCreateNoteOnProject`、`hideAutoCheatsheet`、`clipSearchHistory`、`clipSortMode`。

### `codex-shell.js`

- custom titlebar、native drag/resize、page profile。
- Ctrl/Cmd + wheel/key の zoom を抑止。
- 全 form/input/textarea/select に `autocomplete=off` を付け、MutationObserver でも監視。
- `window.appConfirm` / `window.confirmDeletion`。外側クリック、Escape、focus return、Shift+click immediate。
- modal focus trap。
- home 以外の file drop を capture phase でキャンセル。

modifier 選択は Shift/Ctrl/Meta。Shift+クリックは追加の単体選択、Shift+ドラッグは既存選択を保持した範囲選択。テキストボックス以外のテキスト選択は抑制。notes は task panel を選択対象外にし、memo のみ選択する。

## 8. 画面ごとの現行仕様

### ホーム (`index.html`, `app.js`)

- 検索、カテゴリ、星のお気に入り、ファイル追加、独自 sort（date/title/recent_opened/random）、クリップグリッド。
- クリップカードはサムネイル/ファイルアイコン/テキストプレビュー、タイトル、コメント、タグ、fav/edit/delete。
- local clip の open、Explorer 表示、ファイルパスコピー。
- 編集 modal はタイトル、サムネイル、コメント、カテゴリ、タグ。カテゴリ/タグは独自 combobox 候補を入力欄の上へ表示し、入力で部分一致。datalist は使わない。
- 複数選択、batch tag/category/delete。削除は独自 popover、Shift+削除は確認を省略。
- 1個のアップロードでも bulk tag/category を表示。
- 同名+同サイズのローカルファイルは独自 duplicate confirm。
- 保存ボタンは保存中 `保存中…` + disabled。
- 保存後 `loadAll()`、extension 保存も focus/visibility/periodic refresh で reload 不要。
- index のファイル drop overlay は「ここにドロップしてアップロード」。reference は native bridge、copy は FileList。
- `clipSortMode` は初期 inline script でリロード直後の並び替えちらつきを抑える。
- `page-enter-card` はカード用。検索/フィルター/新規操作に不要な entry animation を付けない。

### タスク・メモ (`notes.html`, `notes.js`)

- sidebar 表示は「タスク・メモ」。上部は `すべて`、`進行中`、`完了済み`、`+ 新規メモ`。
- task: priority stars、完了、期限、関連 clip/note。最優先ハイライトは常時ON、設定項目は削除。
- task edit から project 項目は削除。project 側から task を紐づける。
- task panel は範囲選択不可。`メモを紐づけ` は複数 checkbox。
- task 作成時の同名空 memo は `autoCreateNoteOnTask=true` の時だけ。
- memo card は open、hover 時に pin/delete を横並び表示。memo hover 上移動アニメーションは最新状態で無効。
- top row clipping 対策は memo 上部に余白を足すのではなく topbar/overflow 側で行った。再修正時も見た目の空白を増やさない。
- 選択 memo は orange border。batch delete/duplicate。duplicate は本文、clip/task/project link を保持し `（コピー）`。
- memo の初回表示はカードだけフェードイン。filter/new memo は対象外。

### メモ編集 (`note-editor.html`, `note-editor.js`)

- `/Note` 新規、`/Note?id=...` 既存。
- title input + Markdown textarea、`テキスト編集`/`プレビュー表示`。
- marked.js、裸 URL の autolink、新しいタブの link。
- toolbar: bold/italic/strike/mark/H1-H3/UL/OL/code/codeblock/quote/hr/link/help。
- Ctrl+Z / Ctrl+Shift+Z、Ctrl+E。
- localStorage `note-editor-draft:<id|new>` に draft。新規は title 空なら DB 保存せず draft を維持。
- autosave debounce 約650ms。成功後 note pin と project pins を更新。
- 削除ボタンと「クリップを貼り付け」は削除済み。
- edit/preview で textarea のサイズを変えない。ページ/textarea/preview の scrollbar は非表示。
- Markdown cheat sheet は初回自動表示、`hideAutoCheatsheet` で次回以降を抑止。

### プロジェクト (`projects.html`, `projects.js`)

- 上部は `すべて`、`進行中`、`完了済み`、`+ 新規プロジェクト`。
- card は name/description/linked clip album/counts/done/pin/edit/delete。
- 初回の project card のみ順番にフェードイン。ボタン/フィルターは対象外。
- pending class で detail reload 時の list button flash を抑止。scrollbar は非表示。
- `?id=...` 詳細で clip/task/note の3セクション。
- clip picker は検索/カテゴリ/タグ。category を tag として重複表示しない（trim + case-insensitive Set）。
- task は既存 link または project-only 新規、期限、priority。
- note は既存 link または title/body から新規。
- project done は backend snapshot。変更後は `refreshProjectPin()`。
- project card は Shift/Ctrl/Meta 選択、複製、削除。
- project 作成時の同名空 memo は `autoCreateNoteOnProject=true` の時だけ。

### 設定 (`settings.html`, `pins.js`)

モーダルではなく他ページと同じ full page。縦配置なので小さい幅でも横スクロールを発生させない。

設定:

- file save: copy/reference
- search history 全削除
- task auto delete
- task/project 作成時の同名空メモ
- DB/ZIP export/import
- AI export enable/disable、status、folder open
- reset all settings

設定 UI から削除済み: AI Markdown 自動更新の on/off、最優先タスク highlight の on/off、AI export の「今すぐ更新」。機能はそれぞれ常時ON/自動更新。

AI export を ON→OFF にする時は生成 Markdown 削除確認を独自 popup で表示。DB/元データは保持する。backup/import は operation lock でリロード等を止める。検索履歴削除・reset も独自 popup。

注意: `pins.js` の設定リセット側は file_save_method を `copy` に戻す実装があり、`setup.py`/`maintenance.py` の初期既定 `reference` と不一致の可能性がある。仕様としてどちらを採用するか OpenCode で確認する。

## 9. 移行・初期設定・拡張案内

### 遷移順

`/Home` は、migration required → `/Migration`、初回 setup required → `/Setup`、migration 後 marker → `/Setup` → `/ExtensionGuide`、それ以外 → home の順に判定する。

### migration (`migration.py`)

検出対象は旧 AppData、旧 Documents export、Documents/Downloads/プロジェクトルート/dist/exe 近辺の旧 backup/db/exe、旧 Run key。DB integrity を検査し、現行側に実データがあれば競合で停止する。自動生成された空の Sparkle フォルダ、空 uploads、WebView2 runtime は除外する。

成功時:

- DB/ファイルを検証しながら copy。
- 旧 Markdown のブランド名を Sparkle に置換。
- backup は Sparkle 名へ rename（上書きしない）。旧 exe は remove 扱いの場合がある。
- Run key を Sparkle へ更新。
- `.migration-complete.json` を書き、post-migration onboarding を開始。
- 失敗時は現行側のコピーを掃除し、旧側を可能な限り保持。

「Sparkle側に既存データがあるため安全に実行できません」は `%APPDATA%\Sparkle\clips.db`、uploads の実体、既存 export 等の競合を意味する。空階層だけなら現在の判定で移行可能。

### setup (`setup.py`)

- `%APPDATA%\Sparkle\.initial-setup-complete.json`
- `%APPDATA%\Sparkle\.post-migration-onboarding.json`
- file_save_method 初期 `reference`
- task_auto_delete 初期 `1w`
- ai_export_enabled 初期 true
- autoCreateNoteOnTask/Project は frontend localStorage

移行ユーザーにも初期設定/拡張案内を表示する。移行後は「設定を確認しましょう」「拡張機能を更新しましょう」というニュアンスにする。

デバッグ引数:

- `Sparkle.exe --debug-setup`
- `Sparkle.exe --debug-extension-guide`

通常ユーザー向け画面に「開発用デバッグ表示」を出さない。

### Extension guide

Chrome の制約により、外部アプリが developer mode の unpacked extension を完全自動インストールすることはできない。案内画面で、ダウンロードした `extension` フォルダを `chrome://extensions` の「パッケージ化されていない拡張機能を読み込む」から選ぶ。skip は強制しない。

現行文言の方針:

- 「ダウンロードした extension フォルダを選択すると、Sparkle 拡張機能が追加されます。」
- 初期設定のボタンは `次へ`。
- 拡張案内は `導入しない` と `Sparkleを始める`。

## 10. Chrome 拡張

`extension/manifest.json` は MV3。activeTab/storage/scripting 等と localhost host permission、service worker、content script、options page を使う。

保存フロー:

1. active tab の URL/title/OG image 等を取得。
2. scripting でページ情報を補完。
3. popup で comment/category/tags/favorite を編集。
4. `POST /clips`、サムネイルがあれば `/uploads/thumbnail`、favorite は patch。
5. 成功後に popup を閉じ、アプリ側の focus/visibility refresh でリロードなし反映。

タグ履歴:

- `chrome.storage.local.tagHistory`。
- タグチップ追加時に記録、新しい順、最大50、重複は先頭へ移動。
- 独自候補リスト、入力フィルター、Arrow/Tab/Enter/Escape、枠外 close。

カテゴリ履歴（最新 `5f0fa83`）:

- API `/categories` と `chrome.storage.local.categoryHistory` を統合。履歴を先にして完全一致重複排除。
- 入力の部分一致。候補は popup 下端で見切れないよう入力欄の上。
- 残り高さに応じて表示、最大7件程度。
- 入力/下書きでは履歴を書き換えない。`POST /clips` が成功した後に保存カテゴリを履歴の先頭へ追加。最大50。
- popup の標準 autocomplete/datalist は使わない。

タグとカテゴリで履歴更新タイミングが異なる点は現行仕様。統一する場合は回帰テストが必要。

スクリーンショットは content.js の範囲選択、background.js のキャプチャ/受け渡し、popup の pending draft/thumbnail を使う。

## 11. AI Markdown

`ai_export.py` は read-only (`mode=ro`, `query_only`) で DB を読み、README/index/all/clips/notes/tasks/projects/taxonomy を atomic temp→replace で生成する。タイトル、コメント、タグ、カテゴリ、favorite、関連関係を含むが、local clip の絶対パスは出さない。

- dirty DB commit 後に約1秒 debounce。
- `ai_export_enabled=false` は timer を止め known Markdown/temp だけ削除。DB、uploads、元データは残る。
- DB を直接書く新機能は `TrackedConnection` の commit 経路を使う。

## 12. ffmpeg

`ffmpeg_bootstrap.py` は PATH の ffmpeg を優先。無ければ gyan.dev の static zip を daemon thread でダウンロードし、`%APPDATA%\Sparkle\bin\ffmpeg.exe` に保存。失敗してもアプリ起動は止めず、動画サムネイルだけ使えない。

## 13. 起動・ビルド・拡張テスト

### 依存環境

`requirements.txt`: fastapi, uvicorn, pydantic, python-multipart, Pillow, pystray, pywebview。Python 3.10+。Sparkle rename 前に作った uv venv は `uv trampoline failed to canonicalize script path` を起こすことがあるため、現フォルダで `.venv313` を作り直す。

### 起動

`start.bat` は `dist\Sparkle.exe` 優先、無ければ `.venv313`/`.venv` の `app_entry.py`。ソース起動は次の通り。

    .\.venv313\Scripts\Activate.ps1
    python app_entry.py

### ビルド

`build_exe.bat` は venv prefix を検証し、`pyinstaller --clean --noconfirm Sparkle.spec` を実行して `dist\Sparkle.exe` を作る。spec は `app_entry.py`、`frontend`、`Icon.png` を内包し、exe 名 `Sparkle`、icon `Icon.png`、console=False。

起動中の exe は上書きできない。置換前に対象のフルパスが `...\dist\Sparkle.exe` であることを確認して、そのプロセスだけ終了する。別 Sparkle や別アプリをプロセス名だけで一括終了しない。

### 拡張の読み込み

`chrome://extensions` → developer mode → unpacked extension を読み込む → `...\Sparkle\extension`。ソース変更後は拡張カードの Reload。Chrome の完全自動インストールは不可。

## 14. 回帰テスト

最低限:

1. start.bat、トレイへ隠す/再表示/完全終了。
2. Windows 100/150/175% で通常画面と onboarding が画面内に収まる。
3. 最大化→タイトルバー/サイドバー空白ドラッグでカーソル位置に復元、resize 枠も動く。
4. index の URL、copy/reference file、path copy、duplicate confirm、保存中表示、home drop。
5. index 以外への file drop で OS の「開く」を出さない。
6. notes の task→複数 memo checkbox、memo Shift/Ctrl 選択、複製、pin、削除。
7. Note editor の Markdown、preview、autosave、draft、scrollbarなし。
8. projects の CRUD、clip/task/note link、カテゴリ/タグ重複なし、done snapshot、複製/複数選択。
9. settings の AI export toggle、削除確認、ZIP backup/import、operation lock、history clear、reset。
10. Chrome popup の tag/category 候補。カテゴリは保存成功時だけ履歴に入る。
11. ページ移動/reload 後に pins の名前、project counts、tooltip がプレースホルダーに戻らない。

## 15. 移行テスト用 BAT

`reset_for_migration_test.bat` は確認付きで current Sparkle data/export と legacy data/export を削除し、空の旧 AppData/Documents フォルダを作る。空フォルダだけでは migration は発生しないため、旧 DB、旧 backup、旧 exe 等を別途用意する。外部の backup ZIP/DB は削除しない。

`reset_for_new_user_test.bat` は current/legacy data と export を確認付きで削除し、旧空フォルダは作らない。外部の backup ZIP、DB、旧 exe は残すので、それらがあれば migration が出るのは仕様。

どちらも Sparkle.exe が動作中なら削除しない。実データに使う前に ZIP export を作る。

## 16. 既知の注意点と今後の候補

1. `pins.js` の settings reset は file_save_method を `copy` に戻す箇所がある一方、`setup.py`/`maintenance.py` の初期既定は `reference`。仕様を統一するか確認。
2. AI export の手動 API は残るが、UI の「今すぐ更新」は削除済み。
3. `note-editor.js` の Markdown toolbar には prompt を使う action がある。削除確認用の標準ダイアログに戻さない。
4. WebView2 `webview` は migration conflict 判定から除外する。
5. reference file の移動/削除、copy file の削除条件、175% DPI の native picker/titlebar/resize を実機回帰する。
6. HTML/JS/CSS を変更したら、末尾の `?v=...` cache-busting query を確認。特に `codex-shell.js`、`pins.js`、`notes-figma.css`、`note-editor.js`。

## 17. Git 作業ルール

変更前後に `git status --short`、`git diff`、`git diff --cached --check` を確認する。今回のようなソース以外の Markdown 変更では exe ビルドは不要だが、Python/HTML/CSS/JS を実装変更した場合は、動作確認後に build と commit を行う。

`Icon old*.png` は追加しない。build/dist は通常 Git 管理外。exe を更新しても source commit を忘れない。

直近の関連コミット:

    5f0fa83 feat: add category history to extension
    4e4bfa0 fix: align edit modal fields
    57570b9 fix: align clip edit suggestions
    d1d7ed4 feat: add clip edit suggestions
    9adcda2 feat: protect settings backup operations
    55eba60 fix: ignore WebView runtime data during migration
    5ef7e40 fix: reset onboarding tests and hide debug labels
    8cacbc0 chore: add data reset scripts for onboarding tests
    a67c018 feat: show post-migration onboarding
    2283530 feat: size onboarding window separately
    003de1d fix: enable scrolling on small setup windows
    7873c59 feat: add Chrome extension onboarding guide
    843ee4b fix: disable browser autocomplete across app
    38bda6e feat: add batch duplication for notes and projects

## 18. OpenCode の開始手順

1. 実体パスが `Documents\OpenCode\Sparkle` であることを確認。
2. `git status --short` と `git log --oneline -n 5` を確認。
3. `README.md`、この `HANDOFF.md`、`paths.py`、`app_entry.py`、`main.py`、`routers.py` を読む。
4. 実ユーザーデータを触る前に `%APPDATA%\Sparkle\clips.db` と `Documents\Sparkle\ai-export` のバックアップを確認。
5. UI 修正は関連 HTML/JS/CSS と cache-busting query を同時に確認。
6. 実装後は静的確認、手動回帰、Git diff check、必要なら build、commit。
7. 文章と実装が食い違う時の source of truth は `paths.py`、`db.py`、`setup.py`、`migration.py`、`routers.py`、該当 frontend の現行コード。
