from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from .models import ProcessingRequest, PublishResult, RenderedNote


class LocalPublisher:
    def __init__(self, output_dir: str | Path):
        self._output_dir = Path(output_dir)

    def publish(
        self,
        notes: Sequence[RenderedNote],
        request: ProcessingRequest,
        title: str,
    ) -> PublishResult:
        for note in notes:
            destination = self._output_dir / Path(note.path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(note.content, encoding="utf-8")

        metadata_path = self._output_dir / "metadata" / f"{request.stable_id}.json"
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(
                {
                    "request_id": request.resolved_request_id,
                    "stable_id": request.stable_id,
                    "title": title,
                    "source_type": request.source_type,
                    "source_url": request.source_url,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return PublishResult(commit_sha=None, commit_url=None)
