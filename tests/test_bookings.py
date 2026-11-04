from services.bookings import app


def test_booking_confirmed():
    app._booked.clear()
    assert app.book("r1", "FXT-RTM", 1) == {"lane": "FXT-RTM", "pallets": 1}


def test_no_capacity_returns_none():
    app._booked.clear()
    assert app.book("r2", "SOU-ZEE", 1) is None


def _lines(capsys):
    import json

    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_booking_confirmed_log_line(capsys):
    app._booked.clear()
    app.book("r3", "FXT-RTM", 2)
    [line] = _lines(capsys)
    assert line["level"] == "info"
    assert line["service"] == "bookings"
    assert line["event"] == "booking_confirmed"
    assert line["request_id"] == "r3"
    assert (line["lane"], line["pallets"]) == ("FXT-RTM", 2)


def test_no_capacity_log_line(capsys):
    app._booked.clear()
    app.book("r4", "SOU-ZEE", 1)
    [line] = _lines(capsys)
    assert line["level"] == "warning"
    assert line["event"] == "lane_no_capacity"
    assert line["request_id"] == "r4"
    assert (line["lane"], line["wanted"], line["free"]) == ("SOU-ZEE", 1, 0)


def test_request_id_does_not_leak_between_calls(capsys):
    app._booked.clear()
    app.book("r5", "FXT-RTM", 1)
    app.book("r6", "SOU-ZEE", 1)
    assert [line["request_id"] for line in _lines(capsys)] == ["r5", "r6"]
