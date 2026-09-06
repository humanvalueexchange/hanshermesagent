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

    def run(self, args: list[str], _stdin: bytes | None) -> str:
        self.calls.append(args)
        command = " ".join(args)
        if "repos/humanvalueexchange/hve-team/issues" in command and "--method" not in args:
            return "[]"
        if "repos/humanvalueexchange/hve-team/issues" in command:
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

    def test_approval_sensitivity_and_owner_gates(self) -> None:
        adapter = GitHubPhase1Adapter(runner=FakeGitHub().run)
        with self.assertRaisesRegex(GitHubPhase1Error, "approval"):
            adapter.create_tracking_record(task(), approved=False)
        with self.assertRaisesRegex(GitHubPhase1Error, "sensitivity"):
            adapter.create_tracking_record(task(sensitivity="financial"), approved=True)
        with self.assertRaisesRegex(GitHubPhase1Error, "owned by Hans"):
            adapter.create_tracking_record(task(owner="Hermes"), approved=True)

    def test_tracking_record_is_one_issue_and_one_project_item(self) -> None:
        fake = FakeGitHub()
        result = GitHubPhase1Adapter(runner=fake.run).create_tracking_record(task(), approved=True)
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["issue_number"], 7)
        self.assertEqual(result["project_item_id"], "PVTI-item-1")
        self.assertEqual(sum("issues" in " ".join(call) and "--method" in call for call in fake.calls), 1)
        self.assertEqual(sum(call[:2] == ["project", "item-add"] for call in fake.calls), 1)
        self.assertTrue(any(call[:2] == ["project", "item-edit"] for call in fake.calls))

    def test_artifact_publication_and_duplicate_safe_status(self) -> None:
        fake = FakeGitHub()
        adapter = GitHubPhase1Adapter(runner=fake.run)
        result = adapter.publish_artifact(
            task(),
            project_item_id="PVTI-item-1",
            filename="note.md",
            content=b"# Safe note\n",
            approved=True,
        )
        self.assertEqual(result["commit_sha"], "commit-1")
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


if __name__ == "__main__":
    unittest.main()
