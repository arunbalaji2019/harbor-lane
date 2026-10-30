# harbor-lane

Backend services for Harbor Lane Freight: quotes, bookings, payments, shipment tracking, notifications, invoicing, customer records, and the EDI bridge to customs brokers.

Each service lives in `services/<name>/`. Logging today goes through `hl_log`, our 2017 logger. We're moving every service to structured JSON logs (`harbor_obs`) so the new log pipeline can index them. See `docs/LOGGING_STANDARD.md`.

## Run the tests

    pip install -r requirements-dev.txt
    pytest -q

Python 3.11.
