from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tools.jw_summarize.config import Settings
from tools.jw_summarize.exceptions import ProcessingError
from tools.jw_summarize.local_publisher import LocalPublisher
from tools.jw_summarize.models import ProcessingRequest
from tools.jw_summarize.obsidian import render_notes
from tools.jw_summarize.service import SummarizationService, resolve_text
from tools.jw_summarize.title import extract_title


def fake_summary_generator(
    text: str,
    settings: Settings,
    provider: str | None,
    profile: str | None,
) -> str:
    del settings, provider, profile
    return f"## Summary\n- Characters: {len(text)}"


class ProcessingRequestTests(unittest.TestCase):
    def test_requires_url_for_url_source_type(self) -> None:
        with self.assertRaisesRegex(Exception, "source_url is required"):
            ProcessingRequest.from_mapping(
                {"source_type": "url", "raw_text": "text without url"}
            )

    def test_uses_request_id_for_text_stable_id(self) -> None:
        request = ProcessingRequest.from_mapping(
            {
                "source_type": "text",
                "raw_text": "body",
                "request_id": "abc123",
            }
        )
        self.assertEqual(request.stable_id, request.stable_id)
        self.assertEqual(request.resolved_request_id, "abc123")


class TitleTests(unittest.TestCase):
    def test_prefers_override(self) -> None:
        title = extract_title("Topic: ignored", title_override="Chosen Title")
        self.assertEqual(title, "Chosen Title")

    def test_extracts_suffix_after_colon(self) -> None:
        title = extract_title("Title: A Better Hope\nSecond line")
        self.assertEqual(title, "A Better Hope")


class ObsidianRenderTests(unittest.TestCase):
    def test_renders_summary_and_transcript_paths(self) -> None:
        settings = Settings.from_env()
        request = ProcessingRequest.from_mapping(
            {
                "source_type": "url",
                "source_url": "https://example.com/watch?v=1",
                "raw_text": "Title: Sample Talk",
                "request_id": "req-1",
            }
        )
        summary_note, transcript_note = render_notes(
            request=request,
            title="Sample Talk",
            summary_markdown="# Sample Talk\n\n## Summary\n- Point",
            settings=settings,
        )
        self.assertTrue(summary_note.path.startswith("01_Talks/"))
        self.assertTrue(transcript_note.path.startswith("05_Transcription/"))
        self.assertIn("[[05_Transcription/", summary_note.content)
        self.assertIn("[[01_Talks/", transcript_note.content)


class ResolveTextTests(unittest.TestCase):
    def test_text_source_type_passes_through(self) -> None:
        request = ProcessingRequest.from_mapping(
            {"source_type": "text", "raw_text": "original text", "request_id": "r1"}
        )
        result = resolve_text(request)
        self.assertEqual(result.raw_text, "original text")

    @patch("tools.jw_summarize.service.fetch_subtitle_text_from_page_url")
    def test_url_source_type_fetches_subtitles(self, mock_fetch) -> None:
        mock_fetch.return_value = "fetched subtitle text"
        request = ProcessingRequest.from_mapping(
            {
                "source_type": "url",
                "source_url": "https://www.jw.org/ja/#ja/mediaitems/pub-jwb-1_1_VIDEO",
                "raw_text": "placeholder",
                "request_id": "r2",
            }
        )
        result = resolve_text(request)
        self.assertEqual(result.raw_text, "fetched subtitle text")
        mock_fetch.assert_called_once_with("https://www.jw.org/ja/#ja/mediaitems/pub-jwb-1_1_VIDEO")

    @patch("tools.jw_summarize.service.fetch_subtitle_text_from_page_url")
    def test_url_source_type_wraps_extraction_error(self, mock_fetch) -> None:
        from tools.jw_subtitles import SubtitleExtractionError

        mock_fetch.side_effect = SubtitleExtractionError("bad url")
        request = ProcessingRequest.from_mapping(
            {
                "source_type": "url",
                "source_url": "https://www.jw.org/ja/#ja/mediaitems/pub-jwb-1_1_VIDEO",
                "raw_text": "placeholder",
                "request_id": "r3",
            }
        )
        with self.assertRaises(ProcessingError):
            resolve_text(request)


class ServiceTests(unittest.TestCase):
    @patch("tools.jw_summarize.service.fetch_subtitle_text_from_page_url")
    def test_service_writes_local_files(self, mock_fetch) -> None:
        mock_fetch.return_value = "Title: Local Talk\nBody line"
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = replace(Settings.from_env(), local_output_dir=temp_dir)
            publisher = LocalPublisher(temp_dir)
            service = SummarizationService(
                settings=settings,
                publisher=publisher,
                summary_generator=fake_summary_generator,
            )
            request = ProcessingRequest.from_mapping(
                {
                    "source_type": "text",
                    "raw_text": "Title: Local Talk\nBody line",
                    "request_id": "row-10",
                }
            )

            result = service.process(request)

            summary_path = Path(temp_dir) / result.summary_note_path
            transcript_path = Path(temp_dir) / result.transcript_note_path
            self.assertTrue(summary_path.exists())
            self.assertTrue(transcript_path.exists())
            self.assertIsNone(result.commit_sha)


if __name__ == "__main__":
    unittest.main()
