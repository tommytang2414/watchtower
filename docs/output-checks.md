# Output checks (audit-2 E01) — design note

Status: draft for owner approval, 2026-11-08.

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

## Expected alerts on first deploy

These are the known silent failures and prove the checks work:
smartflow-research (exit 1), asset-radar (tools ok < ran), short-alpha
(0 candidates / price check unavailable), DevOps-Scanner (exit 2).
