from __future__ import annotations

import unittest
from unittest.mock import patch

from tools.jw_summarize.config import Settings
from tools.jw_summarize.models import ProcessingRequest, PublishResult, RenderedNote
from tools.jw_summarize.webapp import create_app


def fake_summary_generator(
    text: str,
    settings: Settings,
    provider: str | None,
    profile: str | None,
) -> str:
    del text, settings, provider, profile
    return "## Summary\n- ok"


class MemoryPublisher:
    def __init__(self):
        self.notes: list[RenderedNote] = []

    def publish(self, notes, request: ProcessingRequest, title: str) -> PublishResult:
        del request, title
        self.notes = list(notes)
        return PublishResult(
            commit_sha="abc123",
            commit_url="https://example.com/commit/abc123",
        )


class WebAppTests(unittest.TestCase):
    def test_process_endpoint_requires_secret_when_configured(self) -> None:
        base_settings = Settings.from_env()
        settings = Settings(**{**base_settings.__dict__, "webhook_shared_secret": "secret-value"})
        app = create_app(
            settings=settings,
            publisher_factory=lambda _: MemoryPublisher(),
            summary_generator=fake_summary_generator,
        )
        client = app.test_client()
        response = client.post(
            "/process",
            json={"source_type": "text", "raw_text": "body"},
        )
        self.assertEqual(response.status_code, 401)

    @patch("tools.jw_summarize.service.fetch_subtitle_text_from_page_url")
    def test_process_endpoint_returns_success_json(self, mock_fetch) -> None:
        mock_fetch.return_value = "Title: Demo Talk\nBody"
        publisher = MemoryPublisher()
        app = create_app(
            settings=Settings.from_env(),
            publisher_factory=lambda _: publisher,
            summary_generator=fake_summary_generator,
        )
        client = app.test_client()
        response = client.post(
            "/process",
            json={
                "source_type": "text",
                "raw_text": "Title: Demo Talk\nBody",
                "request_id": "req-42",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["request_id"], "req-42")
        self.assertEqual(body["commit_sha"], "abc123")
        self.assertEqual(len(publisher.notes), 2)


if __name__ == "__main__":
    unittest.main()
