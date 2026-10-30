"""hl_log: Harbor Lane's original logger (2017).

Deprecated for application logs. New code uses harbor_obs (see docs/LOGGING_STANDARD.md).
"""
import datetime
import os
import sys
import threading

_ctx = threading.local()


def _ts():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_request(request_id):
    """Attach a request id to every line this thread logs until the next call."""
    _ctx.request_id = request_id


def _emit(level, service, msg):
    rid = getattr(_ctx, "request_id", None) or "-"
    sys.stdout.write(f"{_ts()} [{level}] {service} rid={rid} {msg}\n")


def info(service, msg):
    _emit("INFO", service, msg)


def warn(service, msg):
    _emit("WARN", service, msg)


def error(service, msg):
    _emit("ERROR", service, msg)


def audit(service, action, **fields):
    """Append one line to the audit trail. See docs/AUDIT.md before changing anything here."""
    path = os.environ.get("HL_AUDIT_PATH", "audit.log")
    body = "|".join(f"{k}={v}" for k, v in sorted(fields.items()))
    with open(path, "a") as f:
        f.write(f"{_ts()}|{service}|{action}|{body}\n")
