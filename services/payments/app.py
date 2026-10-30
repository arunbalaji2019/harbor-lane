import hl_log

SERVICE = "payments"


def charge(request_id, order_id, amount, card_ok=True):
    hl_log.set_request(request_id)
    if not card_ok:
        hl_log.error(SERVICE, f"payment declined for order {order_id}: card_refused")
        return False
    hl_log.info(SERVICE, f"order {order_id} paid amount={amount}")
    return True
