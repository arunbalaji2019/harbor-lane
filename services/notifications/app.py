import hl_log

SERVICE = "notifications"


def send_delivery_email(request_id, email, shipment_id):
    hl_log.set_request(request_id)
    # (provider call omitted in this repo)
    hl_log.info(SERVICE, f"sent delivery email to {email} for shipment {shipment_id}")
    return True
