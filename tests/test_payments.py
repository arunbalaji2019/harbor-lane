from services.payments.app import charge


def test_charge_ok():
    assert charge("r1", "O1", 120.0) is True


def test_charge_declined():
    assert charge("r2", "O2", 50.0, card_ok=False) is False


def _lines(capsys):
    import json

    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_order_paid_log_line(capsys):
    charge("r3", "O3", 120.0)
    [line] = _lines(capsys)
    assert line["level"] == "info"
    assert line["service"] == "payments"
    assert line["event"] == "order_paid"
    assert line["request_id"] == "r3"
    assert (line["order_id"], line["amount"]) == ("O3", 120.0)


def test_payment_declined_log_line(capsys):
    charge("r4", "O4", 50.0, card_ok=False)
    [line] = _lines(capsys)
    assert line["level"] == "error"
    assert line["service"] == "payments"
    assert line["event"] == "payment_declined"
    assert line["request_id"] == "r4"
    assert (line["order_id"], line["reason"]) == ("O4", "card_refused")


def test_request_id_does_not_leak_between_calls(capsys):
    charge("r5", "O5", 10.0)
    charge("r6", "O6", 20.0, card_ok=False)
    assert [line["request_id"] for line in _lines(capsys)] == ["r5", "r6"]
