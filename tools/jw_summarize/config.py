from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    llm_provider: str = "vertexai"
    llm_profile: str = "heavy"
    vertex_project_id: str | None = None
    vertex_location: str = "asia-northeast1"
    vertex_heavy_model: str = "gemini-2.5-pro"
    vertex_light_model: str = "gemini-2.5-flash"
    openai_api_key: str | None = None
    openai_heavy_model: str = "gpt-4.1"
    openai_light_model: str = "gpt-4o-mini"
    github_token: str | None = None
    github_repository: str | None = None
    github_branch: str = "main"
    github_api_base: str = "https://api.github.com"
    obsidian_summary_dir: str = "01_Talks"
    obsidian_transcript_dir: str = "05_Transcription"
    local_output_dir: str = "local-output"
    webhook_shared_secret: str | None = None
    google_oidc_audience: str | None = None
    gcp_project_id: str | None = None
    gcs_audio_bucket: str | None = None
    sheets_management_id: str | None = None
    sheets_worksheet_name: str | None = None
    tasks_queue_name: str = "jw-summarize-process"
    tasks_location: str = "asia-northeast1"
    cloud_run_audience: str | None = None
    form_input_type_column: str = "入力種別"
    form_url_column: str = "URL"
    form_text_column: str = "本文"
    form_audio_column: str = "音声ファイル"
    form_title_column: str = "タイトル"
    form_tags_column: str = "タグ"
    sheet_row_id_column: str = "row_id"
    sheet_status_column: str = "status"
    sheet_gcs_uri_column: str = "gcs_uri"
    sheet_github_url_column: str = "github_url"
    sheet_error_column: str = "error"
    sheet_enqueued_at_column: str = "enqueued_at"
    sheet_finished_at_column: str = "finished_at"
    http_timeout_seconds: int = 30

    @classmethod
    def from_env(cls) -> Settings:
        timeout_raw = os.getenv("HTTP_TIMEOUT_SECONDS", "30").strip() or "30"
        return cls(
            llm_provider=os.getenv("LLM_PROVIDER", "vertexai").strip() or "vertexai",
            llm_profile=os.getenv("LLM_PROFILE", "heavy").strip() or "heavy",
            vertex_project_id=(
                os.getenv("VERTEX_PROJECT_ID")
                or os.getenv("GOOGLE_CLOUD_PROJECT")
                or os.getenv("PROJECT_ID")
            ),
            vertex_location=os.getenv("VERTEX_LOCATION", "asia-northeast1").strip()
            or "asia-northeast1",
            vertex_heavy_model=os.getenv("VERTEX_HEAVY_MODEL", "gemini-2.5-pro").strip()
            or "gemini-2.5-pro",
            vertex_light_model=os.getenv(
                "VERTEX_LIGHT_MODEL", "gemini-2.5-flash"
            ).strip()
            or "gemini-2.5-flash",
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_heavy_model=os.getenv("OPENAI_HEAVY_MODEL", "gpt-4.1").strip()
            or "gpt-4.1",
            openai_light_model=os.getenv("OPENAI_LIGHT_MODEL", "gpt-4o-mini").strip()
            or "gpt-4o-mini",
            github_token=os.getenv("GITHUB_TOKEN"),
            github_repository=os.getenv("GITHUB_REPOSITORY"),
            github_branch=os.getenv("GITHUB_BRANCH", "main").strip() or "main",
            github_api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com")
            .strip()
            .rstrip("/"),
            obsidian_summary_dir=os.getenv("OBSIDIAN_SUMMARY_DIR", "01_Talks").strip()
            or "01_Talks",
            obsidian_transcript_dir=os.getenv(
                "OBSIDIAN_TRANSCRIPT_DIR", "05_Transcription"
            ).strip()
            or "05_Transcription",
            local_output_dir=os.getenv("LOCAL_OUTPUT_DIR", "local-output").strip()
            or "local-output",
            webhook_shared_secret=os.getenv("WEBHOOK_SHARED_SECRET"),
            google_oidc_audience=(
                os.getenv("GOOGLE_OIDC_AUDIENCE") or os.getenv("CLOUD_RUN_AUDIENCE")
            ),
            gcp_project_id=(
                os.getenv("GCP_PROJECT_ID")
                or os.getenv("GOOGLE_CLOUD_PROJECT")
                or os.getenv("PROJECT_ID")
            ),
            gcs_audio_bucket=os.getenv("GCS_AUDIO_BUCKET"),
            sheets_management_id=os.getenv("SHEETS_MANAGEMENT_ID"),
            sheets_worksheet_name=(
                os.getenv("SHEETS_WORKSHEET_NAME", "").strip() or None
            ),
            tasks_queue_name=os.getenv("TASKS_QUEUE_NAME", "jw-summarize-process").strip()
            or "jw-summarize-process",
            tasks_location=os.getenv("TASKS_LOCATION", "asia-northeast1").strip()
            or "asia-northeast1",
            cloud_run_audience=os.getenv("CLOUD_RUN_AUDIENCE"),
            form_input_type_column=os.getenv("FORM_INPUT_TYPE_COLUMN", "入力種別").strip()
            or "入力種別",
            form_url_column=os.getenv("FORM_URL_COLUMN", "URL").strip() or "URL",
            form_text_column=os.getenv("FORM_TEXT_COLUMN", "本文").strip() or "本文",
            form_audio_column=os.getenv("FORM_AUDIO_COLUMN", "音声ファイル").strip()
            or "音声ファイル",
            form_title_column=os.getenv("FORM_TITLE_COLUMN", "タイトル").strip()
            or "タイトル",
            form_tags_column=os.getenv("FORM_TAGS_COLUMN", "タグ").strip() or "タグ",
            sheet_row_id_column=os.getenv("SHEET_ROW_ID_COLUMN", "row_id").strip()
            or "row_id",
            sheet_status_column=os.getenv("SHEET_STATUS_COLUMN", "status").strip()
            or "status",
            sheet_gcs_uri_column=os.getenv("SHEET_GCS_URI_COLUMN", "gcs_uri").strip()
            or "gcs_uri",
            sheet_github_url_column=os.getenv(
                "SHEET_GITHUB_URL_COLUMN", "github_url"
            ).strip()
            or "github_url",
            sheet_error_column=os.getenv("SHEET_ERROR_COLUMN", "error").strip()
            or "error",
            sheet_enqueued_at_column=os.getenv(
                "SHEET_ENQUEUED_AT_COLUMN", "enqueued_at"
            ).strip()
            or "enqueued_at",
            sheet_finished_at_column=os.getenv(
                "SHEET_FINISHED_AT_COLUMN", "finished_at"
            ).strip()
            or "finished_at",
            http_timeout_seconds=max(1, int(timeout_raw)),
        )

    @property
    def github_enabled(self) -> bool:
        return bool(self.github_token and self.github_repository)
