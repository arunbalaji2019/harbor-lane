from services.invoicing.app import issue_invoice


def test_invoice_total(tmp_path, monkeypatch):
    monkeypatch.setenv("HL_AUDIT_PATH", str(tmp_path / "audit.log"))
    assert issue_invoice("I1", "C1", 100.0)["total"] == 120.0
