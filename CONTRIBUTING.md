# Contributing

- One service per PR, so each owner reviews only their own change.
- PR titles for the logging migration start with `[logmig]` and name the service, for example `[logmig] payments: move to harbor_obs`.
- CI (`pytest -q`) must be green before review.
- Every PR needs a human approval. Nobody merges their own PR, bots included.
- `services/legacy_edi/` is owned by the EDI partner team (see CODEOWNERS). Don't change it. Raise an issue for them instead.
- Changes under `alerts/` page people at night if they're wrong. They need Kofi (SRE) on the review, and the PR has to say which alerts it touches.
- Never log personal data: email addresses, phone numbers, names. Use ids. This applies to old and new logs.
