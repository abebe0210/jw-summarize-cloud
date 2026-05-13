"""CLI entry point for JW.org subtitle extraction."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .jw_api import SubtitleExtractionError, fetch_subtitle_text_from_page_url


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jw_subtitles",
        description="Extract readable subtitle text from a JW.org video URL.",
    )
    parser.add_argument("url", help="JW.org video URL containing a pub-..._VIDEO id.")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Write subtitle text to this file as UTF-8 instead of stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        text = fetch_subtitle_text_from_page_url(args.url)
    except SubtitleExtractionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.output is not None:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        _write_stdout(text)
    return 0


def _write_stdout(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        safe_text = text.encode(encoding, errors="replace").decode(encoding)
        sys.stdout.write(safe_text)
        sys.stdout.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
