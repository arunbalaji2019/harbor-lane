from services.tracking.app import check_feed


def test_feed_ok():
    assert check_feed(3) == "ok"


def test_feed_stale():
    assert check_feed(40) == "stale"
