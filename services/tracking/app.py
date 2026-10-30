import hl_log

SERVICE = "tracking"
STALE_AFTER_MIN = 15


def check_feed(minutes_since_update):
    if minutes_since_update > STALE_AFTER_MIN:
        hl_log.warn(SERVICE, f"tracking feed stale for {minutes_since_update} minutes")
        return "stale"
    hl_log.info(SERVICE, "tracking feed ok")
    return "ok"
