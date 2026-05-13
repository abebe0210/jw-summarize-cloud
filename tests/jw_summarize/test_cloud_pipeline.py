from __future__ import annotations

import unittest

from tools.jw_summarize.cloud_pipeline import (
    CloudPipelineService,
    CloudProcessRequest,
    is_cloud_process_payload,
)
from tools.jw_summarize.config import Settings
from tools.jw_summarize.models import ProcessingRequest, ProcessingResult, PublishResult
from tools.jw_summarize.sheets import ManagementRow
from tools.jw_summarize.webapp import create_app


def fake_summary_generator(
    text: str,
    settings: Settings,
    provider: str | None,
    profile: str | None,
) -> str:
    del settings, provider, profile
    return f"## Summary\n- Characters: {len(text)}"


class MemoryPublisher:
    def __init__(self):
        self.requests: list[ProcessingRequest] = []
        self.note_contents: list[str] = []

    def publish(self, notes, request: ProcessingRequest, title: str) -> PublishResult:
        del title
        self.requests.append(request)
        self.note_contents = [note.content for note in notes]
        return PublishResult(
            commit_sha="abc123",
            commit_url="https://github.com/owner/repo/commit/abc123",
        )


class FakeSheetsClient:
    def __init__(self, row: ManagementRow):
        self.row = row
        self.success_updates: list[dict[str, str | int | None]] = []

    def get_row(self, spreadsheet_id: str, row_id: str) -> ManagementRow:
        self.last_get = {"spreadsheet_id": spreadsheet_id, "row_id": row_id}
        return self.row

    def update_success(
        self,
        spreadsheet_id: str,
        row_number: int,
        *,
        github_url: str | None,
        finished_at: str,
    ) -> None:
        self.success_updates.append(
            {
                "spreadsheet_id": spreadsheet_id,
                "row_number": row_number,
                "github_url": github_url,
                "finished_at": finished_at,
            }
        )


class StaticCloudService:
    def process(self, request: CloudProcessRequest) -> ProcessingResult:
        return ProcessingResult(
            request_id=request.row_id,
            stable_id="stable",
            title="Done",
            summary_note_path="summary.md",
            transcript_note_path="transcript.md",
            commit_sha="abc123",
            commit_url="https://example.com/commit/abc123",
            updated_at="2026-05-04T00:00:00+09:00",
        )


class CloudPipelineTests(unittest.TestCase):
    def test_processes_text_row_and_updates_sheet_only_on_success(self) -> None:
        row = ManagementRow(
            row_number=2,
            values={
                "row_id": "row-1",
                "status": "queued",
                "入力種別": "text",
                "本文": "これは本文です。",
                "タイトル": "入力タイトル",
                "タグ": "jw, meeting",
            },
        )
        sheets = FakeSheetsClient(row)
        publisher = MemoryPublisher()
        service = CloudPipelineService(
            Settings.from_env(),
            sheets_client=sheets,  # type: ignore[arg-type]
            publisher=publisher,
            summary_generator=fake_summary_generator,
        )

        result = service.process(CloudProcessRequest(row_id="row-1", sheet_id="sheet-1"))

        self.assertEqual(result.commit_url, "https://github.com/owner/repo/commit/abc123")
        self.assertEqual(len(sheets.success_updates), 1)
        self.assertEqual(sheets.success_updates[0]["row_number"], 2)
        self.assertEqual(publisher.requests[0].source_type, "text")
        self.assertEqual(publisher.requests[0].metadata["tags"], ["jw", "meeting"])
        self.assertIn("tags:", publisher.note_contents[0])

    def test_processes_audio_row_with_transcription_text(self) -> None:
        row = ManagementRow(
            row_number=3,
            values={
                "row_id": "row-audio",
                "status": "queued",
                "入力種別": "audio",
                "音声ファイル": "audio.m4a",
                "gcs_uri": "gs://bucket/incoming/audio.m4a",
            },
        )
        publisher = MemoryPublisher()
        service = CloudPipelineService(
            Settings.from_env(),
            sheets_client=FakeSheetsClient(row),  # type: ignore[arg-type]
            publisher=publisher,
            summary_generator=fake_summary_generator,
            audio_transcriber=lambda uri, settings: f"transcript from {uri}",
        )

        result = service.process(CloudProcessRequest(row_id="row-audio", sheet_id="sheet-1"))

        self.assertEqual(result.title, "audio")
        self.assertEqual(publisher.requests[0].raw_text, "transcript from gs://bucket/incoming/audio.m4a")
        self.assertEqual(publisher.requests[0].metadata["gcs_uri"], "gs://bucket/incoming/audio.m4a")

    def test_done_row_is_idempotent_and_skips_publish(self) -> None:
        row = ManagementRow(
            row_number=4,
            values={
                "row_id": "row-done",
                "status": "done",
                "github_url": "https://example.com/done",
            },
        )
        sheets = FakeSheetsClient(row)
        publisher = MemoryPublisher()
        service = CloudPipelineService(
            Settings.from_env(),
            sheets_client=sheets,  # type: ignore[arg-type]
            publisher=publisher,
            summary_generator=fake_summary_generator,
        )

        result = service.process(CloudProcessRequest(row_id="row-done", sheet_id="sheet-1"))

        self.assertEqual(result.commit_url, "https://example.com/done")
        self.assertEqual(publisher.requests, [])
        self.assertEqual(sheets.success_updates, [])

    def test_identifies_cloud_process_payload(self) -> None:
        self.assertTrue(is_cloud_process_payload({"row_id": "row-1", "sheet_id": "s"}))
        self.assertFalse(is_cloud_process_payload({"row_id": "row-1", "source_type": "text"}))


class CloudWebAppTests(unittest.TestCase):
    def test_process_endpoint_routes_row_payload_to_cloud_service(self) -> None:
        app = create_app(
            settings=Settings.from_env(),
            cloud_service_factory=lambda _: StaticCloudService(),  # type: ignore[return-value]
        )
        client = app.test_client()

        response = client.post("/process", json={"row_id": "row-1", "sheet_id": "sheet-1"})

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["status"], "done")
        self.assertEqual(body["request_id"], "row-1")


if __name__ == "__main__":
    unittest.main()
