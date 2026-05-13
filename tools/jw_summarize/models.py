from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from .exceptions import ValidationError

SourceType = Literal["url", "text", "audio"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


@dataclass(frozen=True)
class ProcessingRequest:
    source_type: SourceType
    raw_text: str
    source_url: str | None = None
    title_override: str | None = None
    supplemental_note: str | None = None
    submitted_at: str | None = None
    request_id: str | None = None
    sheet_row_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    provider: str | None = None
    profile: str | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> ProcessingRequest:
        if not isinstance(payload, dict):
            raise ValidationError("JSON body must be an object.")

        source_type = _clean_optional_string(payload.get("source_type"))
        if source_type not in {"url", "text", "audio"}:
            raise ValidationError("source_type must be 'url', 'text', or 'audio'.")

        raw_text = _clean_optional_string(payload.get("raw_text"))
        if not raw_text:
            raise ValidationError("raw_text is required.")

        source_url = _clean_optional_string(payload.get("source_url"))
        if source_type == "url" and not source_url:
            raise ValidationError("source_url is required when source_type is 'url'.")

        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValidationError("metadata must be an object when provided.")

        provider = _clean_optional_string(payload.get("provider"))
        if provider and provider not in {"vertexai", "openai"}:
            raise ValidationError("provider must be either 'vertexai' or 'openai'.")

        profile = _clean_optional_string(payload.get("profile"))
        if profile and profile not in {"heavy", "light"}:
            raise ValidationError("profile must be either 'heavy' or 'light'.")

        request_id = _clean_optional_string(payload.get("request_id")) or (
            f"generated-{uuid.uuid4().hex[:12]}"
        )

        return cls(
            source_type=source_type,
            raw_text=raw_text,
            source_url=source_url,
            title_override=_clean_optional_string(payload.get("title_override")),
            supplemental_note=_clean_optional_string(payload.get("supplemental_note")),
            submitted_at=_clean_optional_string(payload.get("submitted_at")),
            request_id=request_id,
            sheet_row_id=_clean_optional_string(payload.get("sheet_row_id")),
            metadata=dict(metadata),
            provider=provider,
            profile=profile,
        )

    @property
    def resolved_request_id(self) -> str:
        return self.request_id or "generated-missing"

    @property
    def stable_id(self) -> str:
        if self.source_type == "url" and self.source_url:
            basis = f"url:{self.source_url.strip()}"
        elif self.source_type == "audio" and self.request_id:
            basis = f"audio:{self.request_id}"
        elif self.request_id:
            basis = f"request:{self.request_id}"
        else:
            basis = f"text:{_normalize_whitespace(self.raw_text)[:4000]}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:10]

    @property
    def source_label(self) -> str:
        if self.source_type == "url" and self.source_url:
            return self.source_url
        if self.source_type == "audio":
            return "audio-input"
        return "text-input"


@dataclass(frozen=True)
class RenderedNote:
    path: str
    content: str


@dataclass(frozen=True)
class PublishResult:
    commit_sha: str | None
    commit_url: str | None = None


@dataclass(frozen=True)
class ProcessingResult:
    request_id: str
    stable_id: str
    title: str
    summary_note_path: str
    transcript_note_path: str
    commit_sha: str | None
    commit_url: str | None
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "stable_id": self.stable_id,
            "title": self.title,
            "summary_note_path": self.summary_note_path,
            "transcript_note_path": self.transcript_note_path,
            "commit_sha": self.commit_sha,
            "commit_url": self.commit_url,
            "updated_at": self.updated_at,
        }
