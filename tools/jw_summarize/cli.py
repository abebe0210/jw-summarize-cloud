from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .config import Settings
from .github_publisher import GitHubPublisher
from .local_publisher import LocalPublisher
from .models import ProcessingRequest
from .service import SummarizationService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the jw-summarize pipeline locally or publish to GitHub."
    )
    parser.add_argument("--payload-file", help="JSON payload file matching the HTTP contract.")
    parser.add_argument("--source-type", choices=["url", "text"])
    parser.add_argument("--source-url")
    parser.add_argument("--text", help="Transcript text.")
    parser.add_argument("--text-file", help="Read transcript text from a file.")
    parser.add_argument("--title", help="Optional title override.")
    parser.add_argument("--supplemental-note", help="Optional extra note.")
    parser.add_argument("--request-id", help="Request identifier.")
    parser.add_argument("--sheet-row-id", help="Optional sheet row identifier.")
    parser.add_argument("--submitted-at", help="Submission timestamp.")
    parser.add_argument("--summary-text", help="Use a precomputed summary instead of calling the LLM.")
    parser.add_argument("--summary-file", help="Read a precomputed summary from a file.")
    parser.add_argument("--provider", choices=["vertexai", "openai"])
    parser.add_argument("--profile", choices=["heavy", "light"])
    parser.add_argument(
        "--publish-github",
        action="store_true",
        help="Publish directly to GitHub instead of writing locally.",
    )
    parser.add_argument(
        "--output-dir",
        help="Local output directory. Defaults to LOCAL_OUTPUT_DIR when not publishing to GitHub.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)

    payload = _build_payload(args)
    request = ProcessingRequest.from_mapping(payload)

    settings = Settings.from_env()
    if args.output_dir:
        settings = replace(settings, local_output_dir=args.output_dir)

    publisher = (
        GitHubPublisher(settings)
        if args.publish_github
        else LocalPublisher(settings.local_output_dir)
    )
    result = SummarizationService(
        settings=settings,
        publisher=publisher,
        summary_generator=_build_summary_generator(args),
    ).process(request)
    print(
        json.dumps(
            {"status": "success", **result.to_dict()},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _build_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.payload_file:
        return json.loads(Path(args.payload_file).read_text(encoding="utf-8"))

    text_values = [value for value in [args.text, _read_text_file(args.text_file)] if value]
    if len(text_values) > 1:
        raise SystemExit("Only one of --text or --text-file may be used.")
    if not args.source_type:
        raise SystemExit("--source-type is required unless --payload-file is used.")
    if not text_values:
        raise SystemExit("Transcript text is required via --text or --text-file.")

    return {
        "source_type": args.source_type,
        "source_url": args.source_url,
        "raw_text": text_values[0],
        "title_override": args.title,
        "supplemental_note": args.supplemental_note,
        "request_id": args.request_id,
        "sheet_row_id": args.sheet_row_id,
        "submitted_at": args.submitted_at,
        "provider": args.provider,
        "profile": args.profile,
    }


def _read_text_file(path: str | None) -> str | None:
    if not path:
        return None
    return Path(path).read_text(encoding="utf-8")


def _build_summary_generator(args: argparse.Namespace):
    summary_values = [
        value for value in [args.summary_text, _read_text_file(args.summary_file)] if value
    ]
    if len(summary_values) > 1:
        raise SystemExit("Only one of --summary-text or --summary-file may be used.")
    if not summary_values:
        return None

    def _static_summary(
        text: str,
        settings: Settings,
        provider: str | None,
        profile: str | None,
    ) -> str:
        del text, settings, provider, profile
        return summary_values[0]

    return _static_summary
