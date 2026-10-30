from services.notifications.app import send_delivery_email


def test_send():
    assert send_delivery_email("r1", "ana@example.com", "S9") is True
