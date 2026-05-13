from __future__ import annotations

from typing import Any, Sequence

import requests

from .config import Settings
from .exceptions import ConfigError, PublishError
from .models import ProcessingRequest, PublishResult, RenderedNote


class GitHubPublisher:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        if not settings.github_enabled:
            raise ConfigError(
                "GITHUB_TOKEN and GITHUB_REPOSITORY must be set for GitHub publishing."
            )
        self._settings = settings
        self._session = session or requests.Session()
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {settings.github_token}",
            "User-Agent": "jw-summarize/2.0",
        }

    def publish(
        self,
        notes: Sequence[RenderedNote],
        request: ProcessingRequest,
        title: str,
    ) -> PublishResult:
        try:
            ref = self._request(
                "GET",
                f"/repos/{self._settings.github_repository}/git/ref/heads/{self._settings.github_branch}",
            )
            base_commit_sha = ref["object"]["sha"]
            commit = self._request(
                "GET",
                f"/repos/{self._settings.github_repository}/git/commits/{base_commit_sha}",
            )
            base_tree_sha = commit["tree"]["sha"]

            tree_entries = []
            for note in notes:
                blob = self._request(
                    "POST",
                    f"/repos/{self._settings.github_repository}/git/blobs",
                    json_body={"content": note.content, "encoding": "utf-8"},
                )
                tree_entries.append(
                    {
                        "path": note.path,
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob["sha"],
                    }
                )

            tree = self._request(
                "POST",
                f"/repos/{self._settings.github_repository}/git/trees",
                json_body={"base_tree": base_tree_sha, "tree": tree_entries},
            )
            new_commit = self._request(
                "POST",
                f"/repos/{self._settings.github_repository}/git/commits",
                json_body={
                    "message": self._commit_message(title, request),
                    "tree": tree["sha"],
                    "parents": [base_commit_sha],
                },
            )
            self._request(
                "PATCH",
                f"/repos/{self._settings.github_repository}/git/refs/heads/{self._settings.github_branch}",
                json_body={"sha": new_commit["sha"], "force": False},
            )
        except requests.HTTPError as exc:
            raise PublishError(f"GitHub API request failed: {exc}") from exc
        except KeyError as exc:
            raise PublishError(f"Unexpected GitHub API response: missing {exc}") from exc

        commit_sha = new_commit["sha"]
        return PublishResult(
            commit_sha=commit_sha,
            commit_url=f"https://github.com/{self._settings.github_repository}/commit/{commit_sha}",
        )

    def _request(
        self, method: str, path: str, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = self._session.request(
            method=method,
            url=f"{self._settings.github_api_base}{path}",
            headers=self._headers,
            json=json_body,
            timeout=self._settings.http_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _commit_message(title: str, request: ProcessingRequest) -> str:
        return f"Update notes for {title} ({request.resolved_request_id})"
