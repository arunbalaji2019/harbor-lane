import hl_log

SERVICE = "bookings"
CAPACITY = {"FXT-RTM": 2, "SOU-ZEE": 0}
_booked = {}


def book(request_id, lane, pallets):
    hl_log.set_request(request_id)
    free = CAPACITY.get(lane, 0) - _booked.get(lane, 0)
    if free < pallets:
        hl_log.warn(SERVICE, f"no capacity on lane {lane} (wanted {pallets}, free {free})")
        return None
    _booked[lane] = _booked.get(lane, 0) + pallets
    hl_log.info(SERVICE, f"booking confirmed lane={lane} pallets={pallets}")
    return {"lane": lane, "pallets": pallets}
