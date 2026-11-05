import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import logmig_dispatch as d  # noqa: E402

REPO = "arunbalaji2019/harbor-lane"


def test_plan_skips_done_open_pr_running_and_needs_human():
    decisions = d.plan(
        ["bookings", "payments", "tracking", "invoicing", "quotes", "customers"],
        unmigrated={"payments", "tracking", "invoicing", "quotes", "customers"},
        open_pr_titles=["[logmig] payments: move to harbor_obs", "[logmig] paymentsx: other"],
        running={"tracking": "https://app.devin.ai/sessions/x"},
        row_status={"invoicing": "needs human: Finance sign-off", "quotes": "stopped"},
    )
    acts = {svc: act for svc, act, _ in decisions}
    assert acts == {"bookings": "skip", "payments": "skip", "tracking": "skip",
                    "invoicing": "skip", "quotes": "start", "customers": "start"}


def test_needs_human_can_be_retried():
    decisions = d.plan(["invoicing"], {"invoicing"}, [], {}, {"invoicing": "needs human: x"}, include_needs_human=True)
    assert decisions == [("invoicing", "start", "")]


def test_session_body_tags_limit_skill_and_row():
    body = d.session_body(REPO, "quotes", 4, 123, 7)
    assert body["tags"] == ["logmig", "logmig-harbor-lane", "logmig-harbor-lane-quotes"]
    assert body["max_acu_limit"] == 7 and body["repos"] == [REPO]
    assert ".agents/skills/logmig/SKILL.md" in body["prompt"] and "comment 123" in body["prompt"]
    assert body["structured_output_schema"]["properties"]["status"]["enum"][1] == "needs_human"


def test_tagged_service_and_row_text():
    assert d.tagged_service({"tags": ["logmig", "logmig-harbor-lane", "logmig-harbor-lane-legacy_edi"]}, REPO) == "legacy_edi"
    row = d.row_text(REPO, "quotes", "needs human: a | b", session_url="https://x/y")
    assert row == "<!-- logmig-row -->\n| harbor-lane/quotes | needs human: a \\| b |  |  | [session](https://x/y) |"


def test_select_rejects_unknown_services():
    assert d.select("all", ["a", "b"]) == ["a", "b"]
    assert d.select(" b, a ", ["a", "b"]) == ["b", "a"]
    with pytest.raises(SystemExit):
        d.select("a,zzz", ["a", "b"])


def test_discover_finds_every_service():
    assert d.discover() == ["bookings", "customers", "invoicing", "legacy_edi",
                            "notifications", "payments", "quotes", "tracking"]


def test_select_drops_duplicates():
    assert d.select("quotes, quotes,tracking", ["quotes", "tracking"]) == ["quotes", "tracking"]


class FakeIssue:
    def __init__(self, body="<!-- logmig-table:start -->\n<!-- logmig-table:end -->", fail_on_call=None, rows=None):
        self.body, self.fail_on_call, self.writes, self._rows = body, fail_on_call, [], rows or {}

    def require_table(self):
        if "logmig-table:start" not in self.body:
            raise SystemExit("no markers")

    def rows(self):
        return self._rows

    def upsert_row(self, existing, body):
        self.writes.append(body)
        if self.fail_on_call == len(self.writes):
            raise RuntimeError("GitHub said no")
        return 99

    def rebuild(self):
        pass


class FakeDevin:
    def __init__(self):
        self.created = []

    def sessions(self, tags):
        return []

    def create(self, body):
        self.created.append(body)
        return {"url": "https://app.devin.ai/sessions/abc", "session_id": "devin-abc"}


def args(**kw):
    import argparse
    base = dict(services="quotes", max_acu=5, issue=4, include_needs_human=False, dry_run=False)
    return argparse.Namespace(**{**base, **kw})


@pytest.fixture
def no_github(monkeypatch):
    monkeypatch.setattr(d, "open_pr_titles", lambda repo: [])
    monkeypatch.setattr(d, "request_rebuild", lambda repo, issue: None, raising=False)


def test_run_refuses_an_issue_without_markers_before_starting(no_github):
    devin = FakeDevin()
    with pytest.raises(SystemExit):
        d.run(args(), REPO, devin, FakeIssue(body="no table here"))
    assert devin.created == []


def test_row_update_failure_after_create_does_not_mark_dispatch_failed(no_github):
    devin, issue = FakeDevin(), FakeIssue(fail_on_call=2)
    assert d.run(args(), REPO, devin, issue) == 0
    assert len(devin.created) == 1
    assert not any("dispatch failed" in w for w in issue.writes)


def workflow(name):
    import yaml
    wf = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github/workflows" / name).read_text())
    return wf, wf.get("on", wf.get(True))


def test_rebuilds_go_through_the_progress_workflow(monkeypatch):
    calls = []
    monkeypatch.setattr(d.subprocess, "run", lambda cmd, check: calls.append(cmd))
    d.request_rebuild(REPO, 4)
    assert calls == [["gh", "workflow", "run", "logmig-progress.yml", "-R", REPO, "-f", "issue=4"]]
    wf, on = workflow("logmig-progress.yml")
    assert "workflow_dispatch" in on and "inputs.issue" in wf["concurrency"]["group"]
    for name in ("logmig-run.yml", "logmig-stop.yml"):
        assert workflow(name)[0]["permissions"]["actions"] == "write"


def test_skip_list_wins_over_everything_and_shows_owner():
    skip = {"legacy_edi": {"owner": "EDI team", "reason": "owned by EDI"}}
    decisions = d.plan(["legacy_edi", "quotes"], {"legacy_edi", "quotes"}, [], {}, {}, skip_list=skip)
    assert decisions == [("legacy_edi", "skip", "skip list (owner: EDI team): owned by EDI"), ("quotes", "start", "")]


def test_repo_skip_list_has_legacy_edi_with_owner_and_reason():
    entry = d.load_skip_list()["legacy_edi"]
    assert "EDI" in entry["owner"] and entry["reason"]


def test_skip_list_entries_need_owner_reason_and_known_service(tmp_path):
    bad = tmp_path / "skip.yml"
    for text in ("quotes:\n  reason: x\n", "quotes:\n  owner: y\n", "nope:\n  owner: y\n  reason: x\n"):
        bad.write_text(text)
        with pytest.raises(SystemExit):
            d.load_skip_list(bad, known=["quotes"])


def test_dispatch_workflows_install_requirements():
    for name in ("logmig-run.yml", "logmig-stop.yml"):
        steps = next(iter(workflow(name)[0]["jobs"].values()))["steps"]
        assert any(s.get("run") == "pip install -r requirements-dev.txt" for s in steps), name


def row(svc, status, pr=""):
    return {f"harbor-lane/{svc}": ({"id": 7}, [f"harbor-lane/{svc}", status, pr, "PASS" if pr else "", "[session](u)"])}


class RunningDevin(FakeDevin):
    def __init__(self, *services):
        super().__init__()
        self.services, self.terminated = services, []

    def sessions(self, tags):
        return [{"session_id": f"devin-{s}", "status": "running", "url": f"https://app.devin.ai/sessions/{s}",
                 "tags": ["logmig", "logmig-harbor-lane", f"logmig-harbor-lane-{s}"]} for s in self.services]

    def terminate(self, session_id):
        self.terminated.append(session_id)


@pytest.mark.parametrize("rows,titles", [
    (row("payments", "PR open", "arunbalaji2019/harbor-lane#11"), ["[logmig] payments: move to harbor_obs"]),
    (row("payments", "in progress"), ["[logmig] payments: move to harbor_obs"]),
    (row("payments", "needs human: Finance sign-off"), []),
    (row("payments", "nothing to do"), []),
    (row("payments", "merged", "#12"), []),
])
def test_stop_keeps_rows_that_have_a_pr_or_a_final_status(no_github, monkeypatch, rows, titles):
    monkeypatch.setattr(d, "open_pr_titles", lambda repo: titles)
    devin, issue = RunningDevin("payments"), FakeIssue(rows=rows)
    assert d.stop(args(services="payments"), REPO, devin, issue) == 0
    assert devin.terminated == ["devin-payments"]
    assert issue.writes == []


@pytest.mark.parametrize("rows", [{}, row("payments", "in progress"), row("payments", "in progress (starting)")])
def test_stop_marks_unfinished_sessions_stopped(no_github, rows):
    devin, issue = RunningDevin("payments"), FakeIssue(rows=rows)
    assert d.stop(args(services="payments"), REPO, devin, issue) == 0
    assert devin.terminated == ["devin-payments"]
    assert len(issue.writes) == 1 and "| harbor-lane/payments | stopped |  |" in issue.writes[0]


def test_stop_dry_run_terminates_nothing(no_github):
    devin, issue = RunningDevin("payments"), FakeIssue(rows=row("payments", "in progress"))
    assert d.stop(args(services="payments", dry_run=True), REPO, devin, issue) == 0
    assert devin.terminated == [] and issue.writes == []


def test_run_restarts_a_stopped_service_without_a_pr(no_github, monkeypatch):
    monkeypatch.setattr(d, "still_uses_hl_log", lambda svc: True)
    devin, issue = FakeDevin(), FakeIssue(rows=row("quotes", "stopped"))
    assert d.run(args(services="quotes"), REPO, devin, issue) == 0
    assert len(devin.created) == 1 and "| harbor-lane/quotes | in progress |" in issue.writes[-1]


def test_run_does_not_restart_a_stopped_service_with_an_open_pr(no_github, monkeypatch):
    monkeypatch.setattr(d, "still_uses_hl_log", lambda svc: True)
    monkeypatch.setattr(d, "open_pr_titles", lambda repo: ["[logmig] quotes: move to harbor_obs"])
    devin = FakeDevin()
    assert d.run(args(services="quotes"), REPO, devin, FakeIssue(rows=row("quotes", "stopped", "#13"))) == 0
    assert devin.created == []
