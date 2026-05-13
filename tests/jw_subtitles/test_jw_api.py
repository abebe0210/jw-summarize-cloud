from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tools.jw_subtitles.jw_api import (
    SubtitleExtractionError,
    fetch_subtitle_url,
    parse_jw_video_url,
)


class FakeResponse:
    def __init__(self, body: str, charset: str = "utf-8") -> None:
        self._body = body.encode(charset)
        self._charset = charset
        self.headers = self

    def get_content_charset(self) -> str:
        return self._charset

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class ParseJwVideoUrlTests(unittest.TestCase):
    def test_parses_supported_url(self) -> None:
        pub, track = parse_jw_video_url(
            "https://www.jw.org/ja/%E3%83%A9%E3%82%A4%E3%83%96%E3%83%A9%E3%83%AA%E3%83%BC/"
            "%E3%83%93%E3%83%87%E3%82%AA/#ja/mediaitems/StudioFeatured/pub-jwb-135_1_VIDEO"
        )

        self.assertEqual(pub, "jwb-135")
        self.assertEqual(track, 1)

    def test_rejects_non_jw_host(self) -> None:
        with self.assertRaises(SubtitleExtractionError):
            parse_jw_video_url("https://example.com/#ja/mediaitems/pub-jwb-1_1_VIDEO")

    def test_rejects_missing_media_id(self) -> None:
        with self.assertRaises(SubtitleExtractionError):
            parse_jw_video_url("https://www.jw.org/ja/")


class FetchSubtitleUrlTests(unittest.TestCase):
    @patch("tools.jw_subtitles.http.urlopen")
    def test_returns_first_subtitle_url(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeResponse(
            json.dumps(
                {
                    "files": {
                        "J": {
                            "MP4": [
                                {
                                    "subtitles": {
                                        "url": "https://cdn.example/subtitles.vtt"
                                    }
                                }
                            ]
                        }
                    }
                }
            )
        )

        subtitle_url = fetch_subtitle_url("jwb-135", 1)

        self.assertEqual(subtitle_url, "https://cdn.example/subtitles.vtt")

    @patch("tools.jw_subtitles.http.urlopen")
    def test_raises_when_no_subtitles_exist(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeResponse(
            json.dumps({"files": {"J": {"MP4": [{}]}}})
        )

        with self.assertRaises(SubtitleExtractionError):
            fetch_subtitle_url("jwb-135", 1)


if __name__ == "__main__":
    unittest.main()
