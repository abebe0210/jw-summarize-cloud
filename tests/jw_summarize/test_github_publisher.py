from __future__ import annotations

import unittest
from dataclasses import replace

from tools.jw_summarize.config import Settings
from tools.jw_summarize.exceptions import ConfigError
from tools.jw_summarize.github_publisher import GitHubPublisher


class GitHubPublisherTests(unittest.TestCase):
    def test_rejects_template_repository_value(self) -> None:
        settings = replace(
            Settings.from_env(),
            github_token="token",
            github_repository="owner/repo",
        )

        with self.assertRaisesRegex(ConfigError, "not the template value"):
            GitHubPublisher(settings)

    def test_rejects_repository_without_owner_and_name(self) -> None:
        settings = replace(
            Settings.from_env(),
            github_token="token",
            github_repository="obsidian-jw",
        )

        with self.assertRaisesRegex(ConfigError, "owner/repo"):
            GitHubPublisher(settings)


if __name__ == "__main__":
    unittest.main()
