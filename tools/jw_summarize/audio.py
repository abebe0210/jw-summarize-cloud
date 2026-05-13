from __future__ import annotations

import mimetypes
import posixpath

from .config import Settings
from .exceptions import ConfigError, ProcessingError


TRANSCRIPTION_PROMPT = """この音声を日本語でできるだけ正確に文字起こししてください。

要件:
- 要約せず、聞き取れる発話内容を順番どおりに書く
- 長い無音や音楽の説明は必要最小限にする
- 不明瞭な箇所は [不明瞭] と書く
"""


def transcribe_gcs_audio(
    gcs_uri: str,
    settings: Settings,
    *,
    mime_type: str | None = None,
) -> str:
    if not settings.vertex_project_id:
        raise ConfigError(
            "VERTEX_PROJECT_ID, GOOGLE_CLOUD_PROJECT, or PROJECT_ID must be set."
        )

    resolved_mime_type = mime_type or guess_audio_mime_type(gcs_uri)
    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel, Part
    except ImportError as exc:
        raise ConfigError("google-cloud-aiplatform is required for audio transcription.") from exc

    vertexai.init(project=settings.vertex_project_id, location=settings.vertex_location)
    model = GenerativeModel(settings.vertex_heavy_model)
    response = model.generate_content(
        [TRANSCRIPTION_PROMPT, Part.from_uri(gcs_uri, mime_type=resolved_mime_type)]
    )
    text = _extract_vertex_text(response).strip()
    if not text:
        raise ProcessingError("The transcription model returned no text.")
    return text


def guess_audio_mime_type(gcs_uri: str) -> str:
    mime_type, _ = mimetypes.guess_type(posixpath.basename(gcs_uri))
    if mime_type in {"audio/mpeg", "audio/mp4", "audio/wav", "audio/x-wav"}:
        return "audio/wav" if mime_type == "audio/x-wav" else mime_type
    if gcs_uri.lower().endswith(".m4a"):
        return "audio/mp4"
    return "audio/mpeg"


def _extract_vertex_text(response: object) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    candidates = getattr(response, "candidates", None)
    if not candidates:
        return str(response)
    parts: list[str] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                parts.append(str(part_text))
    return "\n".join(parts)
