"""Narrow, idempotent GitHub adapter for the controlled Phase 1 UAT.

The local task store remains authoritative.  This module only performs explicit
public side effects after the caller has confirmed Hans approval.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable

from tools.team_tasking_pilot import classify_sensitivity


class GitHubPhase1Error(RuntimeError):
    """A visible, recoverable GitHub integration failure."""


@dataclass(frozen=True)
class GitHubPhase1Config:
    repository: str = "humanvalueexchange/hve-team"
    project_number: int = 2
    project_id: str = "PVT_kwDOESaYS84BilTn"
    branch: str = "main"
    project_status_field_id: str = "PVTSSF_lADOESaYS84BilTnzhhc0T8"
    project_status_options: dict[str, str] | None = None
    owner_field_id: str = "PVTF_lADOESaYS84BilTnzhhc0d8"
    pillar_field_id: str = "PVTSSF_lADOESaYS84BilTnzhhc0e4"
    due_date_field_id: str = "PVTF_lADOESaYS84BilTnzhhc0e8"
    sensitivity_field_id: str = "PVTSSF_lADOESaYS84BilTnzhhc0fY"
    task_id_field_id: str = "PVTF_lADOESaYS84BilTnzhhc0gU"

    def __post_init__(self) -> None:
        if self.project_status_options is None:
            object.__setattr__(
                self,
                "project_status_options",
                {
                    "open": "1564f9c5",
                    "in_progress": "6890158e",
                    "awaiting_validation": "d6a528b4",
                    "done": "07d87d56",
                },
            )


@dataclass(frozen=True)
class GitHubRecord:
    issue_number: int
    issue_url: str
    project_item_id: str


Runner = Callable[[list[str], bytes | None], str]


def _run_gh(arguments: list[str], stdin: bytes | None = None) -> str:
    try:
        completed = subprocess.run(
            ["gh", *arguments],
            input=stdin,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise GitHubPhase1Error(f"GitHub CLI is unavailable: {exc}") from exc
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        if "HTTP 404" in detail:
            return ""
        raise GitHubPhase1Error(f"GitHub operation failed: {detail or 'unknown error'}")
    return completed.stdout.decode("utf-8", errors="replace")


class GitHubPhase1Adapter:
    """Explicit GitHub mutations with deterministic lookup and no overwrites."""

    def __init__(self, config: GitHubPhase1Config | None = None, runner: Runner = _run_gh) -> None:
        self.config = config or GitHubPhase1Config()
        self.runner = runner

    @staticmethod
    def task_id(source_message_id: str) -> str:
        value = source_message_id.strip()
        if not value:
            raise GitHubPhase1Error("source message ID is required")
        return f"P1-{hashlib.sha256(value.encode()).hexdigest()[:12].upper()}"

    @staticmethod
    def event_id(source_message_id: str, action: str) -> str:
        if not source_message_id.strip() or not action.strip():
            raise GitHubPhase1Error("source message ID and action are required")
        digest = hashlib.sha256(f"{source_message_id}:{action}".encode()).hexdigest()[:16].upper()
        return f"P1E-{digest}"

    @staticmethod
    def artifact_path(task_id: str, filename: str) -> str:
        if not re.fullmatch(r"P1-[0-9A-F]{12}", task_id):
            raise GitHubPhase1Error("invalid Phase 1 task ID")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", filename):
            raise GitHubPhase1Error("artifact filename must be a simple safe filename")
        if filename in {".", ".."} or filename.startswith("."):
            raise GitHubPhase1Error("hidden artifact filenames are not allowed")
        return str(PurePosixPath("artifacts") / task_id / filename)

    @staticmethod
    def _json(text: str, operation: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise GitHubPhase1Error(f"{operation} returned malformed JSON") from exc

    def _require_public(self, task: dict[str, Any], content: bytes | None = None) -> None:
        values = [
            str(task.get("source_message", "")),
            str(task.get("deliverable", "")),
            *[str(v) for v in task.get("acceptance_criteria", [])],
            *[str(v) for v in task.get("risks", [])],
        ]
        if task.get("sensitivity") not in (None, "public"):
            raise GitHubPhase1Error("public GitHub side effect rejected by sensitivity gate")
        if classify_sensitivity(values + ([content.decode("utf-8", errors="replace")] if content else [])) != "public":
            raise GitHubPhase1Error("public GitHub side effect rejected by content safety gate")
        if task.get("owner") != "Hans":
            raise GitHubPhase1Error("Phase 1 public task must be owned by Hans")
        if task.get("pillar") not in {"Time", "Physical", "Mental", "Social", "Financial"}:
            raise GitHubPhase1Error("invalid task pillar")

    def _issue(self, task: dict[str, Any]) -> dict[str, Any]:
        marker = f"[HVE-TASK {task['task_id']}]"
        result = self.runner(
            [
                "issue",
                "list",
                "--repo",
                self.config.repository,
                "--state",
                "all",
                "--search",
                f'"{marker}" in:title',
                "--json",
                "number,url,title",
            ],
            None,
        )
        if result.strip():
            parsed = self._json(result, "issue lookup")
            matches = [item for item in parsed if marker in str(item.get("title", ""))]
            if matches:
                return matches[0]
        body = (
            f"{marker}\n\n"
            f"Owner: {task['owner']}\nPillar: {task['pillar']}\n"
            f"Sensitivity: {task['sensitivity']}\nTask ID: `{task['task_id']}`\n\n"
            "Approved public Phase 1 task. Hans validates the artifact before completion."
        )
        try:
            created_text = self.runner(
                [
                    "api",
                    f"repos/{self.config.repository}/issues",
                    "--method",
                    "POST",
                    "-f",
                    f"title={marker} {task['deliverable']}",
                    "-f",
                    f"body={body}",
                ],
                None,
            )
            created = self._json(created_text, "issue creation")
        except GitHubPhase1Error:
            # A timed-out POST may have succeeded. Reconcile before surfacing
            # the failure so a retry cannot create a second issue.
            retry_result = self.runner(
                [
                    "issue",
                    "list",
                    "--repo",
                    self.config.repository,
                    "--state",
                    "all",
                    "--search",
                    f'"{marker}" in:title',
                    "--json",
                    "number,url,title",
                ],
                None,
            )
            matches = [
                item
                for item in self._json(retry_result, "issue retry lookup")
                if marker in str(item.get("title", ""))
            ]
            if matches:
                return matches[0]
            raise
        return created

    def _project_items(self) -> list[dict[str, Any]]:
        result = self.runner(
            [
                "project",
                "item-list",
                str(self.config.project_number),
                "--owner",
                "humanvalueexchange",
                "--format",
                "json",
            ],
            None,
        )
        parsed = self._json(result, "project item lookup")
        return parsed.get("items", []) if isinstance(parsed, dict) else parsed

    def _set_field(
        self,
        item_id: str,
        field_id: str,
        value: str,
        *,
        single_select: bool = False,
        date: bool = False,
    ) -> None:
        args = [
            "project",
            "item-edit",
            "--id",
            item_id,
            "--project-id",
            self.config.project_id,
            "--field-id",
            field_id,
        ]
        args += [
            "--single-select-option-id" if single_select else "--date" if date else "--text",
            value,
        ]
        self.runner(args, None)

    def create_tracking_record(self, task: dict[str, Any], *, approved: bool) -> dict[str, Any]:
        if not approved:
            raise GitHubPhase1Error("GitHub tracking creation requires explicit Hans approval")
        self._require_public(task)
        issue = self._issue(task)
        issue_url = issue.get("html_url") or issue.get("url")
        issue_number = issue.get("number")
        if not issue_url or not issue_number:
            raise GitHubPhase1Error("issue response lacked number or URL")
        item = next(
            (
                candidate
                for candidate in self._project_items()
                if str(candidate.get("content", {}).get("number", "")) == str(issue_number)
                or candidate.get("content", {}).get("url") == issue_url
            ),
            None,
        )
        if item is None:
            item = self._json(
                self.runner(
                    [
                        "project",
                        "item-add",
                        str(self.config.project_number),
                        "--owner",
                        "humanvalueexchange",
                        "--url",
                        issue_url,
                        "--format",
                        "json",
                    ],
                    None,
                ),
                "project item creation",
            )
        item_id = item.get("id") or item.get("item", {}).get("id")
        if not item_id:
            raise GitHubPhase1Error("project item response lacked item ID")
        self._set_field(item_id, self.config.owner_field_id, task["owner"])
        self._set_field(item_id, self.config.pillar_field_id, task["pillar"], single_select=True)
        self._set_field(item_id, self.config.sensitivity_field_id, task["sensitivity"], single_select=True)
        self._set_field(item_id, self.config.task_id_field_id, task["task_id"])
        if task.get("due_date"):
            self._set_field(item_id, self.config.due_date_field_id, task["due_date"], date=True)
        self.set_status(item_id, "open")
        return {
            "status": "tracking_confirmed",
            "confirmed": True,
            "issue_number": issue_number,
            "issue_url": issue_url,
            "project_item_id": item_id,
            "project_url": f"https://github.com/orgs/humanvalueexchange/projects/{self.config.project_number}",
            "task_id": task["task_id"],
        }

    def set_status(self, project_item_id: str, state: str) -> dict[str, Any]:
        option = (self.config.project_status_options or {}).get(state)
        if not option:
            raise GitHubPhase1Error(f"no GitHub Project status mapping for {state}")
        self._set_field(project_item_id, self.config.project_status_field_id, option, single_select=True)
        return {"status": "project_status_confirmed", "confirmed": True, "state": state, "project_item_id": project_item_id}

    def publish_artifact(
        self,
        task: dict[str, Any],
        *,
        project_item_id: str,
        filename: str,
        content: bytes,
        approved: bool,
    ) -> dict[str, Any]:
        if not approved:
            raise GitHubPhase1Error("artifact publication requires explicit Hans approval")
        self._require_public(task, content)
        path = self.artifact_path(task["task_id"], filename)
        encoded = base64.b64encode(content).decode("ascii")
        lookup = self.runner(
            ["api", f"repos/{self.config.repository}/contents/{path}", "-H", "Accept: application/vnd.github+json"],
            None,
        )
        if lookup.strip():
            existing = self._json(lookup, "artifact lookup")
            existing_content = existing.get("content", "").replace("\n", "")
            if existing_content and base64.b64decode(existing_content) != content:
                raise GitHubPhase1Error("artifact path already exists with different content; no overwrite performed")
            commit_lookup = self.runner(
                [
                    "api",
                    f"repos/{self.config.repository}/commits",
                    "-f",
                    f"path={path}",
                    "-f",
                    f"sha={self.config.branch}",
                    "-f",
                    "per_page=1",
                ],
                None,
            )
            commits = self._json(commit_lookup, "artifact commit lookup") if commit_lookup.strip() else []
            commit_sha = commits[0].get("sha") if commits else existing.get("commit", {}).get("sha")
            if not commit_sha:
                raise GitHubPhase1Error("existing artifact lacked a commit SHA")
            self.set_status(project_item_id, "awaiting_validation")
            return {"status": "artifact_duplicate", "confirmed": True, "artifact_path": path, "commit_sha": commit_sha}
        response = self._json(
            self.runner(
                [
                    "api",
                    f"repos/{self.config.repository}/contents/{path}",
                    "--method",
                    "PUT",
                    "-f",
                    f"message=Publish approved HVE task artifact {task['task_id']}",
                    "-f",
                    f"content={encoded}",
                    "-f",
                    f"branch={self.config.branch}",
                ],
                None,
            ),
            "artifact publication",
        )
        commit_sha = response.get("commit", {}).get("sha")
        if not commit_sha:
            raise GitHubPhase1Error("artifact publication response lacked commit SHA")
        self.set_status(project_item_id, "awaiting_validation")
        return {
            "status": "artifact_published",
            "confirmed": True,
            "artifact_path": path,
            "commit_sha": commit_sha,
            "project_item_id": project_item_id,
        }
