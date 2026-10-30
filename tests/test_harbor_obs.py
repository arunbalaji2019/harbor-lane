import json

from harbor_obs import bind_request_id, get_logger, redact


def test_json_line(capsys):
    bind_request_id("r9")
    get_logger("demo").warning("thing_happened", n=2)
    line = json.loads(capsys.readouterr().out.strip())
    assert line["service"] == "demo"
    assert line["level"] == "warning"
    assert line["event"] == "thing_happened"
    assert line["request_id"] == "r9"
    assert line["n"] == 2


def test_redact():
    assert redact("to ana@example.com") == "to [redacted-email]"
