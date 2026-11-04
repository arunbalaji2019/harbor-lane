---
name: logmig
description: Migrate one service from hl_log to harbor_obs per docs/LOGGING_STANDARD.md, prove it with scripts/check_logmig.py (standard, personal data, alert replay), open one [logmig] PR and report a structured result. Use for any "[logmig]" / hl_log migration task, in harbor-lane or any other Harbor Lane repo.
---

# logmig: move one service from hl_log to harbor_obs

Input: a repo and ONE service name (the dispatcher starts one session per service).
Output: one PR, or a `needs human` result. Runs unattended: never ask for approval
(commit messages included). Read `AGENTS.md` first; its rules override this file.

## 0. Preconditions (stop with `needs human` if any fail)
- Python 3.11. `pip install -r requirements-dev.txt` and `pytest -q` pass on `origin/main`.
- The repo's setup PR, `[logmig] setup: checker and CI`, has merged into the default branch. Every
  repo needs it once, before any service PR. It adds `scripts/check_logmig.py`,
  `scripts/logmig_capture.py`, `scripts/tests/`, PyYAML in `requirements-dev.txt`, and the
  `logmig-check` CI job; harbor-lane's is #3, so copy those files from there. If they're missing,
  the reason is `repo not bootstrapped for logmig: needs the [logmig] setup PR`. Never add them
  in a service PR, because parallel sessions would conflict.
- There is no open PR whose title starts with `[logmig] <service>:`. If there is one, report
  `status: already_open` with its URL and stop.

## 1. Triage: is this service a PR or a human decision?
Grep `services/<service>/` for `hl_log` and classify the service before editing anything.

| Finding | Action |
|---|---|
| Path is owned by another team in CODEOWNERS (e.g. `services/legacy_edi/`) | Don't edit. Open an issue for that team titled `[logmig] <service>: please migrate to harbor_obs`, then report `needs_human` with the reason `owned by <team>` |
| Uses `hl_log.audit()` | Report `needs_human` with the reason `Finance sign-off: LOGGING_STANDARD requires no hl_log imports, AUDIT.md requires audit() unchanged`. Don't touch audit calls |
| A log line contains personal data and no id is available to log instead | Report `needs_human` with the reason `no id available to replace <field>` |
| No `hl_log` usage | Report `status: nothing_to_do` |
| Otherwise | Continue |

## 2. Rewrite the service
Follow the mapping in `docs/LOGGING_STANDARD.md`:
```python
from harbor_obs import bind_request_id, get_logger
log = get_logger(SERVICE)                 # module level, SERVICE is the existing constant
hl_log.set_request(rid)   -> bind_request_id(rid)
hl_log.info(SERVICE, msg) -> log.info("<event>", **fields)
hl_log.warn(SERVICE, msg) -> log.warning("<event>", **fields)
hl_log.error(SERVICE, msg)-> log.error("<event>", **fields)
```
- `event` is a fixed, short snake_case string literal, such as `booking_confirmed`. Never use an
  f-string. Name the event after what happened, not after a value.
- Every value in the old message becomes a field with a clear key. The checker compares ids and
  numbers between the old and new lines.
  Example: `f"no capacity on lane {lane} (wanted {pallets}, free {free})"` becomes
  `log.warning("lane_no_capacity", lane=lane, wanted=pallets, free=free)`.
- Personal data (email, phone, name) is dropped, or replaced by the id the function already has
  (e.g. `customer_id`). Never pass it to `redact()` and log the result.
- Keep behaviour and return values identical. Only logging changes.
- If the old code called `set_request`, keep `bind_request_id` at the same point.

## 3. Alerts: the trap tests won't catch
`alerts/rules.yaml` matches each raw line by case-insensitive substring. Old phrases such as
`no capacity on lane` don't appear in JSON lines, so a correct migration silently stops paging.
For every rule whose `match` appears in one of this service's old lines:
- Keep the old rule unchanged. Old builds are still running during the deploy.
- Add `<RuleName>Json` directly after it, with the same `threshold` and `page`, matching the
  service plus the event:
  ```yaml
  - name: BookingLaneFullJson
    match: '"service": "bookings", "event": "lane_no_capacity"'
    threshold: 10 in 10m
    page: ops-oncall
  ```
  The match relies on harbor_obs key order: ts, level, service, event, request_id.
- Add a comment above it saying the old rule is deleted in a follow-up PR once every instance
  runs harbor_obs.
- In the PR, list the alerts touched, ask for SRE review (CODEOWNERS requests it), and state the
  rollout caveat: during a mixed deploy, events are split across both rules and their thresholds.
- Never add a field or event that contains another rule's phrase. The checker flags it as a
  false page.

## 4. Tests
- Don't rename or delete existing tests. The checker replays alerts per test name against the
  base revision. If an existing test asserts old plain text (e.g. quotes), change the assertion
  to check the JSON fields, but keep the test name.
- Add contract tests with `capsys` that parse each line as JSON, one per log call. Each test
  asserts `level`, `service`, `event`, `request_id` and the fields. Every log call must be hit by
  some test, otherwise the checker fails with `coverage`.
- If the service binds request ids, add a test with two calls using different ids that asserts
  each line carries its own id.

## 5. Prove it
```bash
pytest -q
python scripts/check_logmig.py <service> --base origin/main --json /tmp/logmig-<service>.json
```
Fix the code until both pass. Never edit the checker, `hl_log/`, `docs/AUDIT.md` or other
services to get a pass. If the checker looks wrong, report `needs_human` with the failing
output. After 3 failed fix attempts on the same failure, report `needs_human` with that failure.

## 6. Ship
- Branch: `devin/<unix-ts>-logmig-<service>`.
- Commit message: `[logmig] <service>: move to harbor_obs`. Don't ask for approval.
- Push. Open a non-draft PR with that title. The body includes:
  - a pseudo-diff of the log calls
  - the checker's `samples` lines
  - its alert replay lines
  - `Alerts touched: ...` (or `none`), plus the rollout caveat if any
  - any WARN lines (e.g. `request_id` is null because the service has no request context)
- Wait for CI (`test` and `logmig-check`). If CI fails, fix it and push. Never merge.

## 7. Report
Update the tracking issue: the issue given in the prompt, otherwise the open issue titled
`logmig progress` in arunbalaji2019/harbor-lane (#4). Its body has ONE table for all repos:

| service | status | PR | checker result | session |
|---|---|---|---|---|
| harbor-lane/bookings | PR open | owner/repo#1 | PASS | [session](<this session's URL>) |

- `service` is `<repo>/<service>`; `status` is `in progress`, `PR open`, `needs human: <reason>`
  or `nothing to do`; `checker result` is `PASS`, `FAIL: <first failure>` or blank.
- Set `in progress` when you start, and your final status at the end.
- Edit only your own row (append it if missing). Other sessions edit the same body, so re-read
  the issue immediately before each edit, then read it again afterwards; if your row didn't
  stick, retry once more.

Finish with structured output matching:
```json
{"repo": "owner/repo", "service": "bookings",
 "status": "pr_opened | needs_human | nothing_to_do | already_open",
 "pr_url": "https://... or null", "checker_passed": true, "ci_passed": true,
 "alerts_touched": ["BookingLaneFullJson"], "needs_human_reason": null}
```

## Pilot notes (bookings, harbor-lane)
- The only issue `pytest -q` missed was the `BookingLaneFull` alert going silent. The checker's
  alert replay catches it.
- One session migrated the service, wrote the contract tests and passed CI without any human
  input. The ACU cost per session comes from the v3 API (`acus_consumed`); this session can't
  read it about itself.
