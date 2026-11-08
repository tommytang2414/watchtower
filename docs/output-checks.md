# Output checks (audit-2 E01) — design note

Status: approved by the owner and deployed, 2026-11-08 (commits `66b525e`, `0975ae1`).

## Problem

Watchtower only checks whether Win Win URLs respond. Six live jobs ran on schedule
but produced nothing useful for days or months, and no alert fired. An output
check asks "did the job leave the evidence a good run leaves?" instead of
"is the process up?".

## Constraints

- Watchtower runs on the VPS as `ubuntu` (member of `adm`, so it can read the
  system journal). It cannot reach the Mac mini (LAN only) or the Windows PC.
- Lightsail exposes only 22, 443 and 5001. No new inbound port.
- The VPS AWS user (`smartflow-uploader`) has no CloudWatch Logs read right.
- No new credentials, no IAM change, no edits to other projects' job code.
- The repo is public: no LAN addresses, Mac user paths outside job names,
  secrets, or employer asset names. asset-radar is checked by aggregate counts only.

## Push versus pull, per job

| Job | Where | Mode | Evidence read | Bad output rule |
|---|---|---|---|---|
| HSI-ShortSell-git | VPS root cron 12:15/16:15 HKT | Pull (syslog) | `hsi-monitor` lines in `/var/log/syslog{,.1}` (the journal is capped at 50 MB, about 2-4 days): run start, `短倉: N/49`, `Z-Score sheet 更新：DATE` | On an HK trading day: by 13:00 no midday run or N < 47; by 17:00 no afternoon run, N < 47, or data date is not today |
| TakerLongShort opt/og | VPS systemd | Pull (journal) | last `Running checks` line per unit | none in 2 h |
| TakerLongShort sheet | VPS systemd | Pull (journal) | last `logged` line | none in 2 h |
| SmartFlow shadow collectors | VPS cron | Pull (files) | `~/SmartFlow-shadow/logs/*.log` last JSON block | last success older than 2 h (hourly/5-min collectors) or 26 h (daily SFC) |
| short-alpha Lambda | AWS | Relay | CloudWatch `Full scan done: N watch candidates`, `Price check unavailable` | 0 candidates in every scan for 14 days, no scans in 14 days, or any price-check failure in 4 days (covers weekends) |
| Mac launchd (5 jobs) | Mac mini | Relay | `launchctl print` last exit / running, stdout log mtime | exit != 0, or log older than schedule + slack |
| asset-radar | Mac mini | Relay | daily `ledger.json` status; `scan.json` `observations_complete`, tools ran/ok counts | run not complete, or tools ok < tools ran |
| DevOps-Scanner | Windows task | Relay | `LastTaskResult` | != 0 |
| Relay itself | Windows task | Pull (file) | `generated_at` in relay JSON | older than 2 h |

### The relay (recommended)

The Windows PC is the only machine that already reaches the Mac (pinned SSH key),
AWS (existing CLI profile) and the VPS (`ssh vps`). A Windows scheduled task,
`WatchtowerRelay`, runs `relay/relay.py` with `pythonw.exe` (no window) every
30 minutes. It only reads: `launchctl print`, `stat`, two small JSON summaries
on the Mac, `aws logs filter-log-events`, and `Get-ScheduledTaskInfo`. It writes
one JSON file of raw facts and copies it to the VPS at
`~/watchtower/heartbeats/relay.json` (scp to a temp name, then `mv`).
Watchtower applies every rule; the relay makes no decisions.

If the PC is off or asleep, one `watchtower-relay` alert fires and the
relay-fed checks pause instead of each raising its own alert.

Cost: one new Windows scheduled task (persistent configuration on the owner's PC).
No new port, key, token or IAM permission. Residual risk: the relay calls AWS
with the existing `claude-agent` profile, which is AdministratorAccess. The calls
are read-only, but a narrower read-only profile would be better (optional,
separate IAM approval).

### Alternatives considered

- **Mac pushes to the VPS**: needs a new SSH key in the VPS `authorized_keys`. New credential. Rejected.
- **Mac or Windows jobs send Telegram themselves**: copies the bot token to more machines and edits other projects' jobs. Rejected.
- **VPS pulls CloudWatch for short-alpha**: needs `logs:FilterLogEvents` on one log group for `smartflow-uploader`. IAM change. Possible later, independent of the PC.
- **Reading `ss_history.csv` directly**: `/opt/hsi-monitor` is `root 700`; it would need `sudo` from Watchtower. The journal already carries the stock count and data date, so not needed.

## Engine changes

- New probe type `output` (`probes/output_checks.py`) with checks `hsi`, `journal_fresh`, `json_log`, `relay_heartbeat`, `relay_launchd`, `relay_lambda`, `relay_win_task`.
- New alert type `bad_output`, deduplicated and recovered like the others.
- A check may return `skip` (relay stale, job past its end date). A skip neither alerts nor resolves.
- HK trading days: `holidays` package (HK public holidays) plus weekends. Typhoon closures will cause one false alert that clears on the next trading day.

## Not covered

- SmartFlow legacy cron (`~/SmartFlow/logs/cron.log`): fails daily with
  `Permission denied` since 2026-07-21 because `smartflow_vps.sh` is mode 664.
  Legacy collectors were disabled on purpose (SmartFlow P0-003), so this is not
  probed. The SmartFlow session should delete or fix that cron line.
- Process restart: Watchtower runs under `nohup`, not systemd. A VPS reboot stops
  monitoring silently. Installing the documented systemd unit is a separate follow-up.

## Result of first deploy

Four probes fired on the known silent failures, and Resend accepted all four emails:
`mac-smartflow-research` (exit 1), `mac-asset-radar` (providers 19/21),
`short-alpha-lambda` (0 candidates in 170 scans, price check unavailable),
`devops-scanner` (exit 2).

Deploying also showed that no alert had ever been delivered: Resend's test sender
rejected `ALERT_EMAIL` with 403, and `TELEGRAM_CHAT_ID` was empty. `ALERT_EMAIL` now
holds the Resend account's address, and an alert is recorded only after delivery.

## Follow-ups for other projects

No job needs a heartbeat line; every check reads output the job already writes.
These are the fixes that will clear the alerts, each for that project's own session:

| Project | Alert it clears | Change |
|---|---|---|
| SmartFlow | `mac-smartflow-research` | Find why the research job has exited 1 since 2026-11-06 |
| SmartFlow | none (legacy cron) | Remove the dead line: `crontab -l \| grep -v 'smartflow_vps.sh' \| crontab -`, or run it as `bash ~/SmartFlow/smartflow_vps.sh` if the daily restart is still wanted |
| short-alpha | `short-alpha-lambda` | Package `yfinance` in the Lambda or replace the price lookup |
| asset-radar | `mac-asset-radar` | Fix or retire the two degraded providers |
| DevOps-Scanner | `devops-scanner` | Find why `run_daily_scan.bat` exits 2 |
| HSI-ShortSell-git | prevents fake signals (A2-O2) | In `main()` right after `fetch_all()` (assuming the result is named `scraped`): `if sum(d.get("ss_ratio") is not None for d in scraped) < 47: sys.exit(2)` |
