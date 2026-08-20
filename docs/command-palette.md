# コマンドパレット

コマンドパレットは `Ctrl+K`（macOS は `Cmd+K`）で開き、クリップ・メモ・タスク・プロジェクトをSQLiteの統合インデックスから横断検索します。検索結果は該当ページの項目へ直接移動できます。

## 検索の仕組み

- 通常時は、FTS5が利用できる環境ではFTS5とLIKEを併用し、利用できない環境ではLIKEへフォールバックします。
- クエリはラテン語（AMV、BGMなど）と日本語の助詞区切り（で、に、の、な、など）で分割し、各語を同義語（BGM↔曲・音楽・楽曲、AMV↔Edit・編集・エディット など）へ展開してマッチします。「AMVで使えそうなBGM」のような自然な言い回しでも、データ内の「AMVで使えそう」＋「曲」タグを見つけられます。
- 「今週の未完了タスク」「お気に入りのクリップ」「期限切れの作業」のような条件は、まず組み込みの日本語ルールで解釈します。
- `LiquidAI/LFM2.5-350M` は任意のローカルパーサーとして利用できます。モデルにSQLを生成させず、検索条件のJSONだけを受け取り、実データの読み取りとランキングはSQLiteが行います。

## LFM2.5-350Mを有効にする

1. Sparkleが使うPython環境で任意依存をインストールします。

   ```powershell
   <python.exe> -m pip install -r requirements-ai.txt
   ```

   NVIDIA GPUがある場合は、CUDA版torchを導入すると解析がGPU上で動作します。Windows向けcu130ビルドの例:

   ```powershell
   <python.exe> -m pip install torch==2.13.0+cu130 --index-url https://download.pytorch.org/whl/cu130
   ```

   `GET /command-palette/status` の `device` が `cuda` になればGPU動作です。検索レスポンスの `device` でも確認できます。

2. Hugging Face形式のモデルディレクトリ、またはGGUFを次のいずれかへ配置します。

   - `%APPDATA%\Sparkle\models\LFM2.5-350M`
   - `SPARKLE_LLM_MODEL_PATH` で指定したローカルディレクトリまたはGGUFファイル

   GGUFを使う場合は、同じディレクトリに公式 `LiquidAI/LFM2.5-350M` の `config.json`、`tokenizer.json`、`tokenizer_config.json`、`chat_template.jinja`、`generation_config.json` を配置します。GGUFの重みはそのまま使い、Transformersが起動時にPyTorch用の重みへ展開します。

3. アプリを再起動します。モデルは `local_files_only=True` で読み込むため、検索時にネットワークから自動取得しません。初回のモデル読み込みはアプリ起動時にバックグラウンドで行われるため、最初の検索がモデル読み込みで待たされることはありません。

モデルが未配置、メタデータ不足、または任意依存が未導入の場合も、コマンドパレット自体は通常検索として動作します。設定状態は `GET /command-palette/status` で確認できます。
