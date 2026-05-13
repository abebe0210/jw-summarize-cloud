from __future__ import annotations

import re


INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')
WHITESPACE_RE = re.compile(r"\s+")
TIMESTAMP_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")


def extract_title(raw_text: str, title_override: str | None = None) -> str:
    if title_override and title_override.strip():
        return _finalize_title(title_override)

    for line in raw_text.splitlines():
        candidate = _extract_title_candidate(line)
        if candidate:
            return _finalize_title(candidate)
    return "Untitled Talk"


def sanitize_filename(title: str) -> str:
    cleaned = INVALID_FILENAME_CHARS.sub(" ", title).strip()
    cleaned = WHITESPACE_RE.sub(" ", cleaned).strip(" .")
    return cleaned or "Untitled Talk"


def _extract_title_candidate(line: str) -> str | None:
    text = line.strip()
    if not text:
        return None
    text = text.lstrip("#*- ").strip()
    if not text:
        return None
    if text.upper().startswith("WEBVTT"):
        return None
    if "-->" in text:
        return None
    if TIMESTAMP_RE.match(text):
        return None

    if ":" in text:
        prefix, suffix = text.split(":", 1)
        if 1 <= len(prefix.strip()) <= 20 and suffix.strip():
            text = suffix.strip()

    if len(text) < 4:
        return None
    return text


def _finalize_title(title: str) -> str:
    normalized = WHITESPACE_RE.sub(" ", title).strip()
    if len(normalized) > 90:
        normalized = normalized[:90].rstrip()
    return normalized or "Untitled Talk"
