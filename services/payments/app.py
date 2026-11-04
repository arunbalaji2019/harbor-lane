from harbor_obs import bind_request_id, get_logger

SERVICE = "payments"

log = get_logger(SERVICE)


def charge(request_id, order_id, amount, card_ok=True):
    bind_request_id(request_id)
    if not card_ok:
        log.error("payment_declined", order_id=order_id, reason="card_refused")
        return False
    log.info("order_paid", order_id=order_id, amount=amount)
    return True
