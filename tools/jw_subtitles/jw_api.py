"""JW.org URL parsing and media API integration."""

from __future__ import annotations

import json
import re
from urllib.parse import ParseResult, parse_qs, urlencode, urlparse

from .http import HttpFetchError, fetch_text
from .vtt import VttParseError, extract_text_from_vtt

API_URL = "https://b.jw-cdn.org/apis/pub-media/GETPUBMEDIALINKS"
DEFAULT_HEADERS = {
    "User-Agent": "jw-subtitles/1.0 (+https://www.jw.org/)",
    "Accept": "application/json, text/vtt;q=0.9, */*;q=0.8",
}
MEDIA_ID_PATTERN = re.compile(
    r"^(?P<prefix>pub)-(?P<pub>[a-z0-9-]+)_(?P<track>\d+)_VIDEO$",
    re.IGNORECASE,
)


class SubtitleExtractionError(RuntimeError):
    """Raised when subtitle extraction fails."""


def parse_jw_video_url(url: str) -> tuple[str, int]:
    """Extract the JW publication id and track number from a JW.org video URL."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SubtitleExtractionError("URL must start with http:// or https://.")
    if not parsed.netloc.endswith("jw.org"):
        raise SubtitleExtractionError("URL host must be jw.org.")

    media_id = _extract_media_id(parsed)
    match = MEDIA_ID_PATTERN.match(media_id)
    if not match:
        raise SubtitleExtractionError(
            "Could not parse JW.org media identifier from URL."
        )

    pub = match.group("pub").lower()
    track = int(match.group("track"))
    if track < 1:
        raise SubtitleExtractionError("Track number must be greater than zero.")
    return pub, track


def fetch_subtitle_url(pub: str, track: int, *, lang: str = "J") -> str:
    """Resolve a JW publication id and track to a subtitle URL.

    *lang* is the JW language code (default ``"J"`` for Japanese).
    """
    query = urlencode(
        {
            "output": "json",
            "pub": pub,
            "track": track,
            "fileformat": "MP4",
            "alllangs": 0,
            "langwritten": lang,
            "txtCMSLang": lang,
        }
    )
    headers = dict(DEFAULT_HEADERS)
    headers["Accept"] = "application/json"
    try:
        response_text = fetch_text(f"{API_URL}?{query}", headers=headers)
    except HttpFetchError as exc:
        raise SubtitleExtractionError(str(exc)) from exc

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise SubtitleExtractionError("JW media API returned invalid JSON.") from exc

    files = payload.get("files", {}).get(lang, {}).get("MP4", [])
    for entry in files:
        subtitle_url = entry.get("subtitles", {}).get("url")
        if subtitle_url:
            return subtitle_url

    raise SubtitleExtractionError(
        f"No subtitles were published for pub='{pub}' track={track}."
    )


def fetch_subtitle_text_from_page_url(url: str, *, lang: str = "J") -> str:
    """Resolve a JW.org video URL to subtitles and return the extracted text.

    *lang* is the JW language code (default ``"J"`` for Japanese).
    """
    pub, track = parse_jw_video_url(url)
    subtitle_url = fetch_subtitle_url(pub, track, lang=lang)

    headers = dict(DEFAULT_HEADERS)
    headers["Accept"] = "text/vtt, */*;q=0.8"
    try:
        vtt_text = fetch_text(subtitle_url, headers=headers)
    except HttpFetchError as exc:
        raise SubtitleExtractionError(str(exc)) from exc

    try:
        return extract_text_from_vtt(vtt_text)
    except VttParseError as exc:
        raise SubtitleExtractionError(str(exc)) from exc


def _extract_media_id(parsed_url: ParseResult) -> str:
    fragment = parsed_url.fragment or ""
    if fragment:
        media_id = fragment.rsplit("/", 1)[-1]
        if media_id:
            return media_id

    query_values = parse_qs(parsed_url.query)
    media_id = query_values.get("lank") or query_values.get("media")
    if media_id:
        return media_id[0]

    raise SubtitleExtractionError(
        "URL does not contain a JW.org video media identifier in the fragment."
    )
