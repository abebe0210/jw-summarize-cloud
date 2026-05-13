from __future__ import annotations

from typing import Protocol, Sequence

from .models import ProcessingRequest, PublishResult, RenderedNote


class Publisher(Protocol):
    def publish(
        self,
        notes: Sequence[RenderedNote],
        request: ProcessingRequest,
        title: str,
    ) -> PublishResult: ...
