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
