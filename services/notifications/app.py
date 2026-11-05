from harbor_obs import bind_request_id, get_logger

SERVICE = "notifications"
log = get_logger(SERVICE)


def send_delivery_email(request_id, email, shipment_id):
    bind_request_id(request_id)
    # (provider call omitted in this repo)
    log.info("delivery_email_sent", shipment_id=shipment_id)
    return True
