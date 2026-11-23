"""Guards for a public repo: workflows must never hand secrets to outside code."""

import re
from pathlib import Path

WORKFLOWS = sorted((Path(__file__).parent.parent / ".github" / "workflows").glob("*.y*ml"))
FORBIDDEN_TRIGGERS = ("pull_request_target", "pull_request", "issue_comment", "workflow_run")
PINNED = re.compile(r"uses:\s*[\w.-]+/[\w./-]+@[0-9a-f]{40}\b")


def test_workflows_exist():
    assert WORKFLOWS


def test_no_triggers_that_run_outside_code():
    for wf in WORKFLOWS:
        text = wf.read_text(encoding="utf-8")
        for trigger in FORBIDDEN_TRIGGERS:
            assert not re.search(rf"^\s*{trigger}\s*:", text, re.M), f"{wf.name} uses {trigger}"


def test_actions_pinned_to_full_commit_sha():
    for wf in WORKFLOWS:
        for line in wf.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("- uses:") or line.strip().startswith("uses:"):
                assert PINNED.search(line), f"{wf.name}: not pinned to a commit SHA: {line.strip()}"


def test_default_permissions_are_read_only():
    for wf in WORKFLOWS:
        text = wf.read_text(encoding="utf-8")
        assert re.search(r"^permissions:\s*\n\s+contents:\s*read\s*$", text, re.M), wf.name
