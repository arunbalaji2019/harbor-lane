from services.tracking.app import check_feed


def test_feed_ok():
    assert check_feed(3) == "ok"


def test_feed_stale():
    assert check_feed(40) == "stale"


def _lines(capsys):
    import json

    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_feed_ok_log_line(capsys):
    check_feed(3)
    [line] = _lines(capsys)
    assert line["level"] == "info"
    assert line["service"] == "tracking"
    assert line["event"] == "feed_ok"


def test_feed_stale_log_line(capsys):
    check_feed(40)
    [line] = _lines(capsys)
    assert line["level"] == "warning"
    assert line["service"] == "tracking"
    assert line["event"] == "feed_stale"
    assert line["minutes_since_update"] == 40
