# AI Handoff

## Current state

- Branch / commit: `main`; production code at `444a2fb`.
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

- Rule tests on real logs passed; VPS integration test confirmed alert, dedup and recovery.
- systemd: enabled, active, one uvicorn, new rows for all 20 probes, no alerts re-sent. Crash restart tested with `kill -9`; a full reboot was not.
- Triage: canary tests refused writes, shell, web, `.env` and out-of-project reads. Three real diagnoses reached the inbox, and a later run did not repeat them. The logged-out path pauses and emails a reminder.

## Decisions / constraints

- The uncommitted `CLAUDE.md` hunk contains a Resend key. It must not be committed; staged edits were built from HEAD.
- The repo is public: no LAN address, employer asset name or secret. Mac settings stay in `RELAY_*` keys in local `.env`.
- SmartFlow legacy cron is not probed. `mac-asset-radar` is excluded from AI diagnosis.

## Next handoff

- AI diagnosis claims are unverified; each owning project's session should confirm before fixing.
- Follow-ups: fix `deploy.ps1`, set a Telegram chat ID, rotate exposed credentials (R01).
