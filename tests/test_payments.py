from services.payments.app import charge


def test_charge_ok():
    assert charge("r1", "O1", 120.0) is True


def test_charge_declined():
    assert charge("r2", "O2", 50.0, card_ok=False) is False
