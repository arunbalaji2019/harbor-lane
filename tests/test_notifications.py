import json

from services.notifications.app import send_delivery_email


def _lines(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_send():
    assert send_delivery_email("r1", "ana@example.com", "S9") is True


def test_delivery_email_sent_log_line(capsys):
    send_delivery_email("r2", "ana@example.com", "S9")
    [line] = _lines(capsys)
    assert line["level"] == "info"
    assert line["service"] == "notifications"
    assert line["event"] == "delivery_email_sent"
    assert line["request_id"] == "r2"
    assert line["shipment_id"] == "S9"
    assert "ana@example.com" not in json.dumps(line)


def test_request_id_does_not_leak_between_calls(capsys):
    send_delivery_email("r3", "ana@example.com", "S1")
    send_delivery_email("r4", "bo@example.com", "S2")
    assert [line["request_id"] for line in _lines(capsys)] == ["r3", "r4"]
