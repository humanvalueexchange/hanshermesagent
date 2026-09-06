from __future__ import annotations

import base64
import json
import unittest
from pathlib import Path

import yaml

from tools.github_phase1 import GitHubPhase1Adapter, GitHubPhase1Config, GitHubPhase1Error


class FakeGitHub:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.artifact_exists = False
        self.issue_created = False

    def run(self, args: list[str], _stdin: bytes | None) -> str:
        self.calls.append(args)
        command = " ".join(args)
        if args[:2] == ["issue", "list"]:
            return (
                json.dumps([{
                    "number": 7,
                    "html_url": "https://github.com/humanvalueexchange/hve-team/issues/7",
                    "title": "[HVE-TASK P1-ABCDEF123456] Harmless public note",
                }])
                if self.issue_created
                else "[]"
            )
        if "repos/humanvalueexchange/hve-team/issues" in command and "--method" not in args:
            if "/comments" in command:
                return "[]"
            if self.issue_created:
                return json.dumps([{"number": 7, "html_url": "https://github.com/humanvalueexchange/hve-team/issues/7"}])
            return "[]"
        if "repos/humanvalueexchange/hve-team/issues" in command:
            if "/comments" in command:
                return json.dumps({"html_url": "https://github.com/humanvalueexchange/hve-team/issues/7#issuecomment-1"})
            self.issue_created = True
            return json.dumps({"number": 7, "html_url": "https://github.com/humanvalueexchange/hve-team/issues/7"})
        if args[:2] == ["project", "item-list"]:
            return json.dumps({"items": []})
        if args[:2] == ["project", "item-add"]:
            return json.dumps({"id": "PVTI-item-1"})
        if "/contents/artifacts/" in command and "--method" not in args:
            return ""
        if "/contents/artifacts/" in command and "--method" in args:
            return json.dumps({"commit": {"sha": "commit-1"}})
        return ""


def task(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "task_id": "P1-ABCDEF123456",
        "source_message": "Share a harmless public note.",
        "deliverable": "Harmless public note",
        "acceptance_criteria": ["Markdown"],
        "risks": [],
        "owner": "Hans",
        "pillar": "Time",
        "sensitivity": "public",
    }
    value.update(overrides)
    return value


class GitHubPhase1Tests(unittest.TestCase):
    def test_identity_and_safe_path_are_deterministic(self) -> None:
        self.assertEqual(
            GitHubPhase1Adapter.task_id("wa-001"),
            GitHubPhase1Adapter.task_id("wa-001"),
        )
        self.assertEqual(
            GitHubPhase1Adapter.event_id("wa-001", "approve"),
            GitHubPhase1Adapter.event_id("wa-001", "approve"),
        )
        self.assertEqual(
            GitHubPhase1Adapter.artifact_path("P1-ABCDEF123456", "note.md"),
            "artifacts/P1-ABCDEF123456/note.md",
        )
        with self.assertRaises(GitHubPhase1Error):
            GitHubPhase1Adapter.artifact_path("P1-ABCDEF123456", "../secret")

    def test_approval_and_declared_owner_validation_without_sensitivity_gate(self) -> None:
        adapter = GitHubPhase1Adapter(runner=FakeGitHub().run)
        with self.assertRaisesRegex(GitHubPhase1Error, "approval"):
            adapter.create_tracking_record(task(), approved=False)
        for owner in ("Alan", "Brian"):
            with self.subTest(owner=owner):
                accepted = adapter.create_tracking_record(
                    task(
                        owner=owner,
                        source_message="Review a bank investment workflow.",
                        deliverable=f"{owner} investment workflow",
                        sensitivity="financial",
                    ),
                    approved=True,
                )
                self.assertTrue(accepted["confirmed"])
        with self.assertRaisesRegex(GitHubPhase1Error, "owner is required"):
            adapter.create_tracking_record(task(owner=""), approved=True)

    def test_authenticated_artifact_publication_accepts_non_public_classification(self) -> None:
        fake = FakeGitHub()
        adapter = GitHubPhase1Adapter(runner=fake.run)
        adapter.create_tracking_record(task(owner="Brian", sensitivity="financial"), approved=True)
        fake.issue_created = True
        result = adapter.publish_artifact(
            task(owner="Brian", sensitivity="financial"),
            project_item_id="PVTI-item-1",
            filename="investment.md",
            content=b"Private investment working notes.\n",
            approved=True,
        )
        self.assertEqual(result["status"], "artifact_published")

    def test_tracking_record_is_one_issue_and_one_project_item(self) -> None:
        fake = FakeGitHub()
        result = GitHubPhase1Adapter(runner=fake.run).create_tracking_record(task(), approved=True)
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["issue_number"], 7)
        self.assertEqual(result["project_item_id"], "PVTI-item-1")
        self.assertEqual(sum("issues" in " ".join(call) and "--method" in call for call in fake.calls), 1)
        self.assertEqual(sum(call[:2] == ["project", "item-add"] for call in fake.calls), 1)
        self.assertTrue(any(call[:2] == ["project", "item-edit"] for call in fake.calls))
        field_calls = [" ".join(call) for call in fake.calls if call[:2] == ["project", "item-edit"]]
        self.assertTrue(any("--single-select-option-id 23cd5c76" in call for call in field_calls))
        self.assertTrue(any("--single-select-option-id 49826168" in call for call in field_calls))

    def test_artifact_publication_and_duplicate_safe_status(self) -> None:
        fake = FakeGitHub()
        adapter = GitHubPhase1Adapter(runner=fake.run)
        adapter.create_tracking_record(task(), approved=True)
        fake.issue_created = True
        result = adapter.publish_artifact(
            task(),
            project_item_id="PVTI-item-1",
            filename="note.md",
            content=b"# Safe note\n",
            approved=True,
        )
        self.assertEqual(result["commit_sha"], "commit-1")
        self.assertIn("artifact_comment_url", result)
        self.assertTrue(any("/contents/artifacts/" in " ".join(call) and "--method" in call for call in fake.calls))
        with self.assertRaisesRegex(GitHubPhase1Error, "different content"):
            class Conflicting(FakeGitHub):
                def run(self, args: list[str], stdin: bytes | None) -> str:
                    if "/contents/artifacts/" in " ".join(args) and "--method" not in args:
                        return json.dumps({"content": base64.b64encode(b"different").decode()})
                    return super().run(args, stdin)
            GitHubPhase1Adapter(runner=Conflicting().run).publish_artifact(
                task(), project_item_id="PVTI-item-1", filename="note.md",
                content=b"# Safe note\n", approved=True,
            )

    def test_named_artifact_comment_operation_is_approval_gated_and_idempotent(self) -> None:
        fake = FakeGitHub()
        adapter = GitHubPhase1Adapter(runner=fake.run)
        adapter.create_tracking_record(task(), approved=True)
        fake.issue_created = True
        with self.assertRaisesRegex(GitHubPhase1Error, "approval"):
            adapter.post_artifact_comment(
                task(),
                filename="note.md",
                content=b"# Safe note\n",
                commit_sha="commit-1",
                approved=False,
            )
        result = adapter.post_artifact_comment(
            task(),
            filename="note.md",
            content=b"# Safe note\n",
            commit_sha="commit-1",
            approved=True,
        )
        self.assertTrue(result["confirmed"])
        self.assertIn("artifact_comment_url", result)

    def test_phase1_config_is_separate_and_narrow(self) -> None:
        path = Path(__file__).resolve().parents[1] / "config" / "hermes-config.phase1-uat.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(config["model"]["context_length"], 65536)
        self.assertTrue(config["platforms"]["whatsapp"]["enabled"])
        self.assertFalse(config["platforms"]["telegram"]["enabled"])
        self.assertEqual(config["platform_toolsets"]["whatsapp"], [])
        forbidden = {"terminal", "browser", "web", "delegation", "cronjob", "code_execution", "computer_use"}
        self.assertTrue(forbidden.issubset(set(config["agent"]["disabled_toolsets"])))
        self.assertEqual(set(config["mcp_servers"]), {"hve-team-tasking-phase1"})
        self.assertNotIn("tool_call", config["mcp_servers"]["hve-team-tasking-phase1"]["tool_filter"])
        self.assertIn("post_artifact_comment", config["mcp_servers"]["hve-team-tasking-phase1"]["tool_filter"])


if __name__ == "__main__":
    unittest.main()
