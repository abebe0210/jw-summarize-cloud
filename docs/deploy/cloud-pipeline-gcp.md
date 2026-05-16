# Google Cloud デプロイ手順: JW 要約 Cloud Pipeline

この手順書は、`docs/design/cloud-pipeline.md` の設計を実際に Google Cloud へデプロイするための作業ガイドです。GCP に慣れていない人でも上から順に進められるように、画面で確認する場所、コマンドの意味、失敗しやすい点をできるだけ具体的に書いています。

ブラウザ UI からデプロイしたい場合は、まず [`docs/deploy/cloud-pipeline-gcp-ui.md`](cloud-pipeline-gcp-ui.md) を使ってください。そちらは `gcloud run deploy` ではなく、Cloud Run の GitHub 連携と Google Cloud Console の画面操作を中心にした手順です。このファイルは CLI で作業したい場合の参考手順として残しています。

重要: Cloud Run へデプロイするコードは `jw-agent` ではなく `jw-summarize-cloud` で管理します。`jw-agent` はエージェントがスキル / コマンド / ツールから各種タスクを実行するハーネスとして残し、人間が Google Form から投入する常時稼働パイプラインだけを `jw-summarize-cloud` に分離します。

対象パイプライン:

```
Google Form
  → Spreadsheet
  → Apps Script
  → Cloud Tasks
  → Cloud Run
  → Vertex AI Gemini
  → GitHub / Obsidian Vault
```

この手順ではリージョンを `asia-northeast1`、Cloud Run サービス名を `jw-summarize-web`、Cloud Tasks キュー名を `jw-summarize-process` とします。

すでに別名で作った場合は、その名前を以降も一貫して使ってください。たとえば Cloud Run サービスを `jw-summarize-cloud` として作った場合、`SERVICE_NAME` は `jw-summarize-cloud` にします。

---

## 0. 先に全体像をつかむ

### 0.0 2 リポジトリ運用

| リポジトリ | 主用途 |
|---|---|
| `jw-agent` | エージェントハーネス。ノート作成を含む自動化タスクをエージェントが実行する場所 |
| `jw-summarize-cloud` | Cloud Run / Cloud Tasks / Apps Script / GCP デプロイ資産を管理する本番サービス |

実行経路は次のように分けます。

| 実行者 | 入口 | 実行場所 |
|---|---|---|
| 人間 | Google Form | `jw-summarize-cloud` の Cloud Run |
| エージェント | `jw-agent` の skill / command / tool | `jw-agent` 内のハーネス |

両経路は同じ Obsidian Vault 出力契約を守ります。GCP の本番サービス設定や Apps Script の正本は `jw-summarize-cloud` に置き、`jw-agent` の作業場を Cloud Run デプロイ都合で重くしないことを優先します。

### 0.1 作るもの

| 作るもの | 役割 |
|---|---|
| GCP プロジェクト | Cloud Run / Cloud Tasks / GCS / Vertex AI を置く場所 |
| Cloud Run サービス | 要約処理の本体。`POST /process` を受けて処理する |
| Cloud Tasks キュー | フォーム送信を非同期ジョブとして Cloud Run に渡す |
| GCS バケット | 音声ファイルを一時保管する |
| Secret Manager | GitHub token を安全に持つ |
| サービスアカウント | Cloud Run 実行用、Cloud Tasks 呼び出し用の機械ユーザー |
| Google Form | 入力 UI |
| Spreadsheet | 管理台帳。`queued` / `done` / `failed` を見る場所 |
| Apps Script | Form 送信時に GCS へ音声を移し、Cloud Tasks に登録する |

### 0.2 この手順で使う名前

以下は例です。別名にしてもよいですが、初心者は最初はこのままがおすすめです。

| 項目 | 値 |
|---|---|
| リージョン | `asia-northeast1` |
| Cloud Run サービス | `jw-summarize-web` |
| Cloud Tasks キュー | `jw-summarize-process` |
| Cloud Run 実行 SA | `jw-summarize-runner` |
| Cloud Tasks OIDC SA | `jw-summarize-tasks` |
| GCS バケット | `<PROJECT_ID>-jw-summarize-audio` |

### 0.3 認証の考え方

Cloud Run は公開しません。Cloud Tasks だけが Cloud Run を呼べるようにします。

- Cloud Tasks は `jw-summarize-tasks@...` の OIDC トークンを付けて Cloud Run を呼ぶ
- Cloud Run IAM は `jw-summarize-tasks@...` にだけ `run.invoker` を付ける
- アプリ側も `CLOUD_RUN_AUDIENCE` で OIDC token の audience を検証する
- `WEBHOOK_SHARED_SECRET` は Cloud Pipeline では設定しない

重要: `WEBHOOK_SHARED_SECRET` を設定すると、アプリは共有シークレット認証を優先し、Cloud Tasks の OIDC 認証を受け付けません。

---

## 1. 事前準備

### 1.1 必要なもの

- Google Cloud の課金が有効なプロジェクト
- `gcloud` CLI
- Google Form / Spreadsheet を作れる Google アカウント
- GitHub の Personal Access Token
- `jw-summarize-cloud` のローカルチェックアウト

GitHub token には、Obsidian Vault リポジトリへ commit/push できる権限が必要です。fine-grained token を使う場合は対象リポジトリを限定し、Contents の Read and write を付けます。

### 1.2 `gcloud` にログインする

```bash
gcloud auth login
gcloud auth application-default login
```

`gcloud auth login` は CLI 操作用、`application-default login` はローカルで Google API を試すときの認証です。

### 1.3 プロジェクト ID を決める

GCP コンソールの上部に表示されるプロジェクト ID を確認します。ここでは `<PROJECT_ID>` と書きます。

注意: プロジェクトの「表示名」と「プロジェクト ID」は別物です。API、サービスアカウントのメールアドレス、Script Properties には表示名ではなくプロジェクト ID を使います。たとえば表示名が `jw-agent` で、プロジェクト ID が `jw-agent-495305` の場合、以降の `<PROJECT_ID>` は `jw-agent-495305` です。Cloud Run URL に含まれる数字は `PROJECT_NUMBER` で、これもプロジェクト ID とは別物です。

以降のコマンドを楽にするため、環境変数に入れます。

```bash
export PROJECT_ID="<PROJECT_ID>"
export REGION="asia-northeast1"
export SERVICE_NAME="jw-summarize-web"
export QUEUE_NAME="jw-summarize-process"
export RUNNER_SA_NAME="jw-summarize-runner"
export TASKS_SA_NAME="jw-summarize-tasks"
export AUDIO_BUCKET="${PROJECT_ID}-jw-summarize-audio"
```

GCP CLI のデフォルトプロジェクトも設定します。

```bash
gcloud config set project "${PROJECT_ID}"
```

確認:

```bash
gcloud config get-value project
```

期待値は `<PROJECT_ID>` です。

---

## 2. 必要な Google Cloud API を有効化する

Cloud Run などを使うには API の有効化が必要です。初回だけ実行します。

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  cloudtasks.googleapis.com \
  storage.googleapis.com \
  aiplatform.googleapis.com \
  secretmanager.googleapis.com \
  sheets.googleapis.com \
  iamcredentials.googleapis.com
```

各 API の意味:

| API | 使う場所 |
|---|---|
| Cloud Run | 要約処理の本体 |
| Cloud Build | `gcloud run deploy --source` でソースからコンテナを作る |
| Artifact Registry | Cloud Build が作ったコンテナを保存する |
| Cloud Tasks | 非同期ジョブキュー |
| Cloud Storage | 音声ファイルの一時保管 |
| Vertex AI | Gemini で要約・文字起こし |
| Secret Manager | GitHub token |
| Sheets API | Cloud Run から Spreadsheet を更新 |
| IAM Credentials | Cloud Tasks の OIDC token 発行 |

Vertex AI 呼び出し時に `Agent Platform API has not been used... service: aiplatform.googleapis.com` と出る場合も、ここで有効化する `aiplatform.googleapis.com` が不足しています。

---

## 3. サービスアカウントを作る

サービスアカウントは「人間ではない実行ユーザー」です。今回は 2 つ作ります。

| SA | 役割 |
|---|---|
| `jw-summarize-runner` | Cloud Run の中で動くアプリの権限 |
| `jw-summarize-tasks` | Cloud Tasks が Cloud Run を呼ぶときの身分 |

```bash
gcloud iam service-accounts create "${RUNNER_SA_NAME}" \
  --display-name="JW Summarize Cloud Run runner"

gcloud iam service-accounts create "${TASKS_SA_NAME}" \
  --display-name="JW Summarize Cloud Tasks caller"
```

メールアドレスを環境変数に入れます。

```bash
export RUNNER_SA="${RUNNER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
export TASKS_SA="${TASKS_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
```

確認:

```bash
gcloud iam service-accounts list \
  --filter="email:(${RUNNER_SA} OR ${TASKS_SA})"
```

---

## 4. Cloud Run 実行 SA に権限を付ける

Cloud Run のアプリは、Vertex AI、Sheets、GCS、Secret Manager、GitHub API を使います。GitHub API は token で認証するので、GCP IAM は不要です。

### 4.1 Vertex AI を使えるようにする

```bash
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUNNER_SA}" \
  --role="roles/aiplatform.user"
```

### 4.2 Secret Manager の secret を読めるようにする

```bash
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUNNER_SA}" \
  --role="roles/secretmanager.secretAccessor"
```

### 4.3 GCS バケット操作権限

バケット作成後に付けるため、ここではまだ実行しません。手順 5 で実行します。

---

## 5. 音声用 GCS バケットを作る

音声入力の場合、Google Form の添付ファイルはいったん Drive に入ります。Apps Script がそれを GCS にコピーし、Cloud Run は `gs://...` の URI を Gemini に渡します。

### 5.1 バケット作成

```bash
gcloud storage buckets create "gs://${AUDIO_BUCKET}" \
  --location="${REGION}" \
  --uniform-bucket-level-access
```

バケット名は全世界で一意です。もし `already exists` が出たら、`<PROJECT_ID>-jw-summarize-audio-001` のように名前を変えてください。その場合は以降の `AUDIO_BUCKET` も同じ名前にします。

### 5.2 Cloud Run 実行 SA にバケット権限を付ける

```bash
gcloud storage buckets add-iam-policy-binding "gs://${AUDIO_BUCKET}" \
  --member="serviceAccount:${RUNNER_SA}" \
  --role="roles/storage.objectAdmin"
```

これは Cloud Run が GCS 上の音声を Vertex AI に渡すための権限です。

### 5.3 Apps Script 実行ユーザーにもバケット権限を付ける

Apps Script は人間の Google アカウント権限で GCS へアップロードします。以下の `<YOUR_GOOGLE_ACCOUNT>` は Apps Script を作成・実行する Google アカウントのメールアドレスです。

```bash
export APPS_SCRIPT_USER="<YOUR_GOOGLE_ACCOUNT>"

gcloud storage buckets add-iam-policy-binding "gs://${AUDIO_BUCKET}" \
  --member="user:${APPS_SCRIPT_USER}" \
  --role="roles/storage.objectCreator"
```

`objectCreator` は新規アップロード用です。既存ファイルの削除や上書きは許可しません。

### 5.4 7 日後に音声を自動削除する

GCS に置いた音声は一時ファイルなので、7 日後に消す lifecycle を設定します。

`/tmp/jw-summarize-gcs-lifecycle.json` を作ります。

```bash
cat > /tmp/jw-summarize-gcs-lifecycle.json <<'JSON'
{
  "rule": [
    {
      "action": { "type": "Delete" },
      "condition": {
        "age": 7,
        "matchesPrefix": ["incoming/"]
      }
    }
  ]
}
JSON
```

設定します。

```bash
gcloud storage buckets update "gs://${AUDIO_BUCKET}" \
  --lifecycle-file=/tmp/jw-summarize-gcs-lifecycle.json
```

---

## 6. GitHub token を Secret Manager に保存する

`GITHUB_TOKEN` を Cloud Run の環境変数に直接書くのではなく、Secret Manager に保存します。

```bash
printf "%s" "<GITHUB_TOKEN>" | gcloud secrets create jw-summarize-github-token \
  --data-file=-
```

すでに作成済みで token を更新したい場合:

```bash
printf "%s" "<NEW_GITHUB_TOKEN>" | gcloud secrets versions add jw-summarize-github-token \
  --data-file=-
```

確認:

```bash
gcloud secrets versions list jw-summarize-github-token
```

---

## 7. Google Form と Spreadsheet を作る

### 7.1 Form を作る

Google Form で新しいフォームを作ります。フォーム名は例として `JW 要約受付` にします。

質問を以下のように作ります。

| 質問名 | 種類 | 必須 | 値 |
|---|---|---|---|
| `入力種別` | ラジオボタン | 必須 | `url`, `text`, `audio` |
| `URL` | 記述式 | 任意 | JW.org の動画ページ URL |
| `本文` | 段落 | 任意 | テキスト入力 |
| `音声ファイル` | ファイルのアップロード | 任意 | mp3/m4a/wav など |
| `タイトル` | 記述式 | 任意 | 空欄時は種別ごとにフォールバック |
| `タグ` | 記述式 | 任意 | カンマ区切り |

初心者向けのおすすめ:

- 最初は分岐設定なしで作る
- 動作確認ができてから、`入力種別=url` のときだけ URL を出す、などのセクション分岐を追加する
- `text` 入力ではタイトルが必要なので、運用上は「text のときはタイトルも入力」とフォーム説明に書く

### 7.2 回答先 Spreadsheet を作る

Form の「回答」タブから、緑色の Spreadsheet アイコンを押して回答先を作成します。

作成された Spreadsheet の URL は次のような形です。

```text
https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit
```

`/d/` と `/edit` の間が `<SHEET_ID>` です。後で使うので控えます。

```bash
export SHEET_ID="<SHEET_ID>"
```

### 7.3 Cloud Run 実行 SA を Spreadsheet に共有する

Spreadsheet 右上の「共有」から、Cloud Run 実行 SA のメールアドレスを編集者として追加します。

追加するメール:

```text
jw-summarize-runner@<PROJECT_ID>.iam.gserviceaccount.com
```

注意:

- 閲覧者ではなく編集者にする
- 通知メールは送らなくてよい
- 共有し忘れると Cloud Run が Sheet を読めず、処理が 500 になります

---

## 8. Cloud Run をデプロイする

ブラウザ UI で Cloud Run を作る場合は、この章の代わりに [`cloud-pipeline-gcp-ui.md` の手順 8](cloud-pipeline-gcp-ui.md#8-cloud-run-%E3%82%92%E3%83%96%E3%83%A9%E3%82%A6%E3%82%B6-ui-%E3%81%8B%E3%82%89%E3%83%87%E3%83%97%E3%83%AD%E3%82%A4%E3%81%99%E3%82%8B) を実施します。UI 手順では GitHub リポジトリを Cloud Run に接続し、Cloud Build トリガーで継続デプロイします。

### 8.1 GitHub 書き込み先を決める

ここで設定する `GITHUB_REPOSITORY` は、Cloud Run のコードリポジトリではなく、生成した Obsidian note を commit する Vault リポジトリです。Cloud Run のコードは `jw-summarize-cloud` からデプロイします。

以下を自分の環境に合わせます。

```bash
export GITHUB_REPOSITORY="abebe0210/obsidian-jw"
export GITHUB_BRANCH="main"
export OBSIDIAN_SUMMARY_DIR="01_Talks"
export OBSIDIAN_TRANSCRIPT_DIR="05_Transcription"
```

### 8.2 まず Cloud Run URL なしでデプロイする

初回は Cloud Run URL がまだ分からないため、OIDC audience を仮値で入れてデプロイします。後で正しい URL に更新します。

`jw-summarize-cloud` のリポジトリルートで実行してください。`jw-agent` のルートから実行しないでください。

```bash
gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --region="${REGION}" \
  --set-build-env-vars="GOOGLE_PYTHON_VERSION=3.12.x,GOOGLE_PYTHON_PACKAGE_MANAGER=uv" \
  --service-account="${RUNNER_SA}" \
  --no-allow-unauthenticated \
  --cpu=1 \
  --memory=1Gi \
  --timeout=1800 \
  --min-instances=0 \
  --max-instances=10 \
  --concurrency=1 \
  --command=gunicorn \
  --args="--bind,:8080,--timeout,1800,tools.jw_summarize.webapp:app" \
  --set-env-vars="LLM_PROVIDER=vertexai,LLM_PROFILE=heavy,VERTEX_PROJECT_ID=${PROJECT_ID},VERTEX_LOCATION=${REGION},VERTEX_HEAVY_MODEL=gemini-2.5-pro,VERTEX_LIGHT_MODEL=gemini-2.5-flash,GCP_PROJECT_ID=${PROJECT_ID},GCS_AUDIO_BUCKET=${AUDIO_BUCKET},SHEETS_MANAGEMENT_ID=${SHEET_ID},TASKS_QUEUE_NAME=${QUEUE_NAME},TASKS_LOCATION=${REGION},GITHUB_REPOSITORY=${GITHUB_REPOSITORY},GITHUB_BRANCH=${GITHUB_BRANCH},OBSIDIAN_SUMMARY_DIR=${OBSIDIAN_SUMMARY_DIR},OBSIDIAN_TRANSCRIPT_DIR=${OBSIDIAN_TRANSCRIPT_DIR},CLOUD_RUN_AUDIENCE=https://placeholder.example" \
  --set-secrets="GITHUB_TOKEN=jw-summarize-github-token:latest"
```

`--args` の `tools.jw_summarize.webapp:app` は、`jw-agent` から移行した package path を `jw-summarize-cloud` でもそのまま残す場合の例です。移行時に `jw_summarize_cloud.webapp` のような package に整理した場合は、次のように変更します。

```bash
  --args="--bind,:8080,--timeout,1800,jw_summarize_cloud.webapp:app" \
```

要約処理は 30 秒を超えることがあるため、Cloud Run の `--timeout=1800` だけでなく Gunicorn 側にも `--timeout,1800` を渡します。

このコマンドの意味:

| オプション | 意味 |
|---|---|
| `--source .` | Dockerfile なしでソースから Cloud Build する |
| `--set-build-env-vars` | buildpacks に Python 3.12 と uv を使わせる |
| `--service-account` | Cloud Run の中で使う SA |
| `--no-allow-unauthenticated` | Cloud Run を一般公開しない |
| `--timeout=1800` | 最大 30 分まで処理を待つ |
| `--concurrency=1` | 1 インスタンスで 1 件ずつ処理する |
| `--command=gunicorn` | Flask を本番用 WSGI サーバーで起動する |
| `--args=...--timeout,1800...` | Gunicorn worker が 30 秒で落ちないようにする |
| `--set-secrets` | Secret Manager の token を環境変数として渡す |

デプロイには数分かかります。

### 8.3 Cloud Run URL を取得する

```bash
export CLOUD_RUN_URL="$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --format='value(status.url)')"

echo "${CLOUD_RUN_URL}"
```

出力例:

```text
https://jw-summarize-web-xxxxx-an.a.run.app
```

`/process` の URL も作ります。

```bash
export CLOUD_RUN_PROCESS_URL="${CLOUD_RUN_URL}/process"
```

### 8.4 Cloud Run に正しい audience を設定し直す

アプリ側の OIDC 検証に使う `CLOUD_RUN_AUDIENCE` を Cloud Run URL に更新します。

```bash
gcloud run services update "${SERVICE_NAME}" \
  --region="${REGION}" \
  --update-env-vars="CLOUD_RUN_AUDIENCE=${CLOUD_RUN_URL}"
```

この実装では `CLOUD_RUN_AUDIENCE` が `GOOGLE_OIDC_AUDIENCE` の代わりにも使われます。

### 8.5 Cloud Tasks SA に Cloud Run 呼び出し権限を付ける

```bash
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --region="${REGION}" \
  --member="serviceAccount:${TASKS_SA}" \
  --role="roles/run.invoker"
```

これで `jw-summarize-tasks@...` だけが Cloud Run を呼べます。

### 8.6 起動確認

Cloud Run は一般公開していないため、ブラウザで URL を開くと 403 になるのが正常です。

手元から確認したい場合は Cloud Run proxy を使います。

```bash
gcloud run services proxy "${SERVICE_NAME}" \
  --region="${REGION}" \
  --port=8080
```

別ターミナルで確認します。

```bash
curl http://localhost:8080/healthz
```

期待値:

```json
{"status":"ok"}
```

---

## 9. Cloud Tasks キューを作る

### 9.1 キュー作成

```bash
gcloud tasks queues create "${QUEUE_NAME}" \
  --location="${REGION}" \
  --max-dispatches-per-second=5 \
  --max-concurrent-dispatches=10 \
  --max-attempts=3 \
  --min-backoff=30s \
  --max-backoff=600s \
  --max-doublings=5
```

Cloud Tasks の HTTP timeout にあたる `dispatchDeadline` は、キューではなくタスクごとに設定します。`jw-summarize-cloud` の `scripts/cloud_pipeline/Code.gs` は、Script Property `TASK_DISPATCH_DEADLINE_SECONDS` の値を使って各タスクに `1800s` を設定します。

確認:

```bash
gcloud tasks queues describe "${QUEUE_NAME}" \
  --location="${REGION}"
```

見るポイント:

- `rateLimits.maxDispatchesPerSecond: 5`
- `rateLimits.maxConcurrentDispatches: 10`
- `retryConfig.maxAttempts: 3`
- `retryConfig.maxBackoff: 600s`
- `stackdriverLoggingConfig` は未設定でもよい

---

## 10. Apps Script 実行ユーザーに Cloud Tasks 権限を付ける

Apps Script は `ScriptApp.getOAuthToken()` を使って Cloud Tasks API を呼びます。つまり、Apps Script を実行する人間の Google アカウントに権限が必要です。

```bash
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="user:${APPS_SCRIPT_USER}" \
  --role="roles/cloudtasks.enqueuer"
```

Cloud Tasks が `jw-summarize-tasks@...` の OIDC token を発行できるように、Apps Script 実行ユーザーに Service Account User を付けます。

```bash
gcloud iam service-accounts add-iam-policy-binding "${TASKS_SA}" \
  --member="user:${APPS_SCRIPT_USER}" \
  --role="roles/iam.serviceAccountUser"
```

Cloud Tasks のサービスエージェントにも `jw-summarize-tasks@...` を使う権限を付けます。

```bash
export PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" \
  --format='value(projectNumber)')"

gcloud iam service-accounts add-iam-policy-binding "${TASKS_SA}" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-cloudtasks.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
```

---

## 11. Apps Script を設定する

### 11.1 Apps Script エディタを開く

Spreadsheet で以下を開きます。

```text
拡張機能 → Apps Script
```

### 11.2 `Code.gs` を貼る

`jw-summarize-cloud` の以下の内容を Apps Script の `Code.gs` に貼ります。

```text
scripts/cloud_pipeline/Code.gs
```

既存の空の `myFunction` は削除して構いません。

### 11.3 `appsscript.json` を表示する

Apps Script エディタ左側の歯車アイコン「プロジェクトの設定」を開き、以下を有効にします。

```text
「appsscript.json」マニフェスト ファイルをエディタで表示する
```

左側に `appsscript.json` が出ます。

### 11.4 `appsscript.json` を貼る

`jw-summarize-cloud` の以下の内容を Apps Script の `appsscript.json` に貼ります。

```text
scripts/cloud_pipeline/appsscript.json
```

主な OAuth scope:

| Scope | 理由 |
|---|---|
| `cloud-platform` | Cloud Tasks API / GCS JSON API を呼ぶ |
| `drive` | Form 添付ファイルを読む、コピー後に Drive 側をゴミ箱へ移す |
| `script.external_request` | `UrlFetchApp.fetch` で API を呼ぶ |
| `spreadsheets.currentonly` | 現在の Spreadsheet を読む・更新する |

### 11.5 Script Properties を設定する

Apps Script エディタ左側の歯車アイコン「プロジェクトの設定」を開き、「スクリプト プロパティ」を追加します。

| プロパティ | 値 |
|---|---|
| `GCP_PROJECT_ID` | `<PROJECT_ID>` |
| `TASKS_LOCATION` | `asia-northeast1` |
| `TASKS_QUEUE_NAME` | `jw-summarize-process` |
| `CLOUD_RUN_PROCESS_URL` | `https://...a.run.app/process` |
| `CLOUD_RUN_AUDIENCE` | `https://...a.run.app` |
| `CLOUD_TASKS_SERVICE_ACCOUNT` | `jw-summarize-tasks@<PROJECT_ID>.iam.gserviceaccount.com` |
| `GCS_AUDIO_BUCKET` | `<PROJECT_ID>-jw-summarize-audio` |
| `FAILED_AFTER_MINUTES` | `120` |
| `TASK_DISPATCH_DEADLINE_SECONDS` | `1800` |

任意でフォーム列名を変えた場合だけ、以下も設定します。

| プロパティ | 既定値 |
|---|---|
| `FORM_INPUT_TYPE_COLUMN` | `入力種別` |
| `FORM_URL_COLUMN` | `URL` |
| `FORM_TEXT_COLUMN` | `本文` |
| `FORM_AUDIO_COLUMN` | `音声ファイル` |
| `FORM_TITLE_COLUMN` | `タイトル` |
| `FORM_TAGS_COLUMN` | `タグ` |

### 11.6 初回認可を行う

Apps Script エディタ上部の関数選択で `installMonitorTrigger` を選び、実行します。

初回は Google の認可画面が出ます。自分のアカウントで許可してください。

警告が出る場合:

1. 「詳細」を押す
2. プロジェクト名へ移動
3. 許可

これは自分の Spreadsheet に紐づく未公開スクリプトなので、初回は警告が出ることがあります。

### 11.7 Form submit トリガーを追加する

Apps Script エディタ左側の時計アイコン「トリガー」を開き、「トリガーを追加」を押します。

設定:

| 項目 | 値 |
|---|---|
| 実行する関数 | `onFormSubmit` |
| 実行するデプロイ | `Head` |
| イベントのソース | `スプレッドシートから` |
| イベントの種類 | `フォーム送信時` |

保存します。

### 11.8 監視トリガーを確認する

`installMonitorTrigger` を実行済みなら、トリガー一覧に `monitorQueuedRows` があるはずです。

| 項目 | 値 |
|---|---|
| 実行する関数 | `monitorQueuedRows` |
| イベントのソース | `時間主導型` |
| 間隔 | 15 分ごと |

このトリガーが、`queued` のまま 120 分を超えた行を `failed` にします。

---

## 12. 動作確認

### 12.1 Spreadsheet の列を確認する

フォームを 1 件送信すると、Apps Script が以下の列を自動追加します。

```text
row_id
status
gcs_uri
github_url
error
enqueued_at
finished_at
```

### 12.2 text 入力で最初のテストをする

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

1. `status` が `queued` になる
2. `enqueued_at` が入る
3. 数分後に `status` が `done` になる
4. `github_url` に commit URL が入る
5. GitHub リポジトリに summary note と transcript note が追加される

### 12.3 Cloud Tasks を確認する

```bash
gcloud tasks queues describe "${QUEUE_NAME}" \
  --location="${REGION}"
```

処理中のタスクを見たい場合:

```bash
gcloud tasks list \
  --queue="${QUEUE_NAME}" \
  --location="${REGION}"
```

成功したタスクはキューから消えます。空なら正常です。

### 12.4 Cloud Run ログを確認する

```bash
gcloud run services logs read "${SERVICE_NAME}" \
  --region="${REGION}" \
  --limit=100
```

エラーを見るとき:

```bash
gcloud run services logs read "${SERVICE_NAME}" \
  --region="${REGION}" \
  --limit=200 \
  --log-filter="severity>=ERROR"
```

### 12.5 音声入力をテストする

次に短い mp3/m4a/wav で試します。

Form:

| 項目 | 値 |
|---|---|
| 入力種別 | `audio` |
| 音声ファイル | 1 分程度の音声 |
| タイトル | 任意 |
| タグ | `audio-test` |

期待する流れ:

1. Apps Script が Drive 添付ファイルを GCS にコピーする
2. `gcs_uri` に `gs://.../incoming/<row_id>.<ext>` が入る
3. Drive 側の添付ファイルがゴミ箱に移動される
4. Cloud Run が Gemini で文字起こしする
5. transcript note と summary note が同一 commit で作成される

GCS に入ったか確認:

```bash
gcloud storage ls "gs://${AUDIO_BUCKET}/incoming/"
```

---

## 13. よくある失敗と直し方

### 13.1 Form 送信後すぐ `failed` になる

原因は Apps Script 側です。Cloud Run までは到達していません。

Spreadsheet の `error` 列を見ます。

よくある原因:

| エラー | 原因 | 対処 |
|---|---|---|
| `Missing script property` | Script Properties の不足 | 手順 11.5 を見直す |
| `Cloud Tasks enqueue failed: HTTP 400` | Apps Script から Cloud Tasks へ渡した値が不正 | `TASK_DISPATCH_DEADLINE_SECONDS` は `1800s` ではなく `1800`。`CLOUD_RUN_PROCESS_URL`、`CLOUD_RUN_AUDIENCE`、`CLOUD_TASKS_SERVICE_ACCOUNT` も確認 |
| `Cloud Tasks enqueue failed: HTTP 404` | Apps Script が見ている project / location / queue / service account が存在しない | `GCP_PROJECT_ID` は表示名ではなくプロジェクト ID。`TASKS_LOCATION` と `TASKS_QUEUE_NAME` が実際のキューと一致するか確認 |
| `Cloud Tasks enqueue failed: HTTP 403` | Apps Script 実行ユーザーに Cloud Tasks 権限がない | 手順 10 を見直す |
| `GCS upload failed: HTTP 403` | Apps Script 実行ユーザーに GCS 権限がない | 手順 5.3 を見直す |
| `Missing Drive file id` | 音声ファイル列名が違う、またはファイル添付でない | Form の質問名と Script Properties を確認 |

### 13.2 `queued` のまま進まない

Cloud Tasks か Cloud Run 側で失敗しています。

確認順:

1. Cloud Tasks にタスクが残っているか見る
2. Cloud Run ログを見る
3. 120 分後に `failed` へ自動更新されるか見る

`Timed out waiting for successful Cloud Run completion after 120 minutes.` は Apps Script の監視処理が付けるエラーです。Cloud Tasks への投入は成功していますが、Cloud Run が `status=done` と `github_url` を Spreadsheet へ書き戻せていません。Cloud Run のリクエストログだけでなく、同じ時刻の stderr / application log も確認します。

Cloud Tasks:

```bash
gcloud tasks list \
  --queue="${QUEUE_NAME}" \
  --location="${REGION}"
```

Cloud Run logs:

```bash
gcloud run services logs read "${SERVICE_NAME}" \
  --region="${REGION}" \
  --limit=200
```

### 13.3 Cloud Run が 401 を返す

アプリ側の OIDC 検証に失敗しています。

確認:

```bash
gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --format='value(spec.template.spec.containers[0].env)'
```

見るポイント:

- `CLOUD_RUN_AUDIENCE` が `https://...a.run.app` になっているか
- Apps Script の `CLOUD_RUN_AUDIENCE` も同じ値か
- Apps Script の `CLOUD_RUN_PROCESS_URL` は末尾 `/process` 付きか
- `WEBHOOK_SHARED_SECRET` を Cloud Run に設定していないか

### 13.4 Cloud Run が 403 になる

Cloud Run IAM で拒否されています。

`jw-summarize-tasks@...` に `run.invoker` が付いているか確認します。

```bash
gcloud run services get-iam-policy "${SERVICE_NAME}" \
  --region="${REGION}"
```

なければ再実行:

```bash
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --region="${REGION}" \
  --member="serviceAccount:${TASKS_SA}" \
  --role="roles/run.invoker"
```

### 13.5 Cloud Run が Sheet を読めない

Cloud Run 実行 SA が Spreadsheet に共有されていない可能性が高いです。

Spreadsheet の共有設定で、以下が編集者になっているか確認します。

```text
jw-summarize-runner@<PROJECT_ID>.iam.gserviceaccount.com
```

共有済みなのに読めない場合は、Cloud Run の最新リビジョンが本当に `RUNNER_SA` で動いているか確認します。

```bash
gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --format="value(spec.template.spec.serviceAccountName)"
```

空、または `<PROJECT_NUMBER>-compute@developer.gserviceaccount.com` が出る場合は、Cloud Run がデフォルト Compute SA で動いています。`--service-account="${RUNNER_SA}"` で再デプロイするか、その SA も Spreadsheet に編集者として共有します。

### 13.6 GitHub commit で失敗する

よくある原因:

| 原因 | 対処 |
|---|---|
| `GITHUB_REPOSITORY` が `owner/repo` のまま、または実リポジトリではない | `abebe0210/obsidian-jw` のような実際の Vault リポジトリに直す |
| token に Contents write がない | GitHub token 権限を直す |
| branch 名が違う | `GITHUB_BRANCH` を直す |
| 同時 push 競合 | Cloud Tasks の並列数を一時的に下げる |

並列数を下げる例:

```bash
gcloud tasks queues update "${QUEUE_NAME}" \
  --location="${REGION}" \
  --max-concurrent-dispatches=1
```

### 13.7 Vertex AI で失敗する

よくある原因:

| 原因 | 対処 |
|---|---|
| Vertex AI API が無効 | 手順 2 を再実行 |
| `jw-summarize-runner` に `aiplatform.user` がない | 手順 4.1 を再実行 |
| `Publisher Model ... was not found or your project does not have access to it` | `VERTEX_HEAVY_MODEL=gemini-2.5-pro` に戻す |
| `WORKER TIMEOUT` | `--args` に `--timeout,1800` が入っているか確認 |
| quota 超過 | 少し待つ、または Cloud Tasks の並列数を下げる |

---

## 14. 運用方法

### 14.1 普段見る場所

基本は Spreadsheet を見れば十分です。

| status | 意味 |
|---|---|
| `queued` | 受付済み。処理中またはリトライ待ち |
| `done` | 成功。`github_url` に成果物 commit |
| `failed` | 受付時点で失敗、または一定時間成功しなかった |

### 14.2 手動で再実行したい場合

一番簡単なのは、フォームから同じ内容をもう一度送ることです。

同じ行を再実行したい場合は、手動で Cloud Tasks に同じ `{ row_id, sheet_id }` を登録する必要があります。初心者向け運用では、再送信を推奨します。

### 14.3 デプロイし直す

`jw-summarize-cloud` のコードを変更したら、Cloud Run を再デプロイします。このコマンドも `jw-summarize-cloud` のリポジトリルートで実行します。

```bash
gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --region="${REGION}" \
  --set-build-env-vars="GOOGLE_PYTHON_VERSION=3.12.x,GOOGLE_PYTHON_PACKAGE_MANAGER=uv" \
  --service-account="${RUNNER_SA}" \
  --no-allow-unauthenticated \
  --cpu=1 \
  --memory=1Gi \
  --timeout=1800 \
  --min-instances=0 \
  --max-instances=10 \
  --concurrency=1 \
  --command=gunicorn \
  --args="--bind,:8080,--timeout,1800,tools.jw_summarize.webapp:app"
```

環境変数を変えない再デプロイなら、既存の env / secret は基本的に維持されます。

### 14.4 環境変数だけ変える

例: GitHub branch を変える。

```bash
gcloud run services update "${SERVICE_NAME}" \
  --region="${REGION}" \
  --update-env-vars="GITHUB_BRANCH=main"
```

例: Gemini モデルを安定版へ戻す。

```bash
gcloud run services update "${SERVICE_NAME}" \
  --region="${REGION}" \
  --update-env-vars="VERTEX_HEAVY_MODEL=gemini-2.5-pro,VERTEX_LIGHT_MODEL=gemini-2.5-flash"
```

`gcloud run services update` に `--clear-command` や `--clear-args` はありません。Cloud Run の command / args をコンテナ既定に戻す場合は、空文字を渡します。ただし、既定 Entrypoint を持たないイメージでは起動できなくなるため、通常は `gcloud run deploy` で `--command` / `--args` を明示し直す方が安全です。

```bash
gcloud run services update "${SERVICE_NAME}" \
  --region="${REGION}" \
  --command="" \
  --args=""
```

### 14.5 GitHub token を更新する

```bash
printf "%s" "<NEW_GITHUB_TOKEN>" | gcloud secrets versions add jw-summarize-github-token \
  --data-file=-
```

Cloud Run は `jw-summarize-github-token:latest` を参照しているため、通常は次回起動から新しい version が使われます。すぐ反映したい場合は Cloud Run を再デプロイまたはサービス更新します。

```bash
gcloud run services update "${SERVICE_NAME}" \
  --region="${REGION}"
```

---

## 15. 削除したいとき

テスト環境を消す場合のコマンドです。消すと復旧できないものがあるので注意してください。

Cloud Run:

```bash
gcloud run services delete "${SERVICE_NAME}" \
  --region="${REGION}"
```

Cloud Tasks:

```bash
gcloud tasks queues delete "${QUEUE_NAME}" \
  --location="${REGION}"
```

GCS バケット:

```bash
gcloud storage rm --recursive "gs://${AUDIO_BUCKET}"
gcloud storage buckets delete "gs://${AUDIO_BUCKET}"
```

Secret:

```bash
gcloud secrets delete jw-summarize-github-token
```

サービスアカウント:

```bash
gcloud iam service-accounts delete "${RUNNER_SA}"
gcloud iam service-accounts delete "${TASKS_SA}"
```

Spreadsheet / Form / Apps Script は Google Drive 側で削除します。

---

## 16. 参考リンク

- Cloud Run source deploy: https://docs.cloud.google.com/run/docs/deploying-source-code
- Cloud Tasks HTTP target / OIDC: https://cloud.google.com/tasks/docs/creating-http-target-tasks
- Cloud Storage lifecycle: https://cloud.google.com/storage/docs/lifecycle
- Apps Script manifest scopes: https://developers.google.com/apps-script/manifest
- Apps Script installable triggers: https://developers.google.com/apps-script/guides/triggers/installable
