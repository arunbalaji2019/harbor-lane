from harbor_obs import get_logger

SERVICE = "tracking"
STALE_AFTER_MIN = 15

log = get_logger(SERVICE)


def check_feed(minutes_since_update):
    if minutes_since_update > STALE_AFTER_MIN:
        log.warning("feed_stale", minutes_since_update=minutes_since_update)
        return "stale"
    log.info("feed_ok")
    return "ok"
