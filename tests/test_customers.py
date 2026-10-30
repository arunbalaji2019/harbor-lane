from services.customers.app import update_contact


def test_update_contact():
    assert update_contact("C1", "ana@example.com", "+44 7700 900123")["phone"] == "+44 7700 900123"
