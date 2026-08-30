from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

VALID_REPOS = ("hanshermesagent", "mercury")
VALID_STATES = ("open", "closed", "all")


def _load_github_token() -> str | None:
    env_file = os.path.expanduser("~/.hermes/.env")
    if not os.path.exists(env_file):
        return None
    for line in open(env_file).read().splitlines():
        if line.startswith("HVE_GITHUB_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def _request_github_json(
    path: str,
    token: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
) -> dict | list:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=15) as response:  # noqa: S310
        return json.loads(response.read())


def read_github_issue(issue_number: int, repo: str = "hanshermesagent") -> str:
    if repo not in VALID_REPOS:
        return "ERROR: repo must be 'hanshermesagent' or 'mercury'"

    token = _load_github_token()
    if not token:
        return "ERROR: HVE_GITHUB_TOKEN not found in ~/.hermes/.env"

    try:
        issue = _request_github_json(
            f"/repos/humanvalueexchange/{repo}/issues/{issue_number}",
            token,
        )
    except Exception as exc:
        return f"ERROR fetching issue: {exc}"

    try:
        comments = _request_github_json(
            f"/repos/humanvalueexchange/{repo}/issues/{issue_number}/comments",
            token,
        )
    except Exception as exc:
        comments = []
        comments_warning = f"WARNING: could not fetch comments: {exc}"
    else:
        comments_warning = ""

    labels = ", ".join(label["name"] for label in issue.get("labels", []))
    label_text = labels or "none"
    lines = [
        f"## {repo}#{issue_number}: {issue['title']}",
        (
            f"State: {issue['state']} | Author: {issue['user']['login']} | "
            f"Created: {issue['created_at'][:10]} | Labels: {label_text}"
        ),
        "",
        issue.get("body") or "(no body)",
    ]

    if comments_warning:
        lines.extend(["", comments_warning])

    if comments:
        lines.append(f"\n---\n### Comments ({len(comments)})")
        for comment in comments:
            lines.append(f"\n**{comment['user']['login']}** ({comment['created_at'][:10]}):")
            lines.append(comment.get("body") or "(empty)")
    else:
        lines.append("\n---\n*(no comments yet)*")

    return "\n".join(lines)


def comment_github_issue(issue_number: int, comment_body: str, repo: str = "hanshermesagent") -> str:
    if repo not in VALID_REPOS:
        return "ERROR: repo must be 'hanshermesagent' or 'mercury'"

    if not comment_body or not comment_body.strip():
        return "ERROR: comment_body cannot be empty"

    token = _load_github_token()
    if not token:
        return "ERROR: HVE_GITHUB_TOKEN not found in ~/.hermes/.env"

    body = comment_body.strip()
    if "_Hermes" not in body and "Hermes CFO" not in body:
        body += "\n\n---\n*Posted by Hermes (CFO AI agent, Human Value Exchange)*"

    try:
        data = _request_github_json(
            f"/repos/humanvalueexchange/{repo}/issues/{issue_number}/comments",
            token,
            method="POST",
            payload={"body": body},
        )
        return f"✅ Comment posted on {repo}#{issue_number}: {data['html_url']}"
    except Exception as exc:
        return f"ERROR posting comment: {exc}"


def list_github_issues(
    repo: str = "hanshermesagent",
    state: str = "open",
    label: str = "",
    limit: int = 20,
) -> str:
    if repo not in VALID_REPOS:
        return "ERROR: repo must be 'hanshermesagent' or 'mercury'"

    if state not in VALID_STATES:
        return "ERROR: state must be 'open', 'closed', or 'all'"

    limit = max(1, min(int(limit), 50))
    token = _load_github_token()
    if not token:
        return "ERROR: HVE_GITHUB_TOKEN not found in ~/.hermes/.env"

    params = {
        "state": state,
        "per_page": str(limit),
        "sort": "updated",
        "direction": "desc",
    }
    if label.strip():
        params["labels"] = label.strip()

    query = urllib.parse.urlencode(params)

    try:
        issues = _request_github_json(
            f"/repos/humanvalueexchange/{repo}/issues?{query}",
            token,
        )
    except Exception as exc:
        return f"ERROR listing issues: {exc}"

    filtered_issues = [issue for issue in issues if "pull_request" not in issue]
    if not filtered_issues:
        label_suffix = f" with label '{label.strip()}'" if label.strip() else ""
        return f"No {state} issues found in {repo}{label_suffix}."

    lines = [f"## {repo} — {state.capitalize()} Issues ({len(filtered_issues)} returned)\n"]
    for issue in filtered_issues:
        labels = ", ".join(label["name"] for label in issue.get("labels", []))
        label_suffix = f" [{labels}]" if labels else ""
        lines.append(f"- #{issue['number']}: {issue['title']}{label_suffix}")
    return "\n".join(lines)
