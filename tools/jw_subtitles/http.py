"""Thin HTTP helper — shared across tools."""

from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_TIMEOUT_SECONDS = 20


class HttpFetchError(RuntimeError):
    """Raised when an HTTP request fails."""


def fetch_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Fetch *url* and return the response body as text.

    Raises ``HttpFetchError`` on network or HTTP errors.
    """
    request = Request(url, headers=headers or {})
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise HttpFetchError(
            f"HTTP error {exc.code} while requesting {url}."
        ) from exc
    except URLError as exc:
        raise HttpFetchError(
            f"Network error while requesting {url}: {exc.reason}"
        ) from exc
