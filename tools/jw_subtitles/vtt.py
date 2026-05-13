"""WebVTT subtitle parsing — pure functions with no I/O."""

from __future__ import annotations

import html
import re

TAG_PATTERN = re.compile(r"<[^>]+>")


class VttParseError(RuntimeError):
    """Raised when a VTT document cannot be parsed into cue text."""


def extract_text_from_vtt(vtt_text: str) -> str:
    """Convert a WebVTT document into readable subtitle text.

    Raises ``VttParseError`` when the document contains no cue text.
    """
    blocks = re.split(r"\r?\n\r?\n+", vtt_text.strip())
    extracted: list[str] = []

    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if lines[0].upper().startswith("WEBVTT"):
            continue
        if lines[0].startswith("NOTE"):
            continue

        timing_index = _find_timing_index(lines)
        if timing_index == -1:
            continue

        cue_lines = lines[timing_index + 1 :]
        if not cue_lines:
            continue

        cue_text = " ".join(_clean_cue_text(line) for line in cue_lines).strip()
        if cue_text:
            extracted.append(cue_text)

    if not extracted:
        raise VttParseError("Subtitle file did not contain any cue text.")
    return "\n".join(extracted)


def _find_timing_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if "-->" in line:
            return index
    return -1


def _clean_cue_text(text: str) -> str:
    without_tags = TAG_PATTERN.sub("", text)
    unescaped = html.unescape(without_tags)
    normalized = re.sub(r"\s+", " ", unescaped)
    return normalized.strip()
