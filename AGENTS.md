# jw-summarize-cloud

This repository owns the human-facing Google Form -> Cloud Run summary pipeline.

## Repository Boundary

- Keep Cloud Run, Cloud Tasks, Apps Script, deployment docs, and cloud-only dependencies here.
- Keep agent harness workflows, Codex commands, local skills, Anki automation, and NotebookLM podcast automation in `jw-agent`.
- Share behavior through documented input/output contracts, not by making `jw-agent` the Cloud Run deployment repository.

## Entrypoint

Default Cloud Run entrypoint:

```text
gunicorn --bind :8080 tools.jw_summarize.webapp:app
```

If the package is renamed, update docs, tests, and Cloud Run settings together.

## Validation

Run focused tests before deployment:

```bash
uv run pytest
```
