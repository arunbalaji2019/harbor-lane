import hl_log

SERVICE = "quotes"
RATE_PER_KM = 1.85


def create_quote(quote_id, origin, destination, km):
    price = round(km * RATE_PER_KM, 2)
    hl_log.info(SERVICE, f"quote created id={quote_id} {origin}->{destination} price={price}")
    return {"id": quote_id, "price": price}
