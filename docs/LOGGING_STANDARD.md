# Logging standard (v2)

Owner: Tomasz (Observability). Approved 2026-09.

All application logs move from `hl_log` to `harbor_obs`, which writes one JSON object per line. The new log pipeline indexes these fields, and dashboards are being rebuilt on them.

## Required on every line

| Field | Meaning |
|---|---|
| `ts` | UTC timestamp (added by harbor_obs) |
| `level` | `info`, `warning` or `error` |
| `service` | the service name, for example `payments` |
| `event` | a short snake_case name for what happened, for example `order_paid` |
| `request_id` | set with `bind_request_id()` for anything that runs inside a request |

Put other details in fields, not in the event name: `log.info("order_paid", order_id=oid, amount=amt)`.

## Mapping from hl_log

| hl_log | harbor_obs |
|---|---|
| `hl_log.info(SERVICE, msg)` | `log.info("<event>", **fields)` |
| `hl_log.warn(SERVICE, msg)` | `log.warning("<event>", **fields)` |
| `hl_log.error(SERVICE, msg)` | `log.error("<event>", **fields)` |
| `hl_log.set_request(rid)` | `bind_request_id(rid)` |

## Done means

- No `hl_log` imports left in the service.
- Tests pass.
- A sample of the service's log lines parses as JSON with all required fields.
