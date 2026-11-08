# AI Handoff

## Current state

- Branch / commit: `main`; production code at `0975ae1`. Docs commit follows it.
- Last agent: Claude
- Updated: 2026-11-08 HKT

## Completed

- Audit-2 E01: 16 output probes deployed. Design: `docs/output-checks.md`.
- Windows task `WatchtowerRelay` (every 30 min) supplies Mac, Lambda and Windows facts.
- Alert delivery repaired. No alert had ever been delivered before this work.
- Watchtower now runs as enabled systemd service `watchtower`.

## Verification

- Rule tests on real logs passed; VPS integration test confirmed alert, dedup and recovery.
- Deployed; VPS, local and HEAD code hashes match. Resend accepted four real alerts.
- systemd restart verified with `kill -9`. A full VPS reboot was not tested.

## Decisions / constraints

- The uncommitted `CLAUDE.md` hunk contains a Resend key. It predates this work, is preserved in the working tree and must not be committed.
- The repo is public: no LAN address, employer asset name or secret. Mac settings stay in `RELAY_*` keys in local `.env`.
- SmartFlow legacy cron is deliberately not probed.
- The relay uses the `claude-agent` AWS profile (AdministratorAccess) read-only; the owner accepted this.

## Next handoff

- Owner: confirm the four alert emails arrived.
- Watchtower follow-ups: fix `deploy.ps1`, set a Telegram chat ID, restore the empty VPS `GITHUB_TOKEN` (`winwin-autopost-gha` has been blind since about 2026-04-10), rotate exposed credentials (R01).
- Other projects' fixes are listed in `docs/output-checks.md` under Follow-ups.
