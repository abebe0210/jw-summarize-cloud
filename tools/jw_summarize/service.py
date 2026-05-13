from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from tools.jw_subtitles import SubtitleExtractionError, fetch_subtitle_text_from_page_url

from .config import Settings
from .exceptions import ProcessingError
from .models import ProcessingRequest, ProcessingResult, utc_now_iso
from .obsidian import render_notes
from .publisher import Publisher
from .summarizer import summarize_text
from .title import extract_title


SummaryGenerator = Callable[[str, Settings, str | None, str | None], str]


def resolve_text(request: ProcessingRequest) -> ProcessingRequest:
    """If *source_type* is ``"url"`` and *raw_text* looks like a placeholder,
    fetch the actual subtitle text from JW.org via ``jw_subtitles``.

    Returns a new ``ProcessingRequest`` with *raw_text* populated.
    """
    if request.source_type != "url" or not request.source_url:
        return request

    try:
        subtitle_text = fetch_subtitle_text_from_page_url(request.source_url)
    except SubtitleExtractionError as exc:
        raise ProcessingError(
            f"Failed to extract subtitles from {request.source_url}: {exc}"
        ) from exc

    return replace(request, raw_text=subtitle_text)


class SummarizationService:
    def __init__(
        self,
        settings: Settings,
        publisher: Publisher,
        summary_generator: SummaryGenerator | None = None,
    ):
        self._settings = settings
        self._publisher = publisher
        self._summary_generator = summary_generator or summarize_text

    def process(self, request: ProcessingRequest) -> ProcessingResult:
        request = resolve_text(request)

        title = extract_title(request.raw_text, request.title_override)
        summary = self._summary_generator(
            request.raw_text, self._settings, request.provider, request.profile
        )
        summary_note, transcript_note = render_notes(
            request=request,
            title=title,
            summary_markdown=summary,
            settings=self._settings,
        )
        publish_result = self._publisher.publish(
            [summary_note, transcript_note], request=request, title=title
        )
        return ProcessingResult(
            request_id=request.resolved_request_id,
            stable_id=request.stable_id,
            title=title,
            summary_note_path=summary_note.path,
            transcript_note_path=transcript_note.path,
            commit_sha=publish_result.commit_sha,
            commit_url=publish_result.commit_url,
            updated_at=utc_now_iso(),
        )
