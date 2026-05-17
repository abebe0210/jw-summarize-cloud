# 設計書: JW.org コンテンツ要約パイプラインのクラウド化

- ステータス: ドラフト(レビュー反映済み / レビュアー: Codex)
- 作成日: 2026-05-04
- 対象リポジトリ:
  - `jw-summarize-cloud`: Cloud Run / Apps Script / GCP デプロイ資産を管理する本番サービスリポジトリ
  - `jw-agent`: エージェントが各種自動化タスクを実行するハーネスリポジトリ
- 関連既存ツール: `jw-agent` の `tools/jw_subtitles`, `tools/jw_summarize`(対象外: `tools/jw_podcast`)
- 関連ドキュメント:
  - [`docs/design/architecture.md`](architecture.md): 構成図 / シーケンス図 / モジュール依存グラフ / 各スクリプトの役割をまとめた図解版
  - [`docs/deploy/cloud-pipeline-gcp-ui.md`](../deploy/cloud-pipeline-gcp-ui.md), [`docs/deploy/cloud-pipeline-gcp.md`](../deploy/cloud-pipeline-gcp.md): デプロイ手順

---

## 1. 目的とスコープ

### 1.1 目的
JW.org の動画 URL / テキスト / 音声ファイルを入力として、字幕取得 → LLM 要約 → GitHub(Obsidian Vault リポジトリ)への commit/push までを自動実行する。

実行経路は 2 つに分ける。

- 人間は Google Form から投入し、`jw-summarize-cloud` の Cloud Run パイプラインで処理する
- エージェントは `jw-agent` 内のスキル / コマンド / ツールから投入し、エージェントハーネスとしての作業性を優先する

`jw-summarize-cloud` は人間向け常時稼働サービス、`jw-agent` はエージェント作業場として扱う。両者は同じ Obsidian Vault 出力契約を守るが、デプロイ資産や本番運用責務は共有しない。

### 1.2 スコープに含むもの
- Google Form を入力 UI とする受付経路
- Google スプレッドシートによる管理台帳(キュー兼ステータス管理)
- Cloud Tasks による非同期化と並列ディスパッチ
- Cloud Run(Flask)上での要約パイプライン実行
- Vertex AI Gemini 2.5 への直接入力(テキスト/音声)
- GitHub への自動 commit/push
- `jw-agent` から実行されるエージェント向けノート作成経路との出力互換性

### 1.3 スコープ外
- `jw_podcast`(NotebookLM 経由のポッドキャスト生成):ブラウザ自動化が必要で、Cloud Run 無料枠と整合しないため別フローとして将来検討する
- Obsidian Vault 側のレンダリング・公開フロー
- 多言語対応(現行どおり日本語前提)
- `jw-agent` のエージェントハーネス全体の設計。ここでは Cloud Pipeline と接続契約だけを扱う

### 1.4 想定利用量
- 投入頻度: 1 日あたり数件、ただし「いっぺんに複数件投入」される場面あり(並列処理が必要)
- 音声長さ: 最大 60 分程度
- 処理時間: 1 件あたり 30 分以内に収まる前提
- 同時実行最大: 暫定 10 並列を上限(`max-instances=10`)

---

## 2. 主要な設計判断

| # | 判断 | 根拠 |
|---|------|------|
| D1 | 受付は **Google Form**、台帳は **Spreadsheet** | 人/AI 双方が可読、Google Workspace で完結、Apps Script から触れる |
| D2 | 非同期化に **Cloud Tasks** を採用 | Apps Script の HTTP タイムアウトは 6 分。処理本体は 30 分以内に収まるため Cloud Tasks HTTP target の範囲で扱える |
| D3 | 実行基盤は **Cloud Run(リクエスト駆動)** | 無料枠と並列スケールを両立。処理が 30 分を超えない前提なので Cloud Run Jobs は初期構成では採用しない |
| D4 | 音声は **Gemini 2.5 への直接入力**(GCS 経由) | 外部 STT や別キューを挟まず、同一 Cloud Run ジョブ内で文字起こしと要約を実行する |
| D5 | NotebookLM(`jw_podcast`)は **本パイプラインに含めない** | ヘッドレスブラウザが必要で無料枠から外れる |
| D6 | リトライは **Cloud Tasks の自動リトライ** に委譲 | 実装シンプル化。最大 3 回まで |
| D7 | タイトル生成は **LLM では行わない** | 過剰生成を避け、ユーザー意図を尊重。空欄時は決定的フォールバックを定義 |
| D8 | GCP プロジェクトは **`VERTEX_PROJECT_ID` の既存プロジェクトを流用**(後で切替可能とする) | 初期構築コスト削減 |
| D9 | GitHub のコミット先パスは **既存 `OBSIDIAN_SUMMARY_DIR` と共通** | 入力種別による分岐を避け、消費者(Obsidian)側のタクソノミーを単純に保つ |
| D10 | 既存 `/process` 実装との互換性は維持しない | 本設計では Cloud Tasks 起点の `{ row_id, sheet_id }` 契約を正とし、現行 Web API / データモデルは置換対象とする |
| D11 | Cloud Run 処理失敗時は Sheet を更新しない | 成功時のみ `done` と成果物 URL を書き込む。一定時間 `done` にならない行は監視処理が `failed` に自動確定する |
| D12 | 音声入力でも文字起こしノートを生成する | 音声は同一 Cloud Run ジョブ内で Gemini により文字起こしし、そのテキストを要約入力と transcript note の正本にする |
| D13 | Apps Script → Cloud Tasks は Apps Script 実行ユーザーの OAuth トークンを使う | サービスアカウントキーを配布せず、`ScriptApp.getOAuthToken()` + Cloud Tasks API でキュー登録する。実行ユーザーに `roles/cloudtasks.enqueuer` と Cloud Tasks OIDC 用 SA への `roles/iam.serviceAccountUser` を付与する |
| D14 | GCP リージョンは **`asia-northeast1`** に統一する | 利用者に近い東京リージョンへ統一し、Run / Tasks / GCS / Vertex の設定を揃える |
| D15 | Cloud Run デプロイ資産は **`jw-summarize-cloud` に分離**する | `jw-agent` の主用途はエージェントハーネスであり、GCP 本番サービスの依存・設定・CI/CD を同居させない |
| D16 | 2 リポ間の共有点は **ソースコードではなく入出力契約**を基本にする | 移行後も `jw-agent` の作業性を最優先し、必要な共通化は後から小さな core package として切り出す |

---

## 3. 全体アーキテクチャ

### 3.0 リポジトリ境界

2 リポジトリで運用する。

| リポジトリ | 主用途 | 持つもの | 持たないもの |
|---|---|---|---|
| `jw-agent` | エージェントハーネス | skills, commands, ローカル実行ツール, エージェント向けノート作成フロー, 実験ログ | Cloud Run の継続デプロイ設定、本番用 Apps Script の正本、GCP インフラ設定 |
| `jw-summarize-cloud` | 人間向け Cloud Pipeline | Flask webapp, Cloud Tasks / Sheets / GCS 連携, Apps Script, Cloud Run デプロイ手順, 本番用依存関係 | エージェントハーネス全体、Anki / Podcast など Cloud Pipeline 外の自動化 |

`jw-agent` からのエージェント実行は `jw-agent` リポジトリ内で完結させる。人間が Google Form から投入したものだけが `jw-summarize-cloud` の Cloud Run 経路に入る。両者は最終的に同じ Obsidian Vault へ summary note / transcript note を書き込むため、出力パス、frontmatter、タイトル決定ルール、transcript 保存方針を互換契約として合わせる。

移行直後は `jw-summarize-cloud` に `jw-agent` 由来の必要コードをコピーしてよい。コード重複が運用上の問題になった時点で、字幕取得・要約・ノート生成などの純粋ロジックだけを `jw-summarize-core` のような小さな共有パッケージへ切り出す。

### 3.1 構成図

詳細な構成図 / シーケンス図 / モジュール依存グラフは [`architecture.md`](architecture.md) を参照。ここでは経路の俯瞰のみ示す。

```
Human route (`jw-summarize-cloud`)

Google Form
  -> Spreadsheet
  -> Apps Script
  -> Cloud Tasks
  -> Cloud Run: jw-summarize-web
  -> Vertex AI Gemini
  -> GitHub / Obsidian Vault

Agent route (`jw-agent`)

Agent skill / command / tool
  -> local jw-agent harness
  -> LLM / local tool execution
  -> GitHub / Obsidian Vault
```

### 3.2 主要シーケンス

人間の Google Form 経路:

```
利用者 → Form: 入力種別/値/タイトル/タグ を送信
Form → Sheet: 行追加(ステータス=queued)
Sheet → Apps Script: onFormSubmit 起動
Apps Script → Cloud Tasks: enqueue { row_id, sheet_id }
Cloud Tasks → Cloud Run: POST /process (OIDC 認証)
Cloud Run → (jw_subtitles | GCS | passthrough): 入力正規化
Cloud Run → Vertex AI: 文字起こし(audio のみ) / 要約生成
Cloud Run → GitHub: commit & push
Cloud Run → Sheet: ステータス=done, GitHub URL/完了日時記録
Cloud Run → Cloud Tasks: 200 OK
```

エージェントの `jw-agent` 経路:

```
エージェント → jw-agent skill/command: URL / text / audio / タスク指示を投入
jw-agent → 既存ツール群: 字幕取得 / 要約 / ノート生成を実行
jw-agent → GitHub / Obsidian Vault: 同じ出力契約で commit / 保存
```

この経路は Cloud Tasks や Google Form を必須にしない。エージェントが作業中に使う依存、プロンプト、メモリ、コマンドを `jw-agent` 側に置き、Cloud Run 本番サービスの都合でハーネスを重くしない。

失敗時:

```
Cloud Run: 例外発生
Cloud Run → Cloud Tasks: 5xx を返す
Cloud Tasks: 指数バックオフで自動リトライ(最大 3 回)
3 回超: タスクは終了し、Sheet 行は `queued` のまま残る
監視トリガー: 一定時間 `done` にならない行を `failed` に自動更新する
```

---

## 4. コンポーネント詳細設計

### 4.1 Google Form

| 項目 | 型 | 必須 | 備考 |
|------|----|------|------|
| 入力種別 | ラジオ | ✓ | `url` / `text` / `audio` |
| URL | 短文回答 | 種別=url で必須 | jw.org の動画ページ URL |
| 本文 | 段落回答 | 種別=text で必須 | 任意長 |
| 音声ファイル | ファイル添付 | 種別=audio で必須 | mp3/m4a/wav、最大 ~60 分 |
| タイトル | 短文回答 | 任意 | 空欄時は §4.6 のフォールバック |
| タグ | 短文回答 | 任意 | カンマ区切り |

注: Form の「条件分岐表示」で種別ごとの必須項目を出し分ける。

### 4.2 Spreadsheet 管理台帳

Form 連携シートに、Apps Script で以下の列を追加(Form が自動生成する列の右側):

| 列 | 内容 | 書き込み主体 |
|----|------|--------------|
| `row_id` | UUID(行を一意に識別) | Apps Script |
| `status` | `queued` / `done` / `failed` | Apps Script(初期)、Cloud Run(成功時)、Apps Script 監視トリガー(失敗確定時) |
| `gcs_uri` | 音声入力時の GCS URI | Apps Script |
| `github_url` | commit URL | Cloud Run |
| `error` | 受付失敗または自動失敗確定理由 | Apps Script、Apps Script 監視トリガー |
| `enqueued_at` | Cloud Tasks 登録日時(JST) | Apps Script |
| `finished_at` | 処理完了日時(JST) | Cloud Run |

Cloud Run は処理開始時・失敗時には Sheet を更新しない。これは、リトライ中の一時失敗で台帳を頻繁に書き換えないためと、成功していない行を単純に見つけられるようにするためである。`failed` は Cloud Run が直接書く状態ではなく、Apps Script 側の受付失敗、または後述の監視トリガーで自動確定する状態とする。

### 4.3 Apps Script(onFormSubmit トリガー)

責務:
1. 受付行に `row_id`(UUID)を採番し、`status=queued` を書き込む
2. 種別=audio の場合: Form 添付ファイル(Drive 上)を **GCS バケットへコピー** し、`gcs_uri` 列に記録
3. `ScriptApp.getOAuthToken()` を使って Cloud Tasks API を呼び、`{ row_id, sheet_id }` をエンキューする
4. Drive 上の元音声は GCS コピー後に削除(Drive 容量保全)

エラー時の挙動:
- GCS 転送失敗・キュー登録失敗は `status=failed`、`error` 列にメッセージを書き込む(Cloud Run には到達させない)

### 4.3.1 Apps Script(監視トリガー)

時間主導トリガーで 15 分ごとに管理台帳を走査し、以下の条件に合う行を `failed` に自動更新する:

- `status=queued`
- `enqueued_at` から 120 分以上経過
- `github_url` が空

`error` には `Timed out waiting for successful Cloud Run completion after 120 minutes.` のような定型メッセージを記録する。120 分は、Cloud Tasks の最大 3 試行がそれぞれ 30 分近く実行された場合とバックオフを吸収する初期値である。

### 4.4 Cloud Tasks Queue

| 項目 | 値 |
|------|----|
| Queue 名 | `jw-summarize-process` |
| Location | `asia-northeast1` |
| Max dispatches per second | 5 |
| Max concurrent dispatches | 10(= Cloud Run `max-instances`) |
| Dispatch deadline | タスク作成時に `dispatchDeadline=1800s`(30 分)を指定 |
| Retry config | `max_attempts=3`, `min_backoff=30s`, `max_backoff=600s` |
| Auth | Cloud Run 起動用 SA に対する OIDC トークン |

### 4.5 Cloud Run サービス `jw-summarize-web`

#### 4.5.1 ランタイム
- ベース: Flask + gunicorn。既存 `tools/jw_summarize/webapp.py` との互換性は前提にしない
- イメージ: Python 3.12 slim + Playwright **不要**(`jw_podcast` を含めないため)
- リソース: `--cpu=1 --memory=1Gi --timeout=1800 --min-instances=0 --max-instances=10 --concurrency=1`
  - `concurrency=1`: 1 リクエスト = 1 ジョブ(LLM 呼出は CPU/メモリを占有)
  - `timeout=1800`: Cloud Tasks の HTTP dispatch deadline と揃え、処理時間は 30 分以内に収める

#### 4.5.2 エンドポイント

| Method | Path | 認証 | 用途 |
|--------|------|------|------|
| POST | `/process` | OIDC(Cloud Tasks SA) | 行 ID を受け取り処理本体を実行 |
| GET | `/healthz` | 不要 | 起動確認 |
| POST | `/summarize` | 共有シークレット(任意) | 将来の手動投入/互換用。初期必須ではない |

`/process` のリクエスト/レスポンス:

```json
// Request
{ "row_id": "uuid-xxxx", "sheet_id": "1AbC..." }

// Response (success)
{ "status": "done", "github_url": "https://github.com/owner/repo/commit/..." }

// Response (failure) — 5xx を返してリトライさせる
{ "status": "retrying", "error": "..." }
```

#### 4.5.3 内部処理パイプライン

```python
# 擬似コード
def process(row_id, sheet_id):
    row = sheets.get_row(sheet_id, row_id)            # immutable read
    if row.status == "done":
        return {"status": "done", "github_url": row.github_url}

    transcript = normalize_input(row)                 # → transcript text
    title = resolve_title(row, transcript)            # §4.6
    summary = summarizer.run(transcript, title=title)  # Vertex Gemini 2.5
    commit_url = github_publisher.publish(            # 既存 github_publisher 流用
        title=title, summary=summary, transcript=transcript, tags=row.tags
    )

    sheets.update(row_id, status="done",
                  github_url=commit_url, finished_at=now_jst())
    return {"status": "done", "github_url": commit_url}
```

`normalize_input` の分岐:

| 種別 | 処理 |
|------|------|
| `url` | `jw_subtitles.fetch(url)` で VTT → 平文化 |
| `text` | そのまま |
| `audio` | `gcs_uri` から `Part.from_uri(mime_type, uri)` を構築し、Gemini に文字起こしさせたテキストを返す |

処理中に例外が発生した場合、Cloud Run は Sheet を更新せず 5xx を返す。Cloud Tasks は同じ `{ row_id, sheet_id }` を再実行する。再実行時にすでに `status=done` の場合は冪等処理として即 200 を返す。

音声入力では、Cloud Run 内で以下の順に処理する:

1. GCS URI を Gemini に渡して日本語文字起こしを生成する
2. 生成された文字起こしテキストを transcript note として保持する
3. 同じ文字起こしテキストを要約入力として使う
4. summary note と transcript note を同一 commit で GitHub に書き込む

この方針では、外部 STT サービスや別キューは使わない。ただし、要約ノートだけでなく文字起こしノートも必ず生成する。

### 4.6 タイトル決定ルール(LLM 不使用)

D7 に基づき、決定論的に解決する:

| 種別 | フォーム入力あり | フォーム入力なし(フォールバック) |
|------|------------------|--------------------------------|
| url | フォーム値を採用 | JW.org ページの `<title>` を取得して採用 |
| text | フォーム値を採用 | **エラー**(text 種別ではタイトル必須に Form 側でバリデーション) |
| audio | フォーム値を採用 | 元ファイル名(拡張子除去)を採用 |

備考: Form の「必須」設定だけでは「audio のときタイトル必須」のような条件付き必須は表現しづらいため、text のみ Form 上で必須化し、url/audio はファイルバックを許す。

### 4.7 音声ハンドリング

- Apps Script: Drive 添付 → GCS バケット `gs://<project>-jw-summarize-audio/incoming/<row_id>.<ext>` へ転送
- GCS Lifecycle: `incoming/` プレフィックスは **7 日後に自動削除**(無料枠 5GB 保護)
- Cloud Run: GCS URI を Vertex AI に渡す(ファイル本体を Cloud Run に DL しない → メモリ節約)
- MIME: 拡張子から `audio/mpeg` / `audio/mp4` / `audio/wav` を解決

### 4.8 GitHub publisher

`jw-agent` の既存 `tools/jw_summarize/github_publisher.py` を初期移行で `jw-summarize-cloud` に移して利用する。コミット先は `OBSIDIAN_SUMMARY_DIR`(D9)。`tags` 列の値は本文 frontmatter に注入する。

---

## 5. 認証・シークレット

| 経路 | 方式 |
|------|------|
| Apps Script → Cloud Tasks | `ScriptApp.getOAuthToken()` + Cloud Tasks API。Apps Script 実行ユーザーに `roles/cloudtasks.enqueuer` と Cloud Tasks OIDC 用 SA への `roles/iam.serviceAccountUser` を付与 |
| Cloud Tasks → Cloud Run | OIDC トークン(`audience` = Cloud Run URL) |
| Cloud Run → Vertex AI | 実行 SA の `roles/aiplatform.user` |
| Cloud Run → GCS | 実行 SA の `roles/storage.objectAdmin`(対象バケットに限定) |
| Cloud Run → Sheets API | 実行 SA をシートに編集者として共有 |
| Cloud Run → GitHub | Secret Manager から `GITHUB_TOKEN` 取得 |
| Cloud Run `/summarize`(任意) | `WEBHOOK_SHARED_SECRET`(Secret Manager) |

Secret Manager 管理対象: `GITHUB_TOKEN`, `WEBHOOK_SHARED_SECRET`, (将来) `OPENAI_API_KEY`

---

## 6. 環境変数(Cloud Run)

`jw-summarize-cloud` の `.env.example` に以下を定義する:

```
# 新規
GCP_PROJECT_ID=                       # D8 既存プロジェクト
GCS_AUDIO_BUCKET=                     # 音声受け渡し用
SHEETS_MANAGEMENT_ID=                 # 管理台帳の Spreadsheet ID
TASKS_QUEUE_NAME=jw-summarize-process
TASKS_LOCATION=asia-northeast1
CLOUD_RUN_AUDIENCE=                   # OIDC audience(Cloud Run URL)

# 既存(流用)
VERTEX_PROJECT_ID, VERTEX_LOCATION, VERTEX_HEAVY_MODEL
GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_BRANCH
OBSIDIAN_SUMMARY_DIR
WEBHOOK_SHARED_SECRET
```

---

## 7. デプロイ・運用

実際の構築手順は `jw-summarize-cloud/docs/deploy/` に置く。移行が完了するまでは `jw-agent/docs/deploy/` の手順を作業用の正として使い、移行完了後に同じ内容を `jw-summarize-cloud` 側へ移す。

ブラウザ UI から作業する場合は [`docs/deploy/cloud-pipeline-gcp-ui.md`](../deploy/cloud-pipeline-gcp-ui.md)、CLI で作業する場合は [`docs/deploy/cloud-pipeline-gcp.md`](../deploy/cloud-pipeline-gcp.md) を使う。どちらの場合も Cloud Run の接続先 / `--source` は `jw-agent` ではなく `jw-summarize-cloud` とする。

### 7.0 リポジトリ移行手順

`jw-summarize-cloud` は Cloud Run 本番サービスとして新規作成する。初期移行では、まず動くサービスを切り出すことを優先し、共通パッケージ化は後回しにする。

移すもの:

| 移行元 | 移行先 | 備考 |
|---|---|---|
| `tools/jw_summarize/webapp.py` | `jw_summarize_cloud/webapp.py` または `tools/jw_summarize/webapp.py` | Cloud Run entrypoint の正本 |
| `tools/jw_summarize/cloud_pipeline.py` | 同等モジュール | Sheet 行を処理する本体 |
| `tools/jw_summarize/sheets.py` | 同等モジュール | Spreadsheet 管理台帳 client |
| `tools/jw_summarize/auth.py` | 同等モジュール | Cloud Tasks OIDC 検証 |
| `tools/jw_summarize/audio.py` | 同等モジュール | GCS 音声を Gemini に渡す処理 |
| `tools/jw_summarize/github_publisher.py` | 同等モジュール | Obsidian Vault への commit |
| `tools/jw_subtitles/` の必要部分 | 同等モジュール | URL 入力の字幕取得 |
| `scripts/cloud_pipeline/` | `scripts/cloud_pipeline/` | Apps Script の正本 |
| `docs/deploy/` | `docs/deploy/` | GCP デプロイ手順の正本 |
| Cloud Run 用依存だけの `pyproject.toml` | repo root | Anki / Podcast / agent-only 依存は入れない |

`jw-agent` に残すもの:

| 領域 | 理由 |
|---|---|
| skills / commands | エージェントが日常タスクを実行する入口 |
| ローカル要約・ノート作成ツール | エージェント実行経路のため |
| Cloud Pipeline へのリンクや運用メモ | エージェントが本番サービスの仕様を参照できるようにするため |

移行後、Cloud Run の GitHub 連携は `jw-summarize-cloud` の `main` または `deploy/prod` ブランチを監視する。`jw-agent` への push が Cloud Run の本番デプロイを発火しない状態を正とする。

### 7.1 デプロイ手順(初回)
1. GCP プロジェクト確認 / 必要 API 有効化(Run, Tasks, Storage, Sheets, AI Platform, Secret Manager)
2. サービスアカウント 2 種を作成
   - `jw-summarize-runner@…`(Cloud Run 実行用)
   - `jw-summarize-tasks@…`(Cloud Tasks → Cloud Run 用、OIDC 発行元)
3. GCS バケット作成 + Lifecycle 設定
4. Secret Manager にシークレット投入
5. `jw-summarize-cloud` から Cloud Run デプロイ
6. Cloud Tasks キュー作成
7. Spreadsheet 作成 → Apps Script デプロイ → Form 連携
8. Form を作成し連携シートに紐付け

Apps Script の Script Properties:

```
GCP_PROJECT_ID=
TASKS_LOCATION=asia-northeast1
TASKS_QUEUE_NAME=jw-summarize-process
CLOUD_RUN_PROCESS_URL=https://...
CLOUD_RUN_AUDIENCE=https://...
CLOUD_TASKS_SERVICE_ACCOUNT=jw-summarize-tasks@...
GCS_AUDIO_BUCKET=
FAILED_AFTER_MINUTES=120
TASK_DISPATCH_DEADLINE_SECONDS=1800
```

### 7.2 監視
- Cloud Run のリクエストログ・エラーレートは Cloud Logging で確認
- 処理結果は **Spreadsheet を一次監視窓口** とする
- Apps Script 監視トリガーが `queued` のまま 120 分を超えた行を `failed` に自動更新する
- Cloud Tasks のキュー深さ・リトライ回数を Cloud Monitoring ダッシュボードで可視化(任意)

### 7.3 想定コスト(月)
| 項目 | 想定 |
|------|------|
| Cloud Run | 無料枠内(数十件/月) |
| Cloud Tasks | 無料枠内 |
| GCS | 無料枠内(Lifecycle で 7 日削除) |
| Vertex AI Gemini 2.5 | **課金対象**。60 分音声 1 件あたり数十円〜の見込み |
| Secret Manager | 6 シークレット以内なら無料枠内 |

---

## 8. リスクと対策

| # | リスク | 対策 |
|---|--------|------|
| R1 | 処理が 30 分を超えて Cloud Tasks の HTTP dispatch deadline に抵触する | 初期前提では 30 分以内に収める。超過頻発時は Cloud Run Jobs へ移行、または Cloud Run から別ジョブを起動して即 200 を返す方式へ変更 |
| R2 | Cloud Tasks リトライで重複コミットが発生 | `row_id` を冪等キーとし、Cloud Run 起動時に `status=done` の行は即 200 を返してスキップ |
| R3 | Form 添付の Drive ファイルがサイズ制限に抵触 | Form の最大ファイルサイズを 100MB 程度に制限(60 分の opus/m4a 想定で十分) |
| R4 | Vertex AI のクォータ超過 | リトライ時の指数バックオフで吸収。継続超過時は `max-instances` を絞る |
| R5 | GitHub の同時 push 競合 | `max-instances=10` 程度では実害低。発生時は `git pull --rebase` を publisher に追加 |
| R6 | Apps Script 実行ユーザーの権限不足で Cloud Tasks に登録できない | 実行ユーザーに `roles/cloudtasks.enqueuer` を付与し、Apps Script の OAuth スコープに Cloud Platform を追加する |
| R7 | 失敗時に Sheet を更新しないため、未処理と失敗の区別が曖昧になる | Apps Script 監視トリガーが `enqueued_at` から 120 分超の `queued` 行を `failed` に自動確定する |
| R8 | 音声の文字起こし品質が要約品質に影響する | transcript note を必ず保存し、必要なら人間が文字起こしを確認・修正できるようにする |
| R9 | `jw-agent` と `jw-summarize-cloud` の出力仕様がずれる | frontmatter、保存先、タイトル決定ルールを契約として文書化し、変更時は両リポジトリで同時に確認する |

---

## 9. 実装方針

`jw-summarize-cloud` 側では、現行 `jw_summarize` の Web API / データモデルを正とせず、本設計に合わせて置換または大きく変更してよい。ただし、既存の有用な部品は移行して流用する。

`jw-agent` 側では、エージェントがスキルやコマンドからノート作成を実行しやすいことを優先する。Cloud Run のためだけの依存、GCP デプロイ設定、Apps Script の正本を `jw-agent` に残さない。両リポジトリ間で合わせるべきものは、ソース構成ではなく次の契約である。

- 入力種別: `url` / `text` / `audio`
- 出力: summary note と transcript note
- Obsidian 保存先: `OBSIDIAN_SUMMARY_DIR`, `OBSIDIAN_TRANSCRIPT_DIR`
- タイトル決定ルール: §4.6
- GitHub commit 先: `GITHUB_REPOSITORY`, `GITHUB_BRANCH`
- transcript note は音声入力でも必ず生成する

| 領域 | 方針 |
|------|------|
| Web API | Cloud Tasks 用 `/process` を `{ row_id, sheet_id }` 契約で実装する |
| Sheets client | `row_id` で対象行を取得し、成功時のみ `done` / `github_url` / `finished_at` を更新する |
| 入力モデル | `url` / `text` / `audio` を正規の入力種別として扱う |
| 音声処理 | 音声を Gemini で文字起こしし、文字起こしテキストを transcript note と要約入力の両方に使う |
| 要約実行 | URL 字幕、フォーム本文、音声文字起こしをすべて transcript text に正規化してから要約する |
| タイトル | §4.6 の決定論的ルールを実装し、LLM タイトル生成は行わない |
| GitHub publisher | `jw-agent` から移行した実装を流用可能。ただし同時更新競合が起きる場合はリトライを追加する |
| 依存関係 | `google-cloud-tasks`, `google-cloud-storage`, `google-api-python-client`(Sheets) を追加する |
| 環境変数 | §6 の変数を `jw-summarize-cloud` の `.env.example` に追記する |

---

## 10. 受け入れ基準(Definition of Done)

- [ ] Form 送信後、最大 5 分以内に Cloud Run で処理が開始される(audio 以外)
- [ ] 60 分音声を投入し、30 分以内に GitHub commit まで完了する
- [ ] 同時 5 件投入時、Cloud Tasks/Cloud Run が並列に処理し、すべて完了する
- [ ] 失敗ケースで Cloud Tasks が最大 3 回まで試行し、成功しない行は Apps Script 監視トリガーにより `failed` に自動更新される
- [ ] 音声入力でも summary note と transcript note が同一 commit で生成される
- [ ] タイトルがフォーム入力で上書きされる / 空欄時は §4.6 のフォールバック通りに決まる
- [ ] LLM はタイトル生成を行わない(コードパスごと撤去)
- [ ] `OBSIDIAN_SUMMARY_DIR` 配下にコミットされる
- [ ] `jw-agent` からのエージェント実行経路でも同じ出力契約で summary note / transcript note を生成できる
- [ ] `jw-agent` への通常変更では Cloud Run の本番デプロイが発火しない
- [ ] 月額コストが Vertex AI 利用分のみで Cloud Run 周辺は無料枠に収まる

---

## 11. 未決事項 / 将来検討

- F1: NotebookLM ポッドキャスト生成を Cloud Run Jobs で別フロー化するか
- F2: タグから Obsidian の保存サブディレクトリを自動振り分けするか
- F3: Form の代替として Slack スラッシュコマンド経由の投入を追加するか
- F4: 音声の話者分離(Gemini 単体で十分かの評価)
- F5: GCP プロジェクトを専用プロジェクトに分離するタイミング(D8 の見直し)
- F6: コード重複が問題になった時点で `jw-summarize-core` を作り、字幕取得・要約・ノート生成の純粋ロジックだけを共有するか
