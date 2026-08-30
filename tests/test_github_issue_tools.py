from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import github_issues


class GitHubIssueToolTests(unittest.TestCase):
    def test_read_github_issue_formats_issue_and_comments(self) -> None:
        issue_payload = {
            "title": "RFC: Knowledge Architecture",
            "state": "open",
            "user": {"login": "HansHWestphal"},
            "created_at": "2026-05-31T12:00:00Z",
            "labels": [{"name": "architecture"}, {"name": "rfc"}],
            "body": "Issue body text",
        }
        comments_payload = [
            {
                "user": {"login": "Claude"},
                "created_at": "2026-05-31T13:00:00Z",
                "body": "Looks good.",
            }
        ]

        with mock.patch("tools.github_issues._load_github_token", return_value="token"), mock.patch(
            "tools.github_issues._request_github_json",
            side_effect=[issue_payload, comments_payload],
        ):
            result = github_issues.read_github_issue(54)

        self.assertIn("## hanshermesagent#54: RFC: Knowledge Architecture", result)
        self.assertIn("Labels: architecture, rfc", result)
        self.assertIn("Issue body text", result)
        self.assertIn("### Comments (1)", result)
        self.assertIn("**Claude** (2026-05-31):", result)

    def test_comment_github_issue_appends_signature_when_missing(self) -> None:
        with mock.patch("tools.github_issues._load_github_token", return_value="token"), mock.patch(
            "tools.github_issues._request_github_json",
            return_value={"html_url": "https://github.com/humanvalueexchange/hanshermesagent/issues/54#issuecomment-1"},
        ) as request:
            result = github_issues.comment_github_issue(54, "Operational review")

        self.assertIn("✅ Comment posted on hanshermesagent#54", result)
        self.assertEqual(request.call_args.kwargs["method"], "POST")
        self.assertIn("Posted by Hermes", request.call_args.kwargs["payload"]["body"])

    def test_list_github_issues_filters_pull_requests(self) -> None:
        payload = [
            {"number": 54, "title": "RFC", "labels": [{"name": "architecture"}]},
            {"number": 55, "title": "PR masquerading as issue", "pull_request": {"url": "x"}, "labels": []},
            {"number": 56, "title": "Feature", "labels": []},
        ]

        with mock.patch("tools.github_issues._load_github_token", return_value="token"), mock.patch(
            "tools.github_issues._request_github_json",
            return_value=payload,
        ):
            result = github_issues.list_github_issues(limit=20)

        self.assertIn("## hanshermesagent — Open Issues (2 returned)", result)
        self.assertIn("- #54: RFC [architecture]", result)
        self.assertIn("- #56: Feature", result)
        self.assertNotIn("#55", result)

    def test_invalid_repo_and_state_return_errors(self) -> None:
        self.assertEqual(
            github_issues.read_github_issue(1, repo="bad-repo"),
            "ERROR: repo must be 'hanshermesagent' or 'mercury'",
        )
        self.assertEqual(
            github_issues.comment_github_issue(1, "text", repo="bad-repo"),
            "ERROR: repo must be 'hanshermesagent' or 'mercury'",
        )
        self.assertEqual(
            github_issues.list_github_issues(state="bad-state"),
            "ERROR: state must be 'open', 'closed', or 'all'",
        )

    def test_missing_token_and_empty_comment_are_handled(self) -> None:
        with mock.patch("tools.github_issues._load_github_token", return_value=None):
            self.assertEqual(
                github_issues.read_github_issue(54),
                "ERROR: HVE_GITHUB_TOKEN not found in ~/.hermes/.env",
            )

        self.assertEqual(
            github_issues.comment_github_issue(54, "   "),
            "ERROR: comment_body cannot be empty",
        )


if __name__ == "__main__":
    unittest.main()
