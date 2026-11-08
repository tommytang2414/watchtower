# AI Handoff

## Current state

- Branch / commit: `claude/e01-output-heartbeats-6f8fac`, based on `main` at `b5c8286`; production code at `d83f2b4` (not on `main` until this branch is merged).
- Last agent: Claude
- Updated: 2026-11-08 HKT

## Completed

- Audit-2 E01: output probes deployed. Design and later changes: `docs/output-checks.md`.
- Windows task `WatchtowerRelay` (every 30 min) supplies Mac, Lambda, Windows and GitHub facts.
- Alert delivery repaired. No alert had ever been delivered before this work.
- Watchtower runs as systemd service `watchtower`, with restart settings matching the Taker units.
- `winwin-autopost-gha` reads through the relay's `gh` login.
- AI diagnosis (`relay/triage.py`) is live: one read-only run per new alert, report emailed to the owner.

## Verification

- `python -m unittest discover -s tests`: 20 pass on Windows Python 3.12 and the VPS venv (3.10).
- Synthetic stale `relay.json` on production: one alert 16:32 HKT, dedup 16:47, `RECOVERED` 17:02. No other probe alerted; the four known-bad alerts were not re-sent; Win Win probes up.
- systemd: enabled, active, one uvicorn, new rows for all 20 probes, no alerts re-sent. Crash restart tested with `kill -9`; a full reboot was not.
- Triage: canary tests refused writes, shell, web, `.env` and out-of-project reads. Three real diagnoses reached the inbox, and a later run did not repeat them. The logged-out path pauses and emails a reminder.

## Decisions / constraints

- The uncommitted `CLAUDE.md` hunk contains a Resend key. It must not be committed; staged edits were built from HEAD.
- The repo is public: no LAN address, employer asset name or secret. Mac settings stay in `RELAY_*` keys in local `.env`.
- SmartFlow legacy cron is not probed. `mac-asset-radar` is excluded from AI diagnosis.

## Next handoff

- Merge this branch to `main`. The main checkout has an uncommitted `CLAUDE.md` from another session, so preserve it when updating that checkout.
- After the 2026-11-14 reboot, confirm the service is active and no alert was re-sent; a full reboot is still untested.
- Key counts for five jobs need writer changes in their own projects: see "Key counts not yet covered" in `docs/output-checks.md`.
- AI diagnosis claims are unverified; each owning project's session should confirm before fixing.
- Follow-ups: fix `deploy.ps1`, set a Telegram chat ID, rotate exposed credentials (R01).
