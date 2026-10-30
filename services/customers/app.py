import hl_log

SERVICE = "customers"
_db = {}


def update_contact(customer_id, email, phone):
    _db[customer_id] = {"email": email, "phone": phone}
    hl_log.info(SERVICE, f"customer {customer_id} contact updated email={email} phone={phone}")
    return _db[customer_id]
