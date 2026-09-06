from __future__ import annotations

import hashlib
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import yaml

from tools.team_tasking_pilot import PilotError, PilotStore


class TeamTaskingPilotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_work_root = Path(__file__).resolve().parents[1] / ".test-work"
        self.test_work_root.mkdir(exist_ok=True)
        self.tempdir = tempfile.TemporaryDirectory(dir=self.test_work_root)
        root = Path(self.tempdir.name)
        self.store = PilotStore(root / "pilot.db", root / "artifacts")
        self.preview = self.store.normalize(
            source_message_id="wa-msg-001",
            source_message="Please prepare a public onboarding checklist.",
            owner="Hermes",
            deliverable="Public onboarding checklist",
            pillar="Time",
            due_date="2026-09-12",
            acceptance_criteria=["Checklist is in Markdown", "Each step has an owner"],
            risks=["Do not include credentials"],
        )
        self.task_id = self.preview["task_id"]

    def tearDown(self) -> None:
        self.tempdir.cleanup()
        try:
            self.test_work_root.rmdir()
        except OSError:
            pass

    def _pilot_server_module(self):
        class FakeFastMCP:
            def __init__(self, *_args, **_kwargs):
                pass

            def tool(self):
                return lambda function: function

            def run(self, *_args, **_kwargs):
                raise AssertionError("MCP server should not run during unit tests")

        with mock.patch.dict(sys.modules, {"fastmcp": types.SimpleNamespace(FastMCP=FakeFastMCP)}):
            sys.modules.pop("mcp.team_tasking_pilot_server", None)
            server = importlib.import_module("mcp.team_tasking_pilot_server")
        server.default_store = lambda: self.store
        return server

    def test_normalization_preview_is_draft_and_stable(self) -> None:
        duplicate = self.store.normalize(
            source_message_id="wa-msg-001",
            source_message="different retry",
            owner="Hermes",
            deliverable="Public onboarding checklist",
            pillar="Time",
            acceptance_criteria=["Checklist is in Markdown"],
        )
        self.assertEqual(self.preview["status"], "preview_ready")
        self.assertEqual(self.preview["state"], "draft")
        self.assertEqual(duplicate["task_id"], self.task_id)
        self.assertEqual(duplicate["status"], "duplicate_preview")

    def test_approval_gate_and_lifecycle_rejection_retry(self) -> None:
        with self.assertRaises(PilotError):
            self.store.starting(self.task_id, source_message="starting", event_id="s-before-approval")
        self.store.approve(self.task_id, approval_message_id="wa-approve-001")
        self.store.starting(self.task_id, source_message="starting", event_id="s-001")
        self.store.block(self.task_id, reason="Waiting for source material", source_message="blocked", event_id="b-001")
        self.store.retry(self.task_id, source_message="source arrived", event_id="r-001")
        self.store.report_done(self.task_id, source_message="done", event_id="d-001")
        rejected = self.store.validate(
            self.task_id, approved=False, reason="Add the missing evidence link",
            source_message="no", event_id="v-001",
        )
        self.assertEqual(rejected["state"], "open")
        self.assertEqual(self.store.events(self.task_id)[-1]["reason"], "Add the missing evidence link")

    def test_artifact_delivery_is_private_confirmed_and_idempotent(self) -> None:
        self.store.approve(self.task_id, approval_message_id="wa-approve-002")
        self.store.starting(self.task_id, source_message="starting", event_id="s-002")
        content = b"# Checklist"
        first = self.store.deliver_artifact(
            self.task_id, filename="checklist.md", content=content,
            source_message="artifact", event_id="a-001",
        )
        second = self.store.deliver_artifact(
            self.task_id, filename="checklist.md", content=content,
            source_message="artifact retry", event_id="a-001",
        )
        self.assertTrue(first["confirmed"])
        self.assertEqual(first["state"], "awaiting_validation")
        self.assertEqual(first["filename"], "checklist.md")
        self.assertEqual(first["byte_count"], len(content))
        self.assertEqual(first["line_count"], 1)
        self.assertEqual(first["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(first["final_state"], "awaiting_validation")
        self.assertTrue(first["awaiting_validation"])
        self.assertIn("Do not call report_done", first["operating_contract"])
        self.assertEqual(second["status"], "duplicate_artifact_delivery")
        self.assertTrue(second["confirmed"])
        self.assertEqual(second["filename"], first["filename"])
        self.assertEqual(second["sha256"], first["sha256"])
        self.assertTrue(str(first["artifact_path"]).startswith(str(self.store.artifact_root)))
        artifact_events = [
            event for event in self.store.events(self.task_id)
            if event["requested_transition"] == "artifact_delivery"
        ]
        self.assertEqual(len(artifact_events), 1)

    def test_deliver_text_artifact_accepts_utf8_and_writes_exact_bytes(self) -> None:
        self.store.approve(self.task_id, approval_message_id="wa-approve-text")
        server = self._pilot_server_module()
        text = "# Checklist\n- One\n"
        result = server.deliver_text_artifact(
            self.task_id,
            filename="checklist.md",
            content_text=text,
            source_message="deliver text",
            event_id="txt-001",
        )
        expected = text.encode("utf-8")
        self.assertEqual(result["status"], "artifact_confirmed")
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["state"], "awaiting_validation")
        self.assertEqual(result["byte_count"], len(expected))
        self.assertEqual(result["line_count"], 2)
        self.assertEqual(result["sha256"], hashlib.sha256(expected).hexdigest())
        self.assertEqual(Path(result["artifact_path"]).read_bytes(), expected)

    def test_artifact_delivery_rejects_malformed_input_without_state_change(self) -> None:
        self.store.approve(self.task_id, approval_message_id="wa-approve-malformed")
        server = self._pilot_server_module()
        invalid_base64 = server.deliver_artifact(
            self.task_id,
            filename="checklist.md",
            content_base64="not standard base64",
            source_message="bad artifact",
            event_id="bad-b64",
        )
        invalid_text = server.deliver_text_artifact(
            self.task_id,
            filename="checklist.md",
            content_text="\ud800",
            source_message="bad text",
            event_id="bad-text",
        )
        self.assertEqual(invalid_base64["status"], "rejected")
        self.assertFalse(invalid_base64["confirmed"])
        self.assertIn("invalid base64 artifact", invalid_base64["error"])
        self.assertEqual(invalid_text["status"], "rejected")
        self.assertFalse(invalid_text["confirmed"])
        self.assertIn("valid UTF-8 text", invalid_text["error"])
        self.assertEqual(self.store._get(self.task_id)["state"], "open")

    def test_artifact_delivery_blocks_done_transition_after_awaiting_validation(self) -> None:
        self.store.approve(self.task_id, approval_message_id="wa-approve-stop")
        delivered = self.store.deliver_text_artifact(
            self.task_id,
            filename="checklist.md",
            content_text="Ready for Hans validation\n",
            source_message="artifact",
            event_id="stop-001",
        )
        self.assertEqual(delivered["state"], "awaiting_validation")
        with self.assertRaisesRegex(PilotError, "current state is awaiting_validation"):
            self.store.report_done(self.task_id, source_message="done anyway", event_id="stop-done")

    def test_duplicate_artifact_event_id_with_different_content_is_rejected(self) -> None:
        self.store.approve(self.task_id, approval_message_id="wa-approve-conflict")
        self.store.deliver_text_artifact(
            self.task_id,
            filename="checklist.md",
            content_text="first\n",
            source_message="artifact",
            event_id="conflict-001",
        )
        with self.assertRaisesRegex(PilotError, "already used for a different artifact"):
            self.store.deliver_text_artifact(
                self.task_id,
                filename="checklist.md",
                content_text="second\n",
                source_message="artifact retry",
                event_id="conflict-001",
            )

    def test_sensitive_content_is_classified_and_public_entry_is_blocked(self) -> None:
        sensitive = self.store.normalize(
            source_message_id="wa-finance-001",
            source_message="Research an IUL investment strategy.",
            owner="Brian",
            deliverable="IUL investment research",
            pillar="Financial",
            acceptance_criteria=["Cite sources"],
        )
        self.assertEqual(sensitive["sensitivity"], "financial")
        self.assertEqual(sensitive["card"]["backend"], "private-phase-0-local")
        self.assertEqual(sensitive["card"]["public_repository"], "blocked_by_sensitivity_gate")
        self.assertEqual(sensitive["card"]["initial_state"], "open")
        self.store.approve(sensitive["task_id"], approval_message_id="wa-approve-finance")
        self.assertEqual(self.store._get(sensitive["task_id"])["state"], "open")

    def test_failure_exposes_pending_action_and_recovery(self) -> None:
        self.store.approve(self.task_id, approval_message_id="wa-approve-003")
        failed = self.store.failure(
            self.task_id, action="commit private artifact", error="permission denied",
            source_message="artifact", event_id="f-001",
        )
        self.assertEqual(failed["status"], "operation_failed")
        self.assertEqual(failed["pending_action"], "commit private artifact")
        self.assertIn("permission denied", failed["error"])
        recovered = self.store.retry(self.task_id, source_message="retry", event_id="f-retry")
        self.assertEqual(recovered["state"], "in_progress")

    def test_digest_groups_ownership_and_due_dates(self) -> None:
        digest = self.store.digest()
        self.assertEqual(digest["counts"]["draft"], 1)
        item = digest["tasks"]["draft"][0]
        self.assertEqual(item["owner"], "Hermes")
        self.assertEqual(item["due_date"], "2026-09-12")

    def test_reserved_al01_is_not_assignable(self) -> None:
        with self.assertRaisesRegex(PilotError, "AL-01"):
            self.store.normalize(
                source_message_id="al-01",
                source_message="Create AL-01 Alan bio",
                owner="Alan",
                deliverable="Alan's updated bio",
                pillar="Physical",
                acceptance_criteria=["Approved by Hans"],
            )

    def test_clean_phase0_uat_config_has_narrow_tool_boundary_and_64k_context(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        uat = yaml.safe_load((repo_root / "config" / "hermes-config.phase0-uat.yaml").read_text(encoding="utf-8"))
        template = yaml.safe_load((repo_root / "config" / "hermes-config.template.yaml").read_text(encoding="utf-8"))

        self.assertEqual(uat["model"]["context_length"], 65536)
        self.assertEqual(uat["model"]["ollama_num_ctx"], 65536)
        self.assertEqual(uat["model"]["context_length"], template["model"]["context_length"])
        self.assertEqual(uat["model"]["ollama_num_ctx"], template["model"]["ollama_num_ctx"])

        forbidden_tools = {"terminal", "browser", "web", "code_execution", "delegation", "cronjob", "computer_use"}
        self.assertTrue(forbidden_tools.issubset(set(uat["agent"]["disabled_toolsets"])))
        whatsapp_tools = set(uat["platform_toolsets"]["whatsapp"])
        self.assertFalse(forbidden_tools & whatsapp_tools)
        for tools in uat["platform_toolsets"].values():
            if isinstance(tools, list):
                self.assertFalse(forbidden_tools & set(tools))
        self.assertEqual(uat["toolsets"], ["hermes-cli"])
        self.assertEqual(set(uat["mcp_servers"]), {"hve-team-tasking-pilot"})

        pilot_filter = set(uat["mcp_servers"]["hve-team-tasking-pilot"]["tool_filter"])
        self.assertIn("deliver_text_artifact", pilot_filter)
        self.assertIn("deliver_artifact", pilot_filter)
        self.assertNotIn("report_done", pilot_filter)
        self.assertNotIn("validate_task", pilot_filter)


if __name__ == "__main__":
    unittest.main()
