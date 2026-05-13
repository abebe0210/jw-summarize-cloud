# jw-summarize-cloud

Human-facing Cloud Run pipeline for JW summary generation.

This repository is split out from `jw-agent` so that:

- `jw-agent` stays focused on agent harness workflows, skills, commands, and local automation.
- `jw-summarize-cloud` owns the Google Form -> Spreadsheet -> Apps Script -> Cloud Tasks -> Cloud Run production pipeline.

Both repositories should keep the same Obsidian output contract:

- input types: `url`, `text`, `audio`
- output notes: summary note and transcript note
- summary directory: `OBSIDIAN_SUMMARY_DIR`
- transcript directory: `OBSIDIAN_TRANSCRIPT_DIR`
- title rules documented in `docs/design/cloud-pipeline.md`

## What To Copy

Copy the contents of this directory into a new GitHub repository named `jw-summarize-cloud`.

Recommended first commit:

```bash
git init
git add .
git commit -m "Initial jw-summarize-cloud split"
git branch -M main
git remote add origin git@github.com:<owner>/jw-summarize-cloud.git
git push -u origin main
```

Then connect that repository to Cloud Run. Do not connect `jw-agent` to Cloud Run.

## Runtime

Cloud Run entrypoint, if keeping the migrated package path:

```text
gunicorn --bind :8080 tools.jw_summarize.webapp:app
```

If you later rename the package to `jw_summarize_cloud`, update the entrypoint and imports together.

## Included

- `tools/jw_summarize/`: Flask app and summarization pipeline
- `tools/jw_subtitles/`: JW.org subtitle extraction used by URL input
- `scripts/cloud_pipeline/`: Apps Script source
- `docs/design/cloud-pipeline.md`: architecture and repo-boundary design
- `docs/deploy/`: UI and CLI deployment guides
- `tests/jw_summarize/`, `tests/jw_subtitles/`: focused tests copied from `jw-agent`

## Local Check

```bash
uv sync --extra dev
uv run pytest
uv run gunicorn --bind :8080 tools.jw_summarize.webapp:app
```

For Cloud Run, set environment variables from `.env.example` and follow `docs/deploy/cloud-pipeline-gcp-ui.md`.
