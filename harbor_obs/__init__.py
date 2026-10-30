"""harbor_obs: structured JSON logging for the new log pipeline.

Usage:
    from harbor_obs import get_logger, bind_request_id
    log = get_logger("payments")
    bind_request_id(request_id)
    log.info("order_paid", order_id=oid, amount=amt)

See docs/LOGGING_STANDARD.md.
"""
import contextvars
import datetime
import json
import logging
import re
import sys

_request_id = contextvars.ContextVar("request_id", default=None)

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def bind_request_id(request_id):
    _request_id.set(request_id)


def redact(value):
    """Mask email addresses in a string."""
    return EMAIL.sub("[redacted-email]", str(value))


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        out = {
            "ts": datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "level": record.levelname.lower(),
            "service": record.name.split(".", 1)[-1],
            "event": record.getMessage(),
            "request_id": _request_id.get(),
        }
        out.update(getattr(record, "fields", {}))
        return json.dumps(out, default=str)


class _StdoutHandler(logging.Handler):
    def emit(self, record):
        sys.stdout.write(self.format(record) + "\n")


class _Logger:
    def __init__(self, logger):
        self._logger = logger

    def _log(self, level, event, fields):
        self._logger.log(level, event, extra={"fields": fields})

    def info(self, event, **fields):
        self._log(logging.INFO, event, fields)

    def warning(self, event, **fields):
        self._log(logging.WARNING, event, fields)

    def error(self, event, **fields):
        self._log(logging.ERROR, event, fields)


def get_logger(service):
    logger = logging.getLogger(f"harbor.{service}")
    if not logger.handlers:
        handler = _StdoutHandler()
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return _Logger(logger)
