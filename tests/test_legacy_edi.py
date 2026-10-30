from services.legacy_edi.app import send_manifest


def test_send_manifest():
    assert send_manifest("M1", 3) is True
