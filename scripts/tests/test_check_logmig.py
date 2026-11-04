"""Tests for scripts/check_logmig.py, run against a throwaway git repo per test.

Each regression test builds a base revision that logs with hl_log, applies one faulty
migration on top, and asserts the checker fails with the expected reason.
"""
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "scripts" / "check_logmig.py"

BASE_APP = '''
import hl_log

SERVICE = "svc"


def run(rid, lane, n):
    hl_log.set_request(rid)
    hl_log.info(SERVICE, f"job started lane={lane} size={n}")
    if n > 2:
        for _ in range(n):
            hl_log.warn(SERVICE, f"lane full {lane} wanted={n}")
        return None
    hl_log.info(SERVICE, f"job done lane={lane} size={n}")
    return n
'''

GOOD_APP = '''
from harbor_obs import bind_request_id, get_logger

SERVICE = "svc"
log = get_logger(SERVICE)


def run(rid, lane, n):
    bind_request_id(rid)
    log.info("job_started", lane=lane, size=n)
    if n > 2:
        for _ in range(n):
            log.warning("lane_full", lane=lane, wanted=n)
        return None
    log.info("job_done", lane=lane, size=n)
    return n
'''

TESTS = '''
from services.svc import app


def test_ok():
    assert app.run("r1", "LA", 1) == 1


def test_full():
    assert app.run("r2", "LB", 3) is None
'''

BASE_RULES = '''
- name: LaneFull
  match: "lane full"
  threshold: 3 in 5m
  page: ops
'''

JSON_RULE = '''
- name: LaneFullJson
  match: '"service": "svc", "event": "lane_full"'
  threshold: 3 in 5m
  page: ops
'''


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                   cwd=cwd, check=True, capture_output=True)


def write(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text).lstrip("\n"))


@pytest.fixture
def make_repo(tmp_path):
    def _make(head, base=None):
        root = tmp_path / "repo"
        root.mkdir()
        for pkg in ("hl_log", "harbor_obs"):
            shutil.copytree(REPO / pkg, root / pkg, ignore=shutil.ignore_patterns("__pycache__"))
        write(root, {
            "pyproject.toml": '[tool.pytest.ini_options]\npythonpath = ["."]\ntestpaths = ["tests"]\n',
            "services/__init__.py": "",
            "services/svc/__init__.py": "",
            "services/svc/app.py": BASE_APP,
            "tests/test_svc.py": TESTS,
            "alerts/rules.yaml": BASE_RULES,
            **(base or {}),
        })
        git(root, "init", "-q", "-b", "main")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "base")
        git(root, "checkout", "-q", "-b", "migrate")
        write(root, {"services/svc/app.py": GOOD_APP, "alerts/rules.yaml": BASE_RULES + JSON_RULE, **head})
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "migrate")
        return root
    return _make


def check(root):
    res = subprocess.run([sys.executable, str(CHECKER), "svc", "--base", "main"],
                         cwd=root, capture_output=True, text=True)
    return res.returncode, res.stdout + res.stderr


def assert_fails(root, *expected):
    code, out = check(root)
    assert code == 1, out
    for text in expected:
        assert text in out, out


def test_good_migration_passes(make_repo):
    code, out = check(make_repo({}))
    assert code == 0, out


def test_plain_text_line_from_the_service_fails(make_repo):
    app = GOOD_APP + '''

import logging
import harbor_obs

_plain = logging.getLogger("svc.plain")
_handler = harbor_obs._StdoutHandler()
_handler.setFormatter(logging.Formatter("%(message)s"))
_plain.addHandler(_handler)
_plain.propagate = False


def run_plain(rid, lane, n):
    result = run(rid, lane, n)
    _plain.log(logging.WARNING, "lane full %s", lane)
    return result
'''
    tests = TESTS.replace('app.run("r2", "LB", 3)', 'app.run_plain("r2", "LB", 3)')
    assert_fails(make_repo({"services/svc/app.py": app, "tests/test_svc.py": tests}), "not JSON")


def test_removed_baseline_test_fails(make_repo):
    app = GOOD_APP.replace('"lane_full"', '"lane_is_full"')
    tests = TESTS.replace("def test_full", "def test_full_renamed")
    assert_fails(make_repo({"services/svc/app.py": app, "tests/test_svc.py": tests}),
                 "tests/test_svc.py::test_full", "no longer runs")


def test_changed_threshold_on_replacement_rule_fails(make_repo):
    rules = BASE_RULES + JSON_RULE.replace("threshold: 3 in 5m", "threshold: 30 in 5m")
    assert_fails(make_repo({"alerts/rules.yaml": rules}), "LaneFullJson", "threshold")


def test_changed_page_on_replacement_rule_fails(make_repo):
    rules = BASE_RULES + JSON_RULE.replace("page: ops", "page: payments-oncall")
    assert_fails(make_repo({"alerts/rules.yaml": rules}), "LaneFullJson", "page")


def test_fewer_alerting_lines_fails(make_repo):
    app = GOOD_APP.replace("for _ in range(n):\n            log.warning", "log.warning")
    app = app.replace('\n        return None', '\n        return None', 1)
    assert "for _ in range(n)" not in app
    assert_fails(make_repo({"services/svc/app.py": app}), "LaneFull", "3 time(s) before but 1 after")


def test_failing_base_tests_fail_the_check(make_repo):
    broken_tests = "import module_that_does_not_exist\n" + TESTS
    root = make_repo({"alerts/rules.yaml": BASE_RULES}, base={"tests/test_svc.py": broken_tests})
    # head fixes the test file but adds no JSON rule, so the page silently disappears
    write(root, {"tests/test_svc.py": TESTS})
    git(root, "commit", "-qam", "fix tests")
    assert_fails(root, "baseline", "pytest failed on the base revision")


def test_value_masked_by_another_event_fails(make_repo):
    app = GOOD_APP.replace('log.warning("lane_full", lane=lane, wanted=n)', 'log.warning("lane_full", lane=lane)')
    assert_fails(make_repo({"services/svc/app.py": app}), "nothing lost", "lane full LB wanted=3")


def test_nested_personal_data_fails(make_repo):
    app = GOOD_APP.replace('log.info("job_done", lane=lane, size=n)',
                           'log.info("job_done", lane=lane, size=n, contact={"email": "ops@harbor.example"})')
    assert_fails(make_repo({"services/svc/app.py": app}), "personal data", "contact.email")


def test_reports_redact_personal_data(make_repo):
    app = GOOD_APP.replace('log.info("job_done", lane=lane, size=n)',
                           'log.info("job_done", lane=lane, size=n, note="call +44 20 7946 0958 or ops@harbor.example")')
    code, out = check(make_repo({"services/svc/app.py": app}))
    assert code == 1 and "personal data" in out, out
    assert "ops@harbor.example" not in out and "7946 0958" not in out, out


def test_lowercase_value_dropped_from_a_line_fails(make_repo):
    tests = TESTS.replace('"LA"', '"atlanta"').replace('"LB"', '"boston"')
    app = GOOD_APP.replace('log.info("job_started", lane=lane, size=n)', 'log.info("job_started", size=n)')
    root = make_repo({"services/svc/app.py": app, "tests/test_svc.py": tests}, base={"tests/test_svc.py": tests})
    assert_fails(root, "nothing lost", "atlanta")


def test_line_matching_old_and_json_rule_fails(make_repo):
    app = GOOD_APP.replace('log.warning("lane_full", lane=lane, wanted=n)',
                           'log.warning("lane_full", lane=lane, wanted=n, detail="lane full")')
    assert_fails(make_repo({"services/svc/app.py": app}), "LaneFull fired 3 time(s) before but 6 after", "false page")


AUDIT_TESTS = ("import os\nimport tempfile\n\n"
               "os.environ['HL_AUDIT_PATH'] = os.path.join(tempfile.mkdtemp(), 'audit.log')\n" + TESTS)


def test_dropped_audit_record_fails(make_repo):
    base_app = BASE_APP.replace('    return n\n', '    hl_log.audit(SERVICE, "job_done", lane=lane, size=n)\n    return n\n')
    root = make_repo({}, base={"services/svc/app.py": base_app, "tests/test_svc.py": AUDIT_TESTS})
    assert_fails(root, "audit:", "tests/test_svc.py::test_ok")


def test_background_line_without_request_id_passes(make_repo):
    base_app = BASE_APP + '''

def poll(lane):
    hl_log.info(SERVICE, f"lane polled lane={lane}")
'''
    head_app = GOOD_APP + '''

def poll(lane):
    log.info("lane_polled", lane=lane)
'''
    tests = TESTS.replace("def test_ok", 'def test_poll():\n    app.poll("LC")\n\n\ndef test_ok')
    root = make_repo({"services/svc/app.py": head_app, "tests/test_svc.py": tests},
                     base={"services/svc/app.py": base_app, "tests/test_svc.py": tests})
    code, out = check(root)
    assert code == 0, out


def test_plain_text_line_from_a_shared_helper_fails(make_repo):
    helper = '''
import logging
import harbor_obs

_plain = logging.getLogger("common.plain")
_handler = harbor_obs._StdoutHandler()
_handler.setFormatter(logging.Formatter("%(message)s"))
_plain.addHandler(_handler)
_plain.propagate = False


def note(text):
    _plain.log(logging.WARNING, text)
'''
    app = GOOD_APP.replace("from harbor_obs import bind_request_id, get_logger",
                           "from common.plainlog import note\nfrom harbor_obs import bind_request_id, get_logger")
    app = app.replace("        return None\n", "        note('lane full')\n        return None\n")
    files = {"common/__init__.py": "", "common/plainlog.py": helper, "services/svc/app.py": app}
    assert_fails(make_repo(files), "not JSON")


def test_quoted_old_value_passes(make_repo):
    base_app = BASE_APP.replace('f"job started lane={lane} size={n}"', 'f\'job started lane="{lane}" size={n}\'')
    code, out = check(make_repo({}, base={"services/svc/app.py": base_app}))
    assert code == 0, out
