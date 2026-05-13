# Google Cloud ブラウザ UI デプロイ手順: JW 要約 Cloud Pipeline

この手順書は、`docs/design/cloud-pipeline.md` の Cloud Pipeline を、できるだけコマンドを使わずに Google Cloud Console のブラウザ UI から構築するためのガイドです。

Cloud Run のコード配置は、ローカル端末から `gcloud run deploy` するのではなく、GitHub リポジトリを Cloud Run に接続して、GitHub に push されたコードを Cloud Build が自動ビルド・デプロイする形にします。

重要: Cloud Run に接続するリポジトリは `jw-agent` ではなく、デプロイ専用の `jw-summarize-cloud` です。`jw-agent` はエージェントが各種タスクを実行するハーネスとして残し、人間が Google Form から投入する常時稼働パイプラインだけを `jw-summarize-cloud` で運用します。

対象パイプライン:

```text
Google Form
  -> Spreadsheet
  -> Apps Script
  -> Cloud Tasks
  -> Cloud Run
  -> Vertex AI Gemini
  -> GitHub / Obsidian Vault
```

## 0. 方針

### 0.0 2 リポジトリ運用

このパイプラインは次の役割分担で運用します。

| リポジトリ | 役割 |
|---|---|
| `jw-agent` | エージェント用ハーネス。スキル、コマンド、ローカル実行ツール、ノート作成などの自動化タスクを置く |
| `jw-summarize-cloud` | Cloud Run / Cloud Tasks / Apps Script / GCP デプロイ資産を置く本番サービス |

実行経路も分けます。

| 実行者 | 入口 | 実行場所 |
|---|---|---|
| 人間 | Google Form | `jw-summarize-cloud` の Cloud Run |
| エージェント | `jw-agent` の skill / command / tool | `jw-agent` 内のハーネス |

両方とも最終的には同じ Obsidian Vault リポジトリへ summary note と transcript note を書き込みます。共有するのは出力契約であり、GCP デプロイ資産を `jw-agent` に同居させることは避けます。

### 0.1 この手順で使う作業場所

| 作業 | 使う画面 |
|---|---|
| Cloud Run デプロイ | Google Cloud Console > Cloud Run |
| GitHub 連携 | Cloud Run の「リポジトリを接続」 |
| API 有効化 | API とサービス > ライブラリ |
| IAM / サービスアカウント | IAM と管理 |
| Secret | Secret Manager |
| 音声一時置き場 | Cloud Storage |
| 非同期キュー | Cloud Tasks |
| 入力フォーム | Google Forms |
| 管理台帳 | Google Sheets |
| フォーム送信処理 | Apps Script |

### 0.2 コマンドを完全に避けにくい場所

GCP 側の作成・デプロイはブラウザ UI で進めます。ただし、次の 2 点だけはブラウザ外の作業が必要です。

| 作業 | 理由 |
|---|---|
| `jw-summarize-cloud` を GitHub に push する | Cloud Run UI の継続デプロイは GitHub などの Git リポジトリからビルドするため |
| Apps Script に `Code.gs` / `appsscript.json` を貼る | Apps Script エディタでスクリプト本文を登録するため |

すでに `jw-summarize-cloud` が GitHub に置かれている場合は、GCP デプロイにローカル CLI は不要です。

### 0.3 この手順で使う名前

以下は例です。最初はこのまま進めると、後の設定値を合わせやすくなります。

| 項目 | 値 |
|---|---|
| リージョン | `asia-northeast1` |
| Cloud Run サービス | `jw-summarize-web` |
| Cloud Tasks キュー | `jw-summarize-process` |
| Cloud Run 実行サービスアカウント | `jw-summarize-runner` |
| Cloud Tasks 呼び出しサービスアカウント | `jw-summarize-tasks` |
| GCS バケット | `<PROJECT_ID>-jw-summarize-audio` |
| GitHub token secret | `jw-summarize-github-token` |

`<PROJECT_ID>` は Google Cloud プロジェクト ID に置き換えてください。

## 1. 事前にメモしておく値

作業中に何度も使うため、先にメモを作っておくと楽です。

| メモ名 | 例 | どこで確認するか |
|---|---|---|
| `PROJECT_ID` | `my-jw-summarize-cloud-prod` | Console 上部のプロジェクト選択 |
| `PROJECT_NUMBER` | `123456789012` | IAM と管理 > 設定 |
| `REGION` | `asia-northeast1` | この手順では固定 |
| `RUNNER_SA` | `jw-summarize-runner@<PROJECT_ID>.iam.gserviceaccount.com` | 作成後に確認 |
| `TASKS_SA` | `jw-summarize-tasks@<PROJECT_ID>.iam.gserviceaccount.com` | 作成後に確認 |
| `AUDIO_BUCKET` | `<PROJECT_ID>-jw-summarize-audio` | 作成後に確認 |
| `SHEET_ID` | Spreadsheet URL の `/d/` と `/edit` の間 | Spreadsheet URL |
| `CLOUD_RUN_URL` | `https://jw-summarize-web-xxxxx-an.a.run.app` | Cloud Run デプロイ後 |
| `CLOUD_RUN_PROCESS_URL` | `<CLOUD_RUN_URL>/process` | Cloud Run URL から作る |
| `GITHUB_REPOSITORY` | `owner/repo` | Obsidian Vault リポジトリ |
| `GITHUB_BRANCH` | `main` | Obsidian Vault の保存先ブランチ |

## 2. 必要な API を有効化する

### 2.1 API ライブラリを開く

1. Google Cloud Console を開く。
2. 上部のプロジェクト選択で対象プロジェクトを選ぶ。
3. 左上のナビゲーションメニューを開く。
4. `API とサービス` > `ライブラリ` を開く。

### 2.2 以下の API を検索して有効化する

1 つずつ検索し、ページを開いて `有効にする` を押します。すでに有効なら、そのままで大丈夫です。

| API 名 | 使う場所 |
|---|---|
| Cloud Run Admin API | Cloud Run サービス |
| Cloud Build API | GitHub からのビルド |
| Artifact Registry API | ビルド済みコンテナの保存 |
| Cloud Tasks API | 非同期ジョブキュー |
| Cloud Storage API | 音声ファイルの一時保存 |
| Vertex AI API | Gemini 要約・文字起こし |
| Secret Manager API | GitHub token の保存 |
| Google Sheets API | Cloud Run から Spreadsheet 更新 |
| IAM Service Account Credentials API | Cloud Tasks の OIDC token 発行 |

注意点:

- API 有効化直後は数十秒から数分、画面に反映されないことがあります。
- 権限エラーが出る場合、自分のアカウントに `Service Usage Admin` 相当の権限が足りない可能性があります。

## 3. サービスアカウントを作る

### 3.1 Cloud Run 実行用サービスアカウント

1. `IAM と管理` > `サービス アカウント` を開く。
2. `サービス アカウントを作成` を押す。
3. `サービス アカウント名` に `jw-summarize-runner` と入力する。
4. `サービス アカウント ID` が `jw-summarize-runner` になっていることを確認する。
5. `作成して続行` を押す。
6. ロール付与画面はいったん空のまま `完了` を押す。

作成後、一覧に次のメールアドレスが出ます。

```text
jw-summarize-runner@<PROJECT_ID>.iam.gserviceaccount.com
```

これを `RUNNER_SA` としてメモします。

### 3.2 Cloud Tasks 呼び出し用サービスアカウント

同じ画面で、もう 1 つ作ります。

1. `サービス アカウントを作成` を押す。
2. `サービス アカウント名` に `jw-summarize-tasks` と入力する。
3. `サービス アカウント ID` が `jw-summarize-tasks` になっていることを確認する。
4. `作成して続行` を押す。
5. ロール付与画面はいったん空のまま `完了` を押す。

作成後、一覧に次のメールアドレスが出ます。

```text
jw-summarize-tasks@<PROJECT_ID>.iam.gserviceaccount.com
```

これを `TASKS_SA` としてメモします。

## 4. IAM 権限を付ける

### 4.1 Cloud Run 実行 SA に Vertex AI 権限を付ける

1. `IAM と管理` > `IAM` を開く。
2. `アクセスを許可` を押す。
3. `新しいプリンシパル` に `RUNNER_SA` を入力する。
4. `ロールを選択` で `Vertex AI ユーザー` を選ぶ。
5. `保存` を押す。

### 4.2 Cloud Run 実行 SA に Secret Manager 読み取り権限を付ける

プロジェクト全体ではなく、後で作る `jw-summarize-github-token` secret 単位で付けるのがおすすめです。手順 6.2 で設定します。

急いで検証するだけなら、`IAM と管理` > `IAM` で `RUNNER_SA` に `Secret Manager のシークレット アクセサー` を付けても動きます。ただし本番運用では secret 単位に絞る方が安全です。

### 4.3 Apps Script 実行ユーザーに Cloud Tasks 権限を付ける

Apps Script は、自分の Google アカウント権限で Cloud Tasks API を呼びます。

1. `IAM と管理` > `IAM` を開く。
2. `アクセスを許可` を押す。
3. `新しいプリンシパル` に自分の Google アカウントのメールアドレスを入力する。
4. `ロールを選択` で `Cloud Tasks エンキュー実行者` を選ぶ。
5. `保存` を押す。

### 4.4 Apps Script 実行ユーザーに `TASKS_SA` を使う権限を付ける

Cloud Tasks が Cloud Run を呼ぶときに、`jw-summarize-tasks` の OIDC token を付けます。そのため、Apps Script 実行ユーザーに `TASKS_SA` を使う権限を付けます。

1. `IAM と管理` > `サービス アカウント` を開く。
2. `jw-summarize-tasks` をクリックする。
3. `権限` タブを開く。
4. `アクセスを許可` を押す。
5. `新しいプリンシパル` に自分の Google アカウントのメールアドレスを入力する。
6. `ロールを選択` で `サービス アカウント ユーザー` を選ぶ。
7. `保存` を押す。

### 4.5 Cloud Tasks サービスエージェントにも `TASKS_SA` を使う権限を付ける

Cloud Tasks 自身も `TASKS_SA` の token を発行できる必要があります。

1. `IAM と管理` > `設定` を開き、`プロジェクト番号` をメモする。
2. `IAM と管理` > `サービス アカウント` を開く。
3. `jw-summarize-tasks` をクリックする。
4. `権限` タブを開く。
5. `アクセスを許可` を押す。
6. `新しいプリンシパル` に次を入力する。

```text
service-<PROJECT_NUMBER>@gcp-sa-cloudtasks.iam.gserviceaccount.com
```

7. `ロールを選択` で `サービス アカウント ユーザー` を選ぶ。
8. `保存` を押す。

`PROJECT_NUMBER` と `PROJECT_ID` は別物です。ここは数字だけの `PROJECT_NUMBER` を使います。

### 4.6 Cloud Build の権限を確認する

Cloud Run の GitHub 連携では、Cloud Build がリポジトリをビルドし、Cloud Run に新しいリビジョンを作ります。多くのプロジェクトでは画面の案内どおりに進めるだけで必要な権限が付与されますが、組織ポリシーによってはビルド用サービスアカウントの権限不足で失敗します。

Cloud Build で権限エラーが出た場合は、失敗したビルドログに表示されるサービスアカウントに、以下のロールがあるか確認します。

| ロール | 理由 |
|---|---|
| `Cloud Build サービス アカウント` | Cloud Build の基本実行権限 |
| `Cloud Run 管理者` | Cloud Run サービスとリビジョンを更新する |
| `サービス アカウント ユーザー` | `RUNNER_SA` を Cloud Run の実行 ID として設定する |
| `Artifact Registry 書き込み` | ビルドしたコンテナイメージを保存する |

確認場所:

1. `Cloud Build` > `履歴` を開く。
2. 失敗したビルドを開く。
3. ログまたはビルド詳細で、実行サービスアカウントを確認する。
4. `IAM と管理` > `IAM` で、そのサービスアカウントに上記ロールを追加する。

権限反映には数分かかることがあります。反映後、Cloud Build の失敗したビルドを再実行するか、GitHub に新しい commit を push して再ビルドします。

## 5. 音声用 Cloud Storage バケットを作る

### 5.1 バケットを作成する

1. `Cloud Storage` > `バケット` を開く。
2. `作成` を押す。
3. `バケットに名前を付ける` に `<PROJECT_ID>-jw-summarize-audio` を入力する。
4. `続行` を押す。
5. `ロケーション タイプ` は `リージョン` を選ぶ。
6. `ロケーション` は `asia-northeast1 (東京)` を選ぶ。
7. `ストレージ クラス` は `Standard` のままでよい。
8. `公開アクセスの防止` は有効のままにする。
9. `アクセス制御` は `均一` を選ぶ。
10. `作成` を押す。

バケット名は全世界で一意です。すでに使われている場合は、`<PROJECT_ID>-jw-summarize-audio-001` のように少し変えてください。その場合、以降の `GCS_AUDIO_BUCKET` も同じ名前にします。

### 5.2 Cloud Run 実行 SA にバケット操作権限を付ける

1. 作成したバケットを開く。
2. `権限` タブを開く。
3. `アクセスを許可` を押す。
4. `新しいプリンシパル` に `RUNNER_SA` を入力する。
5. `ロールを選択` で `Storage オブジェクト管理者` を選ぶ。
6. `保存` を押す。

これは Cloud Run が GCS 上の音声を Vertex AI に渡すための権限です。

### 5.3 Apps Script 実行ユーザーにアップロード権限を付ける

1. 同じバケットの `権限` タブで `アクセスを許可` を押す。
2. `新しいプリンシパル` に自分の Google アカウントのメールアドレスを入力する。
3. `ロールを選択` で `Storage オブジェクト作成者` を選ぶ。
4. `保存` を押す。

`Storage オブジェクト作成者` はアップロード専用です。既存ファイルの削除や上書きまでは許可しません。

### 5.4 7 日後に音声を自動削除する

1. 作成したバケットを開く。
2. `ライフサイクル` タブを開く。
3. `ルールを追加` を押す。
4. アクションは `オブジェクトを削除` を選ぶ。
5. 条件で `Age` または `オブジェクトの経過日数` を選び、`7` 日にする。
6. プレフィックス条件を設定できる画面なら、`incoming/` を追加する。
7. `作成` または `保存` を押す。

プレフィックス条件が UI で見つからない場合は、バケット全体を 7 日後削除にしても動作確認には問題ありません。ただし本番では `incoming/` のみに絞る方が安全です。

## 6. GitHub token を Secret Manager に保存する

### 6.1 Secret を作成する

1. `セキュリティ` > `Secret Manager` を開く。
2. `シークレットを作成` を押す。
3. `名前` に `jw-summarize-github-token` を入力する。
4. `シークレットの値` に GitHub の Personal Access Token を貼る。
5. `リージョン` は自動またはデフォルトのままでよい。
6. `シークレットを作成` を押す。

GitHub token には、Obsidian Vault リポジトリへ commit/push できる権限が必要です。fine-grained token の場合は、対象リポジトリを限定し、`Contents: Read and write` を付けます。

### 6.2 Cloud Run 実行 SA に secret 読み取り権限を付ける

1. `Secret Manager` で `jw-summarize-github-token` を開く。
2. `権限` タブを開く。
3. `アクセスを許可` を押す。
4. `新しいプリンシパル` に `RUNNER_SA` を入力する。
5. `ロールを選択` で `Secret Manager のシークレット アクセサー` を選ぶ。
6. `保存` を押す。

## 7. Google Form と Spreadsheet を作る

### 7.1 Form を作る

Google Form で新しいフォームを作ります。フォーム名は例として `JW 要約受付` にします。

質問は以下の名前で作ります。Apps Script は列名を見て値を拾うため、最初はこの名前どおりにしてください。

| 質問名 | 種類 | 必須 | 値 |
|---|---|---|---|
| `入力種別` | ラジオボタン | 必須 | `url`, `text`, `audio` |
| `URL` | 記述式 | 任意 | JW.org の動画ページ URL |
| `本文` | 段落 | 任意 | テキスト入力 |
| `音声ファイル` | ファイルのアップロード | 任意 | mp3/m4a/wav など |
| `タイトル` | 記述式 | 任意 | 空欄時は種別ごとにフォールバック |
| `タグ` | 記述式 | 任意 | カンマ区切り |

最初は分岐設定なしで作るのがおすすめです。動作確認後に、`入力種別=url` のときだけ URL 質問を出す、などのセクション分岐を追加します。

### 7.2 回答先 Spreadsheet を作る

1. Form の `回答` タブを開く。
2. 緑色の Spreadsheet アイコンを押す。
3. `新しいスプレッドシートを作成` を選ぶ。
4. 作成された Spreadsheet を開く。

Spreadsheet URL は次の形です。

```text
https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit
```

`/d/` と `/edit` の間が `SHEET_ID` です。

### 7.3 Cloud Run 実行 SA を Spreadsheet に共有する

1. Spreadsheet 右上の `共有` を押す。
2. `RUNNER_SA` を入力する。
3. 権限を `編集者` にする。
4. 通知メールは送らなくてよい。
5. `共有` または `送信` を押す。

共有し忘れると、Cloud Run が Spreadsheet を読めず処理が失敗します。

## 8. Cloud Run をブラウザ UI からデプロイする

### 8.1 GitHub リポジトリを準備する

Cloud Run UI からソースコードをデプロイする場合、`jw-summarize-cloud` が GitHub に push されている必要があります。`jw-agent` は Cloud Run に接続しません。

推奨:

- `jw-agent` から Cloud Run に必要なコードだけを `jw-summarize-cloud` に移す
- `jw-summarize-cloud` の `main` または `deploy/prod` をデプロイ対象ブランチに決める
- Cloud Run はそのブランチへの push をきっかけに自動デプロイする

初期移行で `jw-summarize-cloud` に置くもの:

| 種類 | 例 |
|---|---|
| Cloud Run アプリ | Flask webapp, Cloud Pipeline service, auth, sheets, audio, GitHub publisher |
| URL 入力の処理 | `jw_subtitles` 相当の字幕取得コード |
| Apps Script | `scripts/cloud_pipeline/Code.gs`, `scripts/cloud_pipeline/appsscript.json` |
| 依存関係 | Cloud Run に必要なものだけを書いた `pyproject.toml` / lock file |
| 手順書 | `docs/deploy/` と Cloud Pipeline 設計のコピー |

`jw-agent` には、エージェントが `jw-agent` 内からノート作成を実行するための skills / commands / tools を残します。Cloud Run の継続デプロイ、GCP サービス設定、Apps Script の正本は `jw-summarize-cloud` 側で管理します。

### 8.2 Cloud Run でリポジトリを接続する

1. Google Cloud Console で `Cloud Run` を開く。
2. `サービス` を開く。
3. `リポジトリを接続` を押す。
4. 接続方式は、まず `Cloud Build` を選ぶ。
5. GitHub 認証を求められたら、画面の指示に従って GitHub App をインストールする。
6. 対象の GitHub アカウントまたは Organization を選ぶ。
7. `jw-summarize-cloud` のリポジトリだけを許可する。
8. リポジトリ一覧に戻ったら、対象リポジトリを選んで `次へ` を押す。

Cloud Run の公式ドキュメントでは、Cloud Run コンソールから Cloud Build または Developer Connect を使って継続デプロイを設定できるとされています。GitHub だけなら Cloud Build が一番わかりやすいです。

### 8.3 ビルド設定を入力する

`ビルド構成` では以下を設定します。

| 項目 | 値 |
|---|---|
| Branch | `^main$` または `^deploy/prod$` など、`jw-summarize-cloud` のデプロイ対象ブランチに合わせた正規表現 |
| Build Type | `Python via Google Cloud's buildpacks` |
| Build context directory | `/` または空欄 |
| Entrypoint | `gunicorn --bind :8080 tools.jw_summarize.webapp:app` |
| Function target | 空欄 |

`Entrypoint` は重要です。Cloud Run はコンテナ内の `PORT` に HTTP サーバーが listen することを期待します。このアプリは Flask なので、`gunicorn` で Flask app を起動します。

上の値は、`jw-agent` から移行したあとも Python package path を `tools.jw_summarize.webapp` として残す場合の例です。`jw-summarize-cloud` 側で `jw_summarize_cloud.webapp` のような package に整理した場合は、Entrypoint も次のように合わせて変更します。

```text
gunicorn --bind :8080 jw_summarize_cloud.webapp:app
```

ビルド環境変数を設定できる欄が表示される場合は、以下も入れます。

| 名前 | 値 |
|---|---|
| `GOOGLE_PYTHON_VERSION` | `3.12.x` |
| `GOOGLE_PYTHON_PACKAGE_MANAGER` | `uv` |

この欄が表示されない場合でも、`pyproject.toml` の `requires-python = ">=3.12"` と `uv.lock` から buildpacks が検出できることがあります。ビルドログで Python 3.12 や依存関係の解決に失敗したときは、Cloud Build トリガーの編集画面で同じ値を追加してください。

### 8.4 Cloud Run サービス設定を入力する

リポジトリ接続を保存すると、Cloud Run サービス作成フォームに戻ります。以下を設定します。

| 項目 | 値 |
|---|---|
| サービス名 | `jw-summarize-web` |
| リージョン | `asia-northeast1` |
| CPU | `1` |
| メモリ | `1 GiB` |
| リクエスト タイムアウト | `1800` 秒 |
| 最小インスタンス数 | `0` |
| 最大インスタンス数 | `10` |
| 同時実行数 | `1` |
| 認証 | `認証が必要` |
| サービス アカウント | `RUNNER_SA` |

`認証が必要` にすると、Cloud Run は一般公開されません。後で `TASKS_SA` にだけ呼び出し権限を付けます。

### 8.5 環境変数を追加する

サービス作成フォームで、`コンテナ、ボリューム、ネットワーキング、セキュリティ` のような詳細設定を開きます。`コンテナ` タブの `変数とシークレット` で、次の環境変数を追加します。

| 名前 | 値 |
|---|---|
| `LLM_PROVIDER` | `vertexai` |
| `LLM_PROFILE` | `heavy` |
| `VERTEX_PROJECT_ID` | `<PROJECT_ID>` |
| `VERTEX_LOCATION` | `asia-northeast1` |
| `VERTEX_HEAVY_MODEL` | `gemini-2.5-pro` |
| `GCP_PROJECT_ID` | `<PROJECT_ID>` |
| `GCS_AUDIO_BUCKET` | `<AUDIO_BUCKET>` |
| `SHEETS_MANAGEMENT_ID` | `<SHEET_ID>` |
| `TASKS_QUEUE_NAME` | `jw-summarize-process` |
| `TASKS_LOCATION` | `asia-northeast1` |
| `GITHUB_REPOSITORY` | `owner/repo` |
| `GITHUB_BRANCH` | `main` |
| `OBSIDIAN_SUMMARY_DIR` | `01_Talks` |
| `OBSIDIAN_TRANSCRIPT_DIR` | `05_Transcription` |
| `CLOUD_RUN_AUDIENCE` | `https://placeholder.example` |

初回は Cloud Run URL がまだ分からないため、`CLOUD_RUN_AUDIENCE` は仮値にします。デプロイ後に正しい Cloud Run URL へ更新します。

設定してはいけない値:

| 名前 | 理由 |
|---|---|
| `WEBHOOK_SHARED_SECRET` | 設定するとアプリが共有シークレット認証を優先し、Cloud Tasks の OIDC 認証を受け付けなくなる |
| `PORT` | Cloud Run が自動注入する予約変数 |

### 8.6 Secret を環境変数として参照する

同じ `変数とシークレット` で、`シークレットを参照` または `Reference a secret` を押します。

| 項目 | 値 |
|---|---|
| 環境変数名 | `GITHUB_TOKEN` |
| Secret | `jw-summarize-github-token` |
| Version | `latest` |

### 8.7 初回デプロイを作成する

1. 設定を見直す。
2. `作成` を押す。
3. Cloud Build と Cloud Run の進行状況を待つ。
4. 成功したら Cloud Run のサービス詳細画面に移動する。

失敗した場合は、サービス詳細画面のビルドログリンク、または `Cloud Build` > `履歴` からログを開きます。

よく見るポイント:

| 症状 | 確認 |
|---|---|
| Python 版が合わない | Buildpacks が Python 3.12 を使っているか |
| `gunicorn` が見つからない | `pyproject.toml` の依存関係が読まれているか |
| 起動後すぐ落ちる | Entrypoint が `gunicorn --bind :8080 tools.jw_summarize.webapp:app` か |

### 8.8 Cloud Run URL を取得する

Cloud Run サービス詳細画面の上部に表示される URL をコピーします。

例:

```text
https://jw-summarize-web-xxxxx-an.a.run.app
```

これを `CLOUD_RUN_URL` としてメモします。

また、Apps Script で使う処理 URL は末尾に `/process` を付けます。

```text
https://jw-summarize-web-xxxxx-an.a.run.app/process
```

これを `CLOUD_RUN_PROCESS_URL` としてメモします。

### 8.9 `CLOUD_RUN_AUDIENCE` を正しい URL に更新する

1. Cloud Run の `jw-summarize-web` サービス詳細を開く。
2. `編集して新しいリビジョンをデプロイ` を押す。
3. `コンテナ` > `変数とシークレット` を開く。
4. `CLOUD_RUN_AUDIENCE` を `CLOUD_RUN_URL` に更新する。

```text
CLOUD_RUN_AUDIENCE=https://jw-summarize-web-xxxxx-an.a.run.app
```

5. `デプロイ` を押す。

`/process` は付けません。`CLOUD_RUN_AUDIENCE` は Cloud Run サービス URL 本体です。

### 8.10 Cloud Tasks SA に Cloud Run 呼び出し権限を付ける

1. Cloud Run の `jw-summarize-web` サービス詳細を開く。
2. `権限` タブを開く。
3. `アクセスを許可` を押す。
4. `新しいプリンシパル` に `TASKS_SA` を入力する。
5. `ロールを選択` で `Cloud Run 起動元` を選ぶ。
6. `保存` を押す。

これで、Cloud Tasks が `jw-summarize-tasks` として Cloud Run を呼べるようになります。

## 9. Cloud Tasks キューをブラウザ UI で作る

### 9.1 キューを作成する

1. `Cloud Tasks` > `キュー` を開く。
2. `キューを作成` を押す。
3. `キュー名` に `jw-summarize-process` を入力する。
4. `リージョン` は `asia-northeast1` を選ぶ。
5. `作成` を押す。

### 9.2 キュー設定を調整する

作成フォームまたは作成後の編集画面で、可能なら以下を設定します。

| 項目 | 値 |
|---|---|
| 最大ディスパッチ数/秒 | `5` |
| 最大同時ディスパッチ数 | `10` |
| 最大試行回数 | `3` |
| 最小バックオフ | `30` 秒 |
| 最大バックオフ | `600` 秒 |
| 最大ダブリング数 | `5` |

Cloud Tasks の HTTP timeout にあたる `dispatchDeadline` は、キューではなく各タスクに設定します。`jw-summarize-cloud` の `scripts/cloud_pipeline/Code.gs` は、Apps Script の `TASK_DISPATCH_DEADLINE_SECONDS` を使って各タスクに `1800s` を設定します。

## 10. Apps Script を設定する

### 10.1 Apps Script エディタを開く

1. 手順 7 で作った Spreadsheet を開く。
2. メニューから `拡張機能` > `Apps Script` を開く。

### 10.2 `Code.gs` を貼る

Apps Script エディタで `Code.gs` を開き、`jw-summarize-cloud` の以下の内容を貼ります。

```text
scripts/cloud_pipeline/Code.gs
```

初期状態の `myFunction` は削除して構いません。

### 10.3 `appsscript.json` を表示する

1. Apps Script エディタ左側の歯車アイコン `プロジェクトの設定` を開く。
2. `appsscript.json マニフェスト ファイルをエディタで表示する` をオンにする。
3. 左側に `appsscript.json` が表示される。

### 10.4 `appsscript.json` を貼る

`appsscript.json` を開き、`jw-summarize-cloud` の以下の内容を貼ります。

```text
scripts/cloud_pipeline/appsscript.json
```

### 10.5 Script Properties を設定する

1. Apps Script エディタ左側の歯車アイコン `プロジェクトの設定` を開く。
2. `スクリプト プロパティ` までスクロールする。
3. `スクリプト プロパティを追加` を押して、以下を登録する。

| プロパティ | 値 |
|---|---|
| `GCP_PROJECT_ID` | `<PROJECT_ID>` |
| `TASKS_LOCATION` | `asia-northeast1` |
| `TASKS_QUEUE_NAME` | `jw-summarize-process` |
| `CLOUD_RUN_PROCESS_URL` | `<CLOUD_RUN_URL>/process` |
| `CLOUD_RUN_AUDIENCE` | `<CLOUD_RUN_URL>` |
| `CLOUD_TASKS_SERVICE_ACCOUNT` | `TASKS_SA` |
| `GCS_AUDIO_BUCKET` | `<AUDIO_BUCKET>` |
| `FAILED_AFTER_MINUTES` | `120` |
| `TASK_DISPATCH_DEADLINE_SECONDS` | `1800` |

フォームの質問名を変えた場合だけ、以下も設定します。

| プロパティ | 既定値 |
|---|---|
| `FORM_INPUT_TYPE_COLUMN` | `入力種別` |
| `FORM_URL_COLUMN` | `URL` |
| `FORM_TEXT_COLUMN` | `本文` |
| `FORM_AUDIO_COLUMN` | `音声ファイル` |
| `FORM_TITLE_COLUMN` | `タイトル` |
| `FORM_TAGS_COLUMN` | `タグ` |

### 10.6 初回認可を行う

1. Apps Script エディタ上部の関数選択で `installMonitorTrigger` を選ぶ。
2. `実行` を押す。
3. Google の認可画面が出たら、自分のアカウントで許可する。

警告が出る場合:

1. `詳細` を押す。
2. プロジェクト名へ移動する。
3. 許可する。

これは自分の Spreadsheet に紐づく未公開スクリプトなので、初回は警告が出ることがあります。

### 10.7 フォーム送信トリガーを追加する

1. Apps Script エディタ左側の時計アイコン `トリガー` を開く。
2. `トリガーを追加` を押す。
3. 以下のように設定する。

| 項目 | 値 |
|---|---|
| 実行する関数 | `onFormSubmit` |
| 実行するデプロイ | `Head` |
| イベントのソース | `スプレッドシートから` |
| イベントの種類 | `フォーム送信時` |

4. `保存` を押す。

### 10.8 監視トリガーを確認する

`installMonitorTrigger` を実行済みなら、トリガー一覧に `monitorQueuedRows` があるはずです。

| 項目 | 値 |
|---|---|
| 実行する関数 | `monitorQueuedRows` |
| イベントのソース | `時間主導型` |
| 間隔 | 15 分ごと |

このトリガーが、`queued` のまま 120 分を超えた行を `failed` にします。

## 11. 動作確認

### 11.1 Cloud Run が起動しているか確認する

Cloud Run は非公開なので、ブラウザで URL を開くと 403 になるのが正常です。

Cloud Run の状態確認:

1. `Cloud Run` > `jw-summarize-web` を開く。
2. `リビジョン` タブを開く。
3. 最新リビジョンが serving 状態になっていることを確認する。
4. `ログ` タブで起動エラーが出ていないことを確認する。

`/healthz` をブラウザから直接開くと、認証がないため 403 になります。これは Cloud Run IAM が効いているためで、異常ではありません。

### 11.2 text 入力でテストする

最初は音声ではなく text が一番簡単です。

Form に以下を入力します。

| 項目 | 値 |
|---|---|
| 入力種別 | `text` |
| 本文 | 短めの日本語テキスト |
| タイトル | `Cloud Pipeline 動作確認` |
| タグ | `test` |

送信後、Spreadsheet を見ます。

期待する流れ:

1. `row_id` などの列が自動追加される。
2. `status` が `queued` になる。
3. `enqueued_at` が入る。
4. 数分後に `status` が `done` になる。
5. `github_url` に commit URL が入る。
6. GitHub リポジトリに summary note と transcript note が追加される。

### 11.3 Cloud Tasks を確認する

1. `Cloud Tasks` > `キュー` を開く。
2. `jw-summarize-process` を開く。
3. タスク数、失敗数、リトライ状況を見る。

成功したタスクはキューから消えます。空なら正常です。

### 11.4 Cloud Run ログを確認する

1. `Cloud Run` > `jw-summarize-web` を開く。
2. `ログ` タブを開く。
3. エラーだけ見たい場合は、重大度のフィルタで Error 以上を選ぶ。

見るポイント:

| ログ | 意味 |
|---|---|
| `Missing bearer token` | Cloud Tasks の OIDC token が付いていない |
| `Invalid OIDC token` | `CLOUD_RUN_AUDIENCE` が一致していない |
| `Application error while processing request` | アプリ内部で設定不足や外部 API エラー |
| GitHub API の 401/403 | GitHub token 権限不足 |
| Sheets API の 403 | Spreadsheet 共有漏れ |

### 11.5 音声入力をテストする

次に短い mp3/m4a/wav で試します。

| 項目 | 値 |
|---|---|
| 入力種別 | `audio` |
| 音声ファイル | 1 分程度の音声 |
| タイトル | 任意 |
| タグ | `audio-test` |

期待する流れ:

1. Apps Script が Drive 添付ファイルを GCS にコピーする。
2. `gcs_uri` に `gs://.../incoming/<row_id>.<ext>` が入る。
3. Drive 側の添付ファイルがゴミ箱に移動される。
4. Cloud Run が Gemini で文字起こしする。
5. transcript note と summary note が同一 commit で作成される。

GCS 側の確認:

1. `Cloud Storage` > `バケット` を開く。
2. `<AUDIO_BUCKET>` を開く。
3. `incoming/` フォルダにファイルがあるか確認する。

## 12. よくある失敗と直し方

### 12.1 Form 送信後すぐ `failed` になる

原因は Apps Script 側です。Cloud Run までは到達していません。

Spreadsheet の `error` 列を見ます。

| エラー | 原因 | 対処 |
|---|---|---|
| `Missing script property` | Script Properties の不足 | 手順 10.5 を見直す |
| `Cloud Tasks enqueue failed: HTTP 403` | Apps Script 実行ユーザーに Cloud Tasks 権限がない | 手順 4.3 を見直す |
| `GCS upload failed: HTTP 403` | Apps Script 実行ユーザーに GCS 権限がない | 手順 5.3 を見直す |
| `Missing Drive file id` | 音声ファイル列名が違う、またはファイル添付でない | Form の質問名と Script Properties を確認 |

### 12.2 `queued` のまま進まない

Cloud Tasks か Cloud Run 側で失敗しています。

確認順:

1. `Cloud Tasks` > `jw-summarize-process` でタスクが残っているか見る。
2. `Cloud Run` > `jw-summarize-web` > `ログ` を見る。
3. 120 分後に `failed` へ自動更新されるか見る。

### 12.3 Cloud Run が 401 を返す

アプリ側の OIDC 検証に失敗しています。

確認:

| 項目 | 正しい値 |
|---|---|
| Cloud Run env `CLOUD_RUN_AUDIENCE` | `https://...a.run.app` |
| Apps Script property `CLOUD_RUN_AUDIENCE` | 同じ `https://...a.run.app` |
| Apps Script property `CLOUD_RUN_PROCESS_URL` | `https://...a.run.app/process` |
| Cloud Run env `WEBHOOK_SHARED_SECRET` | 未設定 |

### 12.4 Cloud Run が 403 を返す

Cloud Run IAM で拒否されています。

確認:

1. `Cloud Run` > `jw-summarize-web` > `権限` を開く。
2. `TASKS_SA` に `Cloud Run 起動元` が付いているか見る。
3. なければ手順 8.10 を実施する。

### 12.5 Cloud Run が Sheet を読めない

Spreadsheet の共有設定で、`RUNNER_SA` が編集者になっているか確認します。

```text
jw-summarize-runner@<PROJECT_ID>.iam.gserviceaccount.com
```

閲覧者ではなく編集者が必要です。

### 12.6 GitHub commit で失敗する

| 原因 | 対処 |
|---|---|
| `GITHUB_REPOSITORY` が `owner/repo` 形式でない | Cloud Run の環境変数を直す |
| token に Contents write がない | GitHub token 権限を直す |
| branch 名が違う | `GITHUB_BRANCH` を直す |
| Secret 参照に失敗 | `RUNNER_SA` に `jw-summarize-github-token` の Secret Accessor があるか確認 |

### 12.7 Cloud Build が失敗する

| 症状 | 対処 |
|---|---|
| リポジトリが見つからない | GitHub App のインストール対象にリポジトリを追加する |
| buildpacks が Python と認識しない | `pyproject.toml` がリポジトリルートにあるか確認する |
| `gunicorn` が見つからない | `pyproject.toml` の依存関係が取り込まれているかログを見る |
| 起動ポートエラー | Entrypoint が `--bind :8080` になっているか確認する |

Cloud Run の継続デプロイ設定を直すには:

1. `Cloud Run` > `jw-summarize-web` を開く。
2. `ソース` または `継続的デプロイ` の設定から `リポジトリ設定を編集` を開く。
3. 必要に応じて `Cloud Build` > `トリガー` 側で設定を修正する。

## 13. 運用

### 13.1 コード変更をデプロイする

1. `jw-summarize-cloud` のコードを GitHub の対象ブランチに push する。
2. Cloud Build トリガーが自動実行される。
3. 成功すると Cloud Run に新しいリビジョンが作成される。
4. Cloud Run の `リビジョン` タブで最新リビジョンが 100% traffic になっていることを確認する。

ブラウザで確認する場所:

- `Cloud Build` > `履歴`
- `Cloud Run` > `jw-summarize-web` > `リビジョン`
- `Cloud Run` > `jw-summarize-web` > `ログ`

### 13.2 環境変数だけ変更する

例: GitHub branch を変える。

1. `Cloud Run` > `jw-summarize-web` を開く。
2. `編集して新しいリビジョンをデプロイ` を押す。
3. `コンテナ` > `変数とシークレット` を開く。
4. `GITHUB_BRANCH` を変更する。
5. `デプロイ` を押す。

環境変数変更だけでも新しいリビジョンが作られます。

### 13.3 GitHub token を更新する

1. `Secret Manager` > `jw-summarize-github-token` を開く。
2. `新しいバージョンを追加` を押す。
3. 新しい token を貼る。
4. 保存する。

Cloud Run は `jw-summarize-github-token:latest` を参照しているため、次回インスタンス起動時に新しい値を使います。すぐ反映したい場合は、Cloud Run で `編集して新しいリビジョンをデプロイ` を押し、設定を変えずに再デプロイします。

### 13.4 並列数を一時的に下げる

GitHub push 競合などが出る場合は Cloud Tasks の並列数を下げます。

1. `Cloud Tasks` > `キュー` を開く。
2. `jw-summarize-process` を開く。
3. `編集` を押す。
4. `最大同時ディスパッチ数` を `1` にする。
5. 保存する。

## 14. 削除したいとき

削除は戻せないものがあるため、テスト環境だけで実行してください。

### 14.1 Cloud Run

1. `Cloud Run` > `jw-summarize-web` を開く。
2. `削除` を押す。
3. 確認して削除する。

### 14.2 Cloud Build トリガー

1. `Cloud Build` > `トリガー` を開く。
2. `jw-summarize-web` 用のトリガーを選ぶ。
3. `削除` を押す。

### 14.3 Cloud Tasks

1. `Cloud Tasks` > `キュー` を開く。
2. `jw-summarize-process` を選ぶ。
3. `削除` を押す。

### 14.4 Cloud Storage

1. `Cloud Storage` > `バケット` を開く。
2. `<AUDIO_BUCKET>` を開く。
3. オブジェクトを削除する。
4. バケット一覧に戻り、バケットを削除する。

### 14.5 Secret Manager

1. `Secret Manager` を開く。
2. `jw-summarize-github-token` を選ぶ。
3. `削除` を押す。

### 14.6 サービスアカウント

1. `IAM と管理` > `サービス アカウント` を開く。
2. `jw-summarize-runner` を削除する。
3. `jw-summarize-tasks` を削除する。

Spreadsheet / Form / Apps Script は Google Drive 側で削除します。

## 15. 参考リンク

- Cloud Run 継続デプロイ: https://docs.cloud.google.com/run/docs/continuous-deployment
- Cloud Run ソースデプロイ: https://docs.cloud.google.com/run/docs/deploying-source-code
- Cloud Run 環境変数: https://cloud.google.com/run/docs/configuring/services/environment-variables
- Cloud Run Secret: https://cloud.google.com/run/docs/configuring/services/secrets
- Cloud Tasks キュー作成: https://cloud.google.com/tasks/docs/creating-queues
- Cloud Tasks HTTP target / OIDC: https://cloud.google.com/tasks/docs/creating-http-target-tasks
- Cloud Storage lifecycle: https://cloud.google.com/storage/docs/lifecycle
- Apps Script installable triggers: https://developers.google.com/apps-script/guides/triggers/installable

最終確認日: 2026-05-08
