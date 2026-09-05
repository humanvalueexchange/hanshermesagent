from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.team_tasking_pilot import PilotError, PilotStore


class TeamTaskingPilotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
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
        first = self.store.deliver_artifact(
            self.task_id, filename="checklist.md", content=b"# Checklist",
            source_message="artifact", event_id="a-001",
        )
        second = self.store.deliver_artifact(
            self.task_id, filename="checklist.md", content=b"# Checklist",
            source_message="artifact retry", event_id="a-001",
        )
        self.assertTrue(first["confirmed"])
        self.assertEqual(first["state"], "awaiting_validation")
        self.assertEqual(second["status"], "duplicate_artifact_delivery")
        self.assertTrue(str(first["artifact_path"]).startswith(str(self.store.artifact_root)))

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


if __name__ == "__main__":
    unittest.main()
