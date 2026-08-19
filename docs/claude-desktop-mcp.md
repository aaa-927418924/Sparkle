# Claude DesktopからSparkleを使う

この初期実装は、Claude Desktopのローカルstdio MCPに限定した読み取り専用サーバーです。GUI本体とは別プロセスで動作し、既存のSQLite DBを`mode=ro`で開きます。DBへの書き込み、任意SQL実行、FastAPIの起動は行いません。

## 1. MCP SDKを実行環境へ入れる

Sparkleの既存GUI依存とは分離して、MCP用の依存関係を入れます。

```powershell
uv pip install --python .venv313\Scripts\python.exe -r requirements-mcp.txt
```

`uv`を使わない場合は、pipが使えるPython環境で`requirements-mcp.txt`をインストールし、そのPythonをClaude Desktopの`command`に指定してください。

## 2. Claude Desktopの設定

設定ファイルはWindowsでは通常`%APPDATA%\Claude\claude_desktop_config.json`です。既存の`mcpServers`を削除せず、下記の`"sparkle"`エントリを追加します。

```json
{
  "mcpServers": {
    "sparkle": {
      "command": "C:\\Users\\PC_User.DESKTOP-N70PB5O\\Documents\\OpenCode\\Sparkle\\.venv313\\Scripts\\python.exe",
      "args": [
        "C:\\Users\\PC_User.DESKTOP-N70PB5O\\Documents\\OpenCode\\Sparkle\\mcp_server.py"
      ]
    }
  }
}
```

別の場所にDBを置く場合だけ、同じエントリに次を追加します。通常は`APPDATA`から自動的に`%APPDATA%\Sparkle\clips.db`を選びます。

```json
"env": {
  "SPARKLE_DB_PATH": "C:\\path\\to\\clips.db"
}
```

設定保存後にClaude Desktopを完全に再起動します。Claude DesktopのMCPログは通常`%APPDATA%\Claude\logs\mcp.log`と`mcp-server-sparkle.log`で確認できます。

## 3. 使えるTool

- `search_clips` → `get_clip`
- `search_memos` → `get_memo`
- `search_tasks` → `get_task`
- `search_projects` → `get_project`
- `list_project_items`

検索結果はID、タイトル、概要、タグ、カテゴリ、プロジェクト、日時などの候補情報に絞っています。本文や関連情報が必要なときだけ、IDを使って`get_*`を呼び出してください。ページが続く場合は返却された`next_cursor`を同じ検索条件で渡します。

ローカルファイルの絶対パスは返しません。ローカルClipは`url: null`、`is_local: true`、ファイル名だけを返します。

## 4. 動作確認

Claude Desktop上で、例えば次のように確認できます。

```text
Sparkleで「Qwen」を検索して、候補のIDとタイトルだけ表示してください。
```

続けて、検索結果のIDを指定して詳細を取得します。

```text
先ほどのClip ID 1の本文、タグ、所属プロジェクト、関連タスクを取得してください。
```

データベースが見つからない場合は、MCP設定の`env.SPARKLE_DB_PATH`を確認してください。ログへ本文や検索引数は出さず、予期しない例外はサーバー側ログに種類だけを記録します。

## 今回の範囲外

Remote MCPのHTTPS公開、OAuth/Token認証、書き込みTool、GUI EXEへのMCP同梱はまだ有効化していません。`sparkle_mcp.service.ToolService`と`ReadRepository`はtransportから分離しているため、次フェーズでStreamable HTTPと認証を追加できます。
