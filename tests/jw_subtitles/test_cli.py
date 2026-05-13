from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.jw_subtitles.cli import main
from tools.jw_subtitles.jw_api import SubtitleExtractionError


class EncodingAwareStdout:
    def __init__(self, encoding: str) -> None:
        self.encoding = encoding
        self._parts: list[str] = []

    def write(self, value: str) -> int:
        value.encode(self.encoding)
        self._parts.append(value)
        return len(value)

    def flush(self) -> None:
        return None

    def getvalue(self) -> str:
        return "".join(self._parts)


class CliTests(unittest.TestCase):
    @patch("tools.jw_subtitles.cli.fetch_subtitle_text_from_page_url")
    def test_cli_prints_text(self, mock_fetch) -> None:
        mock_fetch.return_value = "line 1\nline 2"
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            code = main(
                [
                    "https://www.jw.org/ja/#ja/mediaitems/StudioFeatured/pub-jwb-135_1_VIDEO"
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "line 1\nline 2\n")
        self.assertEqual(stderr.getvalue(), "")

    @patch("tools.jw_subtitles.cli.fetch_subtitle_text_from_page_url")
    def test_cli_prints_errors_to_stderr(self, mock_fetch) -> None:
        mock_fetch.side_effect = SubtitleExtractionError("bad url")
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            code = main(["https://www.jw.org/ja/"])

        self.assertEqual(code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "Error: bad url\n")

    @patch("tools.jw_subtitles.cli.fetch_subtitle_text_from_page_url")
    def test_cli_writes_output_to_file_as_utf8(self, mock_fetch) -> None:
        mock_fetch.return_value = "JW Broadcasting®\nライン2"
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "out.txt"
            with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                code = main(
                    [
                        "https://www.jw.org/ja/#ja/mediaitems/StudioFeatured/pub-jwb-135_1_VIDEO",
                        "--output",
                        str(output_path),
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "JW Broadcasting®\nライン2\n",
            )

    @patch("tools.jw_subtitles.cli.fetch_subtitle_text_from_page_url")
    def test_cli_replaces_unencodable_stdout_characters(self, mock_fetch) -> None:
        mock_fetch.return_value = "JW Broadcasting\u00ae"
        stderr = io.StringIO()
        stdout = EncodingAwareStdout("cp932")

        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            code = main(
                [
                    "https://www.jw.org/ja/#ja/mediaitems/StudioFeatured/pub-jwb-135_1_VIDEO"
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "JW Broadcasting?\n")
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
