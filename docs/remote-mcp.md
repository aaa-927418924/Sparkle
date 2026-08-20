# Sparkle Remote MCP

SparkleのLocal MCPとRemote MCPは同じ`build_server`、`ToolService`、読み取り専用Repositoryを使います。Remote側のTransportだけがStreamable HTTPに変わり、MCP専用の`/mcp`入口を追加します。SQL文を受け取るTool、書き込みTool、ローカルファイル公開はありません。

## 認証と公開URL

Remote MCPはOAuth 2.1 Authorization Code + PKCEをResource Serverと同じプロセスで提供します。WebクライアントがOAuth認証を開始すると、Sparkle設定画面で発行したMCP専用アクセスキーを入力する読み取り許可画面が表示されます。OAuthのauthorization code、access token、refresh tokenはメモリ上だけに保持し、ログや`mcp-auth.json`へ平文保存しません。スマホ・Web画面用の`remote-auth.json`とは別の認証系統です。

MCPの公開URLは、外部から見える`/mcp`まで含めて環境変数で指定します。

```powershell
$env:SPARKLE_MCP_PUBLIC_URL = "https://your-sparkle-host.example/mcp"
```

既存GUIの「外部Webアクセス」と設定画面の「Remote MCP」を有効にすると、Funnel Webモードでは同じリモートWeb gatewayの`/mcp`がHTTPS 443番で使えます。Web用とMCP用のアクセスキーは別です。ChatGPT Web、Claude Web、Claude DesktopのRemote Connectorには、設定画面に表示された`https://.../mcp`を指定してください。`RemoteAccessManager.status()`にも`web_route`、`mcp_route`、`mcp_url`を返します。

Web公開方式をServeにすると、Android/Tailscale接続端末は443番のServeから利用し、Remote MCPだけが8443番のFunnelで外部公開されます。この場合のMCP URLは`https://...:8443/mcp`です。FunnelとServeは同じポートを共有できないため、方式切り替え時にMCPの公開ポートも切り替わります。

## MCP専用アクセスキー

デスクトップアプリの設定 → 外部Webアクセス → Remote MCPで「Remote MCPを有効にする」を押すと、MCP専用アクセスキーが一度だけ表示されます。ChatGPT Web、Claude Web、Claude DesktopのRemote ConnectorのOAuth画面には、このMCP専用キーを入力してください。スマホアプリ/Web画面に使うWeb公開用アクセスキーは入力しません。

キーを紛失した場合は「MCPアクセスキーを再発行」を押します。再発行または「接続をすべて解除」を実行すると、Remote MCPのOAuthクライアント・認証コード・アクセストークン・リフレッシュトークンが破棄され、MCPクライアントは再認証が必要になります。Web画面のログインセッションは影響を受けません。

`SPARKLE_MCP_TOKEN`を設定した場合は、OAuthを使わずにBearer Tokenでも接続できます。これはローカル検証・固定Token運用向けです。16文字未満のTokenは拒否します。

```powershell
$env:SPARKLE_MCP_TOKEN = (python -c "import secrets; print(secrets.token_urlsafe(32))")
```

固定Tokenを使う場合のMCP URLは、クライアントがBearerヘッダーを設定できる必要があります。Claude WebとChatGPT Webのカスタム接続ではOAuth接続を優先してください。

## 単体Remote MCP Server

GUIのRemote Web gatewayを使わず、同梱コンソールEXEを別ポートで起動することもできます。リバースプロキシまたはTailscaleを`8002`へ向けてください。

```powershell
$env:SPARKLE_MCP_PUBLIC_URL = "https://your-sparkle-host.example/mcp"
.\dist\SparkleMCP.exe --transport streamable-http --host 127.0.0.1 --port 8002
```

通常のDB位置は`%APPDATA%\Sparkle\clips.db`です。別DBを読むテストでは`--db-path`を追加できます。RemoteモードでもDBは読み取り専用で開かれます。

## Claude Desktop

### MCPBを使う方法

生成物の`dist\Sparkle.mcpb`をClaude Desktopへインストールします。

1. Claude Desktopの`Settings`を開く。
2. `Extensions` → `Advanced settings` → `Extension Developer` → `Install Extension...`を選ぶ。
3. `dist\Sparkle.mcpb`を選ぶ。
4. チャット画面の`+` → `Connectors`でSparkleのToolが有効になっていることを確認する。

再生成する場合は、PyInstallerビルド後にリポジトリ直下で`powershell -ExecutionPolicy Bypass -File .\build_mcpb.ps1`を実行します。

これはローカルstdio方式なので、Remote URLは不要です。MCPBの中にはWindows向け`SparkleMCP.exe`が入り、GUI本体`Sparkle.exe`とは別プロセスで起動します。

### Remote Connectorを使う方法

Claude Desktopのアカウント側Remote Connectorを使う場合は、Claude Webと同じ公開URLが必要です。Funnel Webモードでは`https://.../mcp`、Serve Webモードでは`https://...:8443/mcp`を登録し、OAuth画面でMCP専用アクセスキーを入力します。

Remote ConnectorはClaudeのクラウドからSparkleへ接続するため、`localhost`やTailnet内だけのTailscale Serve URLでは到達できません。公開HTTPSのFunnel、または同等の公開リバースプロキシが必要です。

## Claude Web

`Customize` → `Connectors` → `+` → `Add custom connector`から、公開MCP URL（`/mcp`まで）を登録します。初回接続時にOAuthの認証画面が開くので、SparkleのMCP専用アクセスキーを入力して読み取り接続を許可します。

Claude WebのRemote ConnectorはAnthropicのクラウドから接続されるため、ローカルPCから見えるだけのURLでは動作しません。設定画面に表示される公開Funnel URLを登録してください。

## ChatGPT Web

ChatGPTのDeveloper Mode / Custom MCP Appが利用できるプラン・ワークスペースで、設定画面に表示されたRemote MCP URL（Funnel Webモードでは`https://.../mcp`）を登録します。OAuthの動的Client Registration、Authorization Code + PKCE、Refresh Tokenを実装済みです。利用可能なメニュー名やFull MCPの可否はChatGPTのプランとワークスペース設定に依存します。

OpenAIの仕様上、ChatGPT WebはローカルMCPへ直接接続しません。公開HTTPSを使わない場合はOpenAIが提供するSecure MCP Tunnel等の対応経路が別途必要です。

## ローカル動作確認

別ターミナルでRemote Serverを起動し、MCP Inspectorまたは同梱SDKクライアントから確認できます。

```powershell
$env:SPARKLE_MCP_PUBLIC_URL = "http://127.0.0.1:8002/mcp"
$env:SPARKLE_MCP_TOKEN = "0123456789abcdef-local-test-token"
.\dist\SparkleMCP.exe --transport streamable-http --port 8002
```

確認対象は次の通りです。

- `GET http://127.0.0.1:8002/.well-known/oauth-protected-resource/mcp`
- `GET http://127.0.0.1:8002/.well-known/oauth-authorization-server`
- Bearerなしの`POST /mcp`が`401`になること
- 認証済みMCP Clientで`initialize`、`tools/list`、`search_clips`が成功すること
- `search_*`の候補を受けて`get_*`を呼ぶこと、本文が上限で切られること

## 運用上の注意

- Remote公開時はHTTPSを必須にする。
- `SPARKLE_MCP_PUBLIC_URL`は外部から実際に見えるMCP URLに合わせる。Funnel Webでは`https://ホスト/mcp`、Serve Webでは`https://ホスト:8443/mcp`を指定する。HTTPSの`:443`有無はOAuthで正規化される。
- リモートアクセスキー、固定Bearer Token、OAuthコードをログへ出さない。
- 固定Tokenを変更する場合はプロセスを再起動する。
- 現在のOAuth ClientとTokenはプロセス再起動で失効する。再接続時にOAuthをやり直す。
- 書き込みToolを追加するまで、Scopeは`sparkle.read`だけにする。
- 公開リバースプロキシを使う場合は、別途rate limit、IP/ユーザー制御、監視、HTTPS証明書更新を設定する。

## 公式仕様

- [MCP Python SDK authorization](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/authorization.md)
- [MCPB manifest specification](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md)
- [Claude custom connectors using remote MCP](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
- [ChatGPT developer mode and MCP apps](https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt-beta)
