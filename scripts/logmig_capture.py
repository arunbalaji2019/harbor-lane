"""pytest plugin used by check_logmig.py: records every hl_log and harbor_obs line per test.

Loaded with `-p logmig_capture`; writes JSON lines to the file named by $LOGMIG_CAPTURE.
Each log entry carries `caller`, the repo-relative file that made the logging call, so the
checker can attribute lines to a service even when they aren't valid JSON. Test outcomes are
recorded as `{"kind": "test"}` entries.
"""
import json
import os
import sys
from pathlib import Path

_current = {"test": None}
_out = None
_root = None
_SKIP_DIRS = ("hl_log", "harbor_obs")


def _record(entry):
    global _out
    if _out is None:
        _out = open(os.environ["LOGMIG_CAPTURE"], "a")
    entry.setdefault("test", _current["test"])
    _out.write(json.dumps(entry, default=str) + "\n")
    _out.flush()


def _caller():
    frame = sys._getframe(2)
    while frame is not None:
        path = Path(frame.f_code.co_filename).resolve()
        if path != Path(__file__).resolve():
            try:
                rel = path.relative_to(_root)
            except ValueError:
                rel = None
            if rel is not None and rel.parts and rel.parts[0] not in _SKIP_DIRS:
                return rel.as_posix()
        frame = frame.f_back
    return None


def _patch_hl_log():
    try:
        import hl_log
    except ImportError:
        return
    original = hl_log._emit

    def _emit(level, service, msg):
        rid = getattr(hl_log._ctx, "request_id", None)
        _record({"kind": "hl_log", "level": level, "service": service, "rid": rid, "msg": msg,
                 "caller": _caller(),
                 "line": f"{hl_log._ts()} [{level}] {service} rid={rid or '-'} {msg}"})
        original(level, service, msg)

    hl_log._emit = _emit


def _patch_harbor_obs():
    try:
        import harbor_obs
    except ImportError:
        return
    original = harbor_obs._StdoutHandler.emit

    def emit(self, record):
        _record({"kind": "harbor_obs", "logger": record.name, "caller": _caller(),
                 "line": self.format(record)})
        original(self, record)

    harbor_obs._StdoutHandler.emit = emit


def pytest_configure(config):
    global _root
    _root = Path(config.rootpath).resolve()
    _patch_hl_log()
    _patch_harbor_obs()


def pytest_runtest_setup(item):
    _current["test"] = item.nodeid


def pytest_runtest_teardown(item):
    _current["test"] = None


def pytest_runtest_logreport(report):
    if report.when == "call" or report.outcome != "passed":
        _record({"kind": "test", "test": report.nodeid, "when": report.when, "outcome": report.outcome})
