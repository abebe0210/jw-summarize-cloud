from __future__ import annotations

import unittest

from tools.jw_subtitles.vtt import VttParseError, extract_text_from_vtt


class ExtractTextFromVttTests(unittest.TestCase):
    def test_extracts_readable_text(self) -> None:
        vtt = """WEBVTT

00:00:01.000 --> 00:00:03.000 line:90%
Hello
world

00:00:04.000 --> 00:00:05.000
<c.white>Second</c> line
"""

        text = extract_text_from_vtt(vtt)

        self.assertEqual(text, "Hello world\nSecond line")

    def test_raises_when_no_cues_are_present(self) -> None:
        with self.assertRaises(VttParseError):
            extract_text_from_vtt("WEBVTT\n\nNOTE empty")


if __name__ == "__main__":
    unittest.main()
