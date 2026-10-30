from services.quotes.app import create_quote


def test_quote_price_and_log(capsys):
    q = create_quote("Q1", "FXT", "RTM", 100)
    assert q["price"] == 185.0
    assert "quote created id=Q1" in capsys.readouterr().out
