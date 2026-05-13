from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Callable

import requests

from tools.jw_subtitles import SubtitleExtractionError, fetch_subtitle_text_from_page_url

from .audio import transcribe_gcs_audio
from .config import Settings
from .exceptions import ConfigError, ProcessingError, ValidationError
from .github_publisher import GitHubPublisher
from .models import ProcessingRequest, ProcessingResult
from .publisher import Publisher
from .sheets import ManagementRow, SheetsClient
from .service import SummaryGenerator, SummarizationService
from .title import extract_title


JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class CloudProcessRequest:
    row_id: str
    sheet_id: str | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> CloudProcessRequest:
        if not isinstance(payload, dict):
            raise ValidationError("JSON body must be an object.")
        row_id = _clean(payload.get("row_id"))
        if not row_id:
            raise ValidationError("row_id is required.")
        return cls(row_id=row_id, sheet_id=_clean(payload.get("sheet_id")))


class CloudPipelineService:
    def __init__(
        self,
        settings: Settings,
        *,
        sheets_client: SheetsClient | None = None,
        publisher: Publisher | None = None,
        summary_generator: SummaryGenerator | None = None,
        audio_transcriber: Callable[[str, Settings], str] | None = None,
        page_title_resolver: Callable[[str, Settings], str | None] | None = None,
    ):
        self._settings = settings
        self._sheets = sheets_client or SheetsClient(settings)
        self._publisher = publisher
        self._summary_generator = summary_generator
        self._audio_transcriber = audio_transcriber or transcribe_gcs_audio
        self._page_title_resolver = page_title_resolver or fetch_page_title

    def process(self, request: CloudProcessRequest) -> ProcessingResult:
        sheet_id = request.sheet_id or self._settings.sheets_management_id
        if not sheet_id:
            raise ConfigError("sheet_id or SHEETS_MANAGEMENT_ID is required.")

        row = self._sheets.get_row(sheet_id, request.row_id)
        if row.value(self._settings.sheet_status_column) == "done":
            return _done_result_from_row(request.row_id, row, self._settings)

        processing_request = self._build_processing_request(row)
        result = SummarizationService(
            settings=self._settings,
            publisher=self._publisher or GitHubPublisher(self._settings),
            summary_generator=self._summary_generator,
        ).process(processing_request)
        self._sheets.update_success(
            sheet_id,
            row.row_number,
            github_url=result.commit_url,
            finished_at=now_jst_iso(),
        )
        return result

    def _build_processing_request(self, row: ManagementRow) -> ProcessingRequest:
        source_type = row.source_type(self._settings)
        if source_type == "url":
            source_url = _required(row, self._settings.form_url_column)
            transcript = _fetch_subtitles(source_url)
            title = self._resolve_title(row, source_type, transcript, source_url=source_url)
        elif source_type == "text":
            transcript = _required(row, self._settings.form_text_column)
            title = self._resolve_title(row, source_type, transcript)
            source_url = None
        elif source_type == "audio":
            gcs_uri = _required(row, self._settings.sheet_gcs_uri_column)
            transcript = self._audio_transcriber(gcs_uri, self._settings)
            title = self._resolve_title(row, source_type, transcript, gcs_uri=gcs_uri)
            source_url = None
        else:  # pragma: no cover - guarded by ManagementRow.source_type
            raise ProcessingError(f"Unsupported source type: {source_type}")

        metadata: dict[str, Any] = {"tags": row.tags(self._settings)}
        if source_type == "audio":
            metadata["gcs_uri"] = row.value(self._settings.sheet_gcs_uri_column)

        return ProcessingRequest(
            source_type=source_type,  # type: ignore[arg-type]
            raw_text=transcript,
            source_url=source_url,
            title_override=title,
            submitted_at=row.value("Timestamp") or row.value("タイムスタンプ"),
            request_id=_required(row, self._settings.sheet_row_id_column),
            sheet_row_id=row.value(self._settings.sheet_row_id_column),
            metadata=metadata,
        )

    def _resolve_title(
        self,
        row: ManagementRow,
        source_type: str,
        transcript: str,
        *,
        source_url: str | None = None,
        gcs_uri: str | None = None,
    ) -> str:
        title_override = row.value(self._settings.form_title_column)
        if title_override:
            return extract_title("", title_override)
        if source_type == "url" and source_url:
            page_title = self._page_title_resolver(source_url, self._settings)
            return extract_title("", page_title) if page_title else extract_title(transcript)
        if source_type == "text":
            raise ValidationError("title is required when source_type is text.")
        if source_type == "audio" and gcs_uri:
            return extract_title("", _basename_without_extension(gcs_uri))
        return extract_title(transcript)


def is_cloud_process_payload(payload: object) -> bool:
    return isinstance(payload, dict) and "row_id" in payload and "source_type" not in payload


def fetch_page_title(url: str, settings: Settings) -> str | None:
    response = requests.get(url, timeout=settings.http_timeout_seconds)
    response.raise_for_status()
    parser = _TitleParser()
    parser.feed(response.text)
    return _clean_page_title(parser.title)


def now_jst_iso() -> str:
    return datetime.now(JST).replace(microsecond=0).isoformat()


def _fetch_subtitles(source_url: str) -> str:
    try:
        return fetch_subtitle_text_from_page_url(source_url)
    except SubtitleExtractionError as exc:
        raise ProcessingError(f"Failed to extract subtitles from {source_url}: {exc}") from exc


def _done_result_from_row(
    row_id: str, row: ManagementRow, settings: Settings
) -> ProcessingResult:
    return ProcessingResult(
        request_id=row_id,
        stable_id=row_id,
        title=row.value(settings.form_title_column) or "Already Processed",
        summary_note_path="",
        transcript_note_path="",
        commit_sha=None,
        commit_url=row.value(settings.sheet_github_url_column),
        updated_at=row.value(settings.sheet_finished_at_column) or now_jst_iso(),
    )


def _required(row: ManagementRow, column_name: str) -> str:
    value = row.value(column_name)
    if not value:
        raise ProcessingError(f"Missing required spreadsheet value: {column_name}")
    return value


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _basename_without_extension(gcs_uri: str) -> str:
    basename = posixpath.basename(gcs_uri)
    if "." in basename:
        basename = basename.rsplit(".", 1)[0]
    return basename or "Untitled Audio"


def _clean_page_title(title: str | None) -> str | None:
    if not title:
        return None
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"\s*\|\s*JW\.ORG\s*$", "", title, flags=re.IGNORECASE).strip()
    return title or None


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self._parts: list[str] = []

    @property
    def title(self) -> str | None:
        return "".join(self._parts).strip() or None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._parts.append(data)
