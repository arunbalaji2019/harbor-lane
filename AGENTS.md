# AGENTS.md

Rules for any agent working in this repo. They come from CONTRIBUTING.md, docs/LOGGING_STANDARD.md,
docs/AUDIT.md and CODEOWNERS. If a rule and a task conflict, the rule wins: record "needs human"
with the reason and stop.

## Must follow
- Sessions run unattended. Never wait for approval, including on commit messages. If blocked,
  record `needs human` with the reason (see `.agents/skills/logmig/SKILL.md`) and stop.
- One service per PR. Logging-migration PR titles are `[logmig] <service>: move to harbor_obs`.
- Never merge a PR, including your own. Every PR needs a human approval.
- `services/legacy_edi/` belongs to the EDI partner team. Don't change it; raise an issue for them.
- Don't change `hl_log.audit()`, `audit.log`, its path or format, the set of audited actions, or
  `docs/AUDIT.md`. That is Finance's HMRC record, not application logging.
- Never log personal data (emails, phone numbers, names) in old or new logs. Log ids instead.
- Changes under `alerts/` page people at night. Only add rules; never edit or delete an existing
  rule in a migration PR. The PR must list every alert it touches and needs SRE (Kofi) review.
- Before opening a `[logmig]` PR, both must pass:
  `pytest -q` and `python scripts/check_logmig.py <service> --base origin/main`.
  CI runs the same checker on every `[logmig]` PR. Don't weaken the checker or its tests to pass.

## Setup
Python 3.11. `pip install -r requirements-dev.txt`, then `pytest -q`.

## Logging migration
Follow `.agents/skills/logmig/SKILL.md`.
