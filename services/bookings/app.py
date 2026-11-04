from harbor_obs import bind_request_id, get_logger

SERVICE = "bookings"
CAPACITY = {"FXT-RTM": 2, "SOU-ZEE": 0}
_booked = {}

log = get_logger(SERVICE)


def book(request_id, lane, pallets):
    bind_request_id(request_id)
    free = CAPACITY.get(lane, 0) - _booked.get(lane, 0)
    if free < pallets:
        log.warning("lane_no_capacity", lane=lane, wanted=pallets, free=free)
        return None
    _booked[lane] = _booked.get(lane, 0) + pallets
    log.info("booking_confirmed", lane=lane, pallets=pallets)
    return {"lane": lane, "pallets": pallets}
