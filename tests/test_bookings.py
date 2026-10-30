from services.bookings import app


def test_booking_confirmed():
    app._booked.clear()
    assert app.book("r1", "FXT-RTM", 1) == {"lane": "FXT-RTM", "pallets": 1}


def test_no_capacity_returns_none():
    app._booked.clear()
    assert app.book("r2", "SOU-ZEE", 1) is None
