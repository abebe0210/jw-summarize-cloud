from __future__ import annotations

import posixpath

from .config import Settings
from .models import ProcessingRequest, RenderedNote
from .title import sanitize_filename


def render_notes(
    request: ProcessingRequest,
    title: str,
    summary_markdown: str,
    settings: Settings,
) -> tuple[RenderedNote, RenderedNote]:
    basename = _note_basename(title)
    summary_path = posixpath.join(settings.obsidian_summary_dir, f"{basename}.md")
    transcript_path = posixpath.join(
        settings.obsidian_transcript_dir, f"{basename}.md"
    )

    summary_link = _obsidian_link(summary_path)
    transcript_link = _obsidian_link(transcript_path)

    summary_content = _build_summary_content(
        request=request,
        title=title,
        summary_markdown=summary_markdown,
        transcript_link=transcript_link,
    )
    transcript_content = _build_transcript_content(
        request=request,
        title=title,
        summary_link=summary_link,
    )

    return (
        RenderedNote(path=summary_path, content=summary_content),
        RenderedNote(path=transcript_path, content=transcript_content),
    )


def _note_basename(title: str) -> str:
    return sanitize_filename(title)


def _obsidian_link(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.endswith(".md"):
        normalized = normalized[:-3]
    return normalized


def _build_summary_content(
    request: ProcessingRequest,
    title: str,
    summary_markdown: str,
    transcript_link: str,
) -> str:
    body = _normalize_summary_body(summary_markdown)
    lines = _frontmatter_lines(request)
    lines.extend(
        [
            f"# {title}",
            "",
            body,
            "",
            "## Metadata",
            f"- Source: `{request.source_type}`",
            f"- Request ID: `{request.resolved_request_id}`",
            f"- Stable ID: `{request.stable_id}`",
        ]
    )
    if request.metadata.get("gcs_uri"):
        lines.append(f"- GCS URI: `{request.metadata['gcs_uri']}`")
    if request.source_url:
        lines.append(f"- Source URL: {request.source_url}")
    if request.submitted_at:
        lines.append(f"- Submitted At: {request.submitted_at}")
    if request.supplemental_note:
        lines.extend(["", "## Supplemental Note", request.supplemental_note])
    lines.extend(["", "## Transcript", f"- [[{transcript_link}]]"])
    return "\n".join(lines).strip() + "\n"


def _build_transcript_content(
    request: ProcessingRequest,
    title: str,
    summary_link: str,
) -> str:
    lines = _frontmatter_lines(request)
    lines.extend(
        [
            f"# {title}",
            "",
            "## Metadata",
            f"- Source: `{request.source_type}`",
            f"- Request ID: `{request.resolved_request_id}`",
            f"- Stable ID: `{request.stable_id}`",
        ]
    )
    if request.metadata.get("gcs_uri"):
        lines.append(f"- GCS URI: `{request.metadata['gcs_uri']}`")
    if request.source_url:
        lines.append(f"- Source URL: {request.source_url}")
    if request.submitted_at:
        lines.append(f"- Submitted At: {request.submitted_at}")
    lines.extend(
        ["", "## Summary", f"- [[{summary_link}]]", "", "## Transcript", request.raw_text]
    )
    return "\n".join(lines).strip() + "\n"


def _normalize_summary_body(summary_markdown: str) -> str:
    text = summary_markdown.strip()
    if not text:
        return "## Summary\n- The summary model returned no content."

    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("#"):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
        text = "\n".join(lines).strip()

    if not text.startswith("##") and not text.startswith("-"):
        text = f"## Summary\n{text}"
    return text


def _frontmatter_lines(request: ProcessingRequest) -> list[str]:
    tags = _normalize_tags(request.metadata.get("tags"))
    if not tags:
        return []
    return ["---", "tags:"] + [f"  - {tag}" for tag in tags] + ["---", ""]


def _normalize_tags(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_tags = value.split(",")
    elif isinstance(value, (list, tuple)):
        raw_tags = [str(item) for item in value]
    else:
        raw_tags = [str(value)]
    tags = []
    for raw_tag in raw_tags:
        tag = raw_tag.strip().lstrip("#")
        if tag:
            tags.append(tag)
    return tags
