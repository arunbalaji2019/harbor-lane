"""pytest plugin used by check_logmig.py: records every hl_log and harbor_obs line per test.

Loaded with `-p logmig_capture`; writes JSON lines to the file named by $LOGMIG_CAPTURE.
Each log entry carries `stack`, the repo-relative files on the call stack (innermost first;
`caller` is the first), so the checker can attribute lines to a service even when they aren't
valid JSON or come from a shared helper. `hl_log.audit()` calls are recorded as
`{"kind": "audit"}` and test outcomes as `{"kind": "test"}` entries. hl_log entries also carry
`rid_set_by`, the stack of the hl_log.set_request() call that set their request id. Request
context (hl_log's thread-local, harbor_obs's contextvar) is reset before every test.
"""
import json
import os
import sys
from pathlib import Path

_current = {"test": None}
_rid_setter = {"stack": None}
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


def _where():
    stack, frame = [], sys._getframe(1)
    while frame is not None:
        path = Path(frame.f_code.co_filename).resolve()
        if path != Path(__file__).resolve():
            try:
                rel = path.relative_to(_root)
            except ValueError:
                rel = None
            if rel is not None and rel.parts and rel.parts[0] not in _SKIP_DIRS:
                stack.append(rel.as_posix())
        frame = frame.f_back
    return {"caller": stack[0] if stack else None, "stack": stack}


def _patch_hl_log():
    try:
        import hl_log
    except ImportError:
        return
    original = hl_log._emit

    def _emit(level, service, msg):
        rid = getattr(hl_log._ctx, "request_id", None)
        _record({"kind": "hl_log", "level": level, "service": service, "rid": rid, "msg": msg,
                 "rid_set_by": _rid_setter["stack"] or [], **_where(),
                 "line": f"{hl_log._ts()} [{level}] {service} rid={rid or '-'} {msg}"})
        original(level, service, msg)

    original_audit = hl_log.audit

    def audit(service, action, **fields):
        _record({"kind": "audit", "service": service, "action": action,
                 "fields": {k: str(v) for k, v in sorted(fields.items())}, **_where()})
        return original_audit(service, action, **fields)

    original_set_request = hl_log.set_request

    def set_request(request_id):
        _rid_setter["stack"] = _where()["stack"]
        return original_set_request(request_id)

    hl_log._emit = _emit
    hl_log.audit = audit
    hl_log.set_request = set_request


def _reset_request_context():
    _rid_setter["stack"] = None
    if "hl_log" in sys.modules:
        sys.modules["hl_log"]._ctx.__dict__.pop("request_id", None)
    if "harbor_obs" in sys.modules:
        sys.modules["harbor_obs"]._request_id.set(None)


def _patch_harbor_obs():
    try:
        import harbor_obs
    except ImportError:
        return
    original = harbor_obs._StdoutHandler.emit

    def emit(self, record):
        _record({"kind": "harbor_obs", "logger": record.name, **_where(),
                 "line": self.format(record)})
        original(self, record)

    harbor_obs._StdoutHandler.emit = emit


def pytest_configure(config):
    global _root
    _root = Path(config.rootpath).resolve()
    _patch_hl_log()
    _patch_harbor_obs()


def pytest_runtest_setup(item):
    _reset_request_context()
    _current["test"] = item.nodeid


def pytest_runtest_teardown(item):
    _current["test"] = None


def pytest_runtest_logreport(report):
    if report.when == "call" or report.outcome != "passed":
        _record({"kind": "test", "test": report.nodeid, "when": report.when, "outcome": report.outcome})
