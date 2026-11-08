# Watchtower — Project Documentation

Self-hosted performance + availability monitoring for all projects. Probes HTTP endpoints, GitHub Actions workflows, and local script logs. Sends alerts via Telegram + Resend email.

**Location**: `C:\Users\user\watchtower` (local)
**GitHub**: https://github.com/tommytang2414/watchtower
**Host**: AWS Lightsail VPS (`18.139.210.59`) — port 8080
**VPS path**: `/home/ubuntu/watchtower/monitor/`
**SSH**: `ubuntu` user with `LightsailDefaultKey-ap-southeast-1.pem`

---

## Quick Start

```bash
# Deploy to VPS
pwsh C:\Users\user\watchtower\deploy.ps1

# Or SSH in and run manually
ssh -i "C:\Users\user\PycharmProjects\CryptoStrategy\mcp_server\LightsailDefaultKey-ap-southeast-1.pem" ubuntu@18.139.210.59
cd ~/watchtower
source venv/bin/activate
python -m uvicorn main:app --host 0.0.0.0 --port 8080
```

**Dashboard**: http://18.139.210.59:8080/
**Health**: http://18.139.210.59:8080/health

---

## Architecture

```
VPS (FastAPI)                    Targets
────────────────                 ──────────────────────────────────────
Probe scheduler (APScheduler)    ──► HTTP endpoints
                                    ──► GitHub Actions workflows
                                    ──► Local script log files
Alert dispatch                   ──► Telegram bot (instant)
                                    Resend email (fallback)
Dashboard                        ──► All registered targets status
```

---

## File Structure

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app + APScheduler — probe dispatch, dashboard route |
| `config.py` | All probe definitions — add/edit targets here |
| `storage.py` | SQLite: metrics (checks table) + alert state (sent_alerts table) |
| `alerter.py` | Telegram + Resend dispatch, 4-hour dedup suppression |
| `probes/http_probe.py` | HTTP/HTTPS GET with response time, content check, stale flag |
| `probes/github_actions.py` | GitHub Actions workflow poller (PyGithub) |
| `probes/log_parser.py` | Local log file scanner for failure keywords |
| `templates/dashboard.html` | Dark-themed HTML dashboard (green/red dots + history) |
| `requirements.txt` | Python dependencies |
| `deploy.ps1` | One-command deploy to Lightsail VPS |
| `.env.example` | Required env vars template |

---

## Adding New Probes

Edit `config.py` only. No core code changes needed.

```python
# HTTP probe example
{
    "name": "my-website",
    "type": "http",
    "target": "https://example.com/",
    "interval_minutes": 5,
    "timeout_seconds": 10,
    "content_check": "ExpectedString",
    "alert_on": ["down", "slow_10s", "content_missing"],
},

# GitHub Actions probe example
{
    "name": "my-workflow",
    "type": "github_actions",
    "owner": "mygithubuser",
    "repo": "my-repo",
    "workflow_filename": "ci.yml",
    "interval_minutes": 5,
    "alert_on": ["failure"],
},

# Log parser probe example
{
    "name": "my-script-log",
    "type": "log_parser",
    "log_path": "/home/user/myproject/logs",
    "keywords": ["ERROR", "FAILED", "Exception"],
    "interval_minutes": 5,
    "alert_on": ["keyword_found"],
},
```

`alert_on` options per probe type:
- `http`: `down`, `slow_5s`, `slow_10s`, `stale`, `content_missing`
- `github_actions`: `failure`
- `log_parser`: `keyword_found`

---

## Environment Variables

Set on VPS in `~/.env` or `monitor/.env`:

```env
TELEGRAM_BOT_TOKEN=   # BotFather bot token
TELEGRAM_CHAT_ID=     # Your Telegram chat ID
RESEND_API_KEY=        # Reuse from exchange-website
ALERT_EMAIL=          # Email to receive alerts
GITHUB_TOKEN=         # GitHub PAT (repo scope, read-only)
```

### Getting Telegram Chat ID
1. Message @userinfobot on Telegram
2. Or create a Telegram channel and get the channel ID

### Getting GitHub Token
1. https://github.com/settings/tokens
2. Generate new token (classic)
3. Scopes: `repo` (full) or `repo:status` (read-only for public repos)

---

## Database Schema

```sql
-- Check results
checks(id, probe_name, probe_type, up, response_time_ms, status_code,
       stale, rates_count, content_ok, error_message, conclusion,
       matched_keywords, created_at)

-- Alert dedup state
sent_alerts(id, probe_name, alert_type, sent_at, resolved_at)
```

Alert fires once per `probe_name + alert_type`. Subsequent failures are suppressed for 4 hours. On recovery, a `RECOVERED` message fires and the dedup window resets.

---

## Current Probes

| Probe | Type | Target | Interval |
|-------|------|--------|----------|
| `winwin-website` | http | https://winwinexchangehk.com/ | 5 min |
| `winwin-api-rates` | http | https://winwinexchangehk.com/api/rates | 5 min |
| `winwin-api-history` | http | https://winwinexchangehk.com/api/rates/history?days=7 | 5 min |
| `winwin-autopost-gha` | github_actions | tommytang2414/exchange-website daily-rate-card.yml | 5 min |

### Output probes (audit-2 E01)

Checks every 15 min that a job left the evidence of a good run. Rules: `probes/output_checks.py`; targets: `OUTPUT_PROBES` in `config.py`; design: `docs/output-checks.md`.

| Probe | Evidence | Alerts when |
|-------|----------|-------------|
| `hsi-shortsell` | `hsi-monitor` lines in `/var/log/syslog{,.1}` | HK trading day: no run by 13:00/17:00 HKT, under 47 stocks, or close data date not today |
| `taker-opt`, `taker-og`, `taker-sheet` | systemd journal | no `Running checks` / `logged` line in 2 h |
| `smartflow-sec-form4`, `-form144`, `-congress-house`, `-sfc-short` | `~/SmartFlow-shadow/logs/*.log` | no successful JSON block in 2 h (SFC 26 h) |
| `watchtower-relay` | relay JSON | relay older than 2 h, or a source unreachable |
| `short-alpha-lambda` | relay: CloudWatch | 0 candidates in all scans for 14 days, no scans, or price check unavailable in 4 days |
| `devops-scanner` | relay: Task Scheduler | last result not 0 |
| `mac-smartflow-research`, `mac-asset-radar`, `mac-vulnpulse`, `mac-hk-civic-newsroom`, `mac-meme-agent` | relay: launchd | exit not 0, stdout log stale, asset-radar run or provider coverage incomplete. `mac-meme-agent` ends 2026-11-13 08:00 HKT |

**Relay**: Windows scheduled task `WatchtowerRelay` runs `relay/relay.py` with `pythonw.exe` every 30 min. Read-only; it uploads raw facts to `~/watchtower/heartbeats/relay.json` on the VPS. Mac connection settings are `RELAY_*` keys in the untracked local `.env`. Last run log: `%LOCALAPPDATA%\watchtower-relay\last-run.log`. If the PC is off, one `watchtower-relay` alert fires and relay-fed probes skip.

**Gotchas**
- `deploy.ps1` is stale: it uploads to `~/watchtower`, but the app runs from `~/watchtower/monitor`. Deploy with `scp` into `monitor/`.
- Watchtower runs as systemd service `watchtower` (enabled, `Restart=always`). Restart with `sudo systemctl restart watchtower`; logs are in `journalctl -u watchtower`, not `/tmp/watchtower.log`.
- Resend's test sender only delivers to the Resend account's own address, so `ALERT_EMAIL` must be that address until a domain is verified. `TELEGRAM_CHAT_ID` is empty, so there is no working fallback.
- An alert is recorded in `sent_alerts` only after delivery; `ALERT NOT DELIVERED` in the log means it retries next run.

---

## VPS Setup (First Time)

1. **SSH key**: `C:\Users\user\PycharmProjects\CryptoStrategy\mcp_server\LightsailDefaultKey-ap-southeast-1.pem`
2. **Test SSH**: `ssh -i "C:\Users\user\PycharmProjects\CryptoStrategy\mcp_server\LightsailDefaultKey-ap-southeast-1.pem" ubuntu@18.139.210.59`
3. **Python**: Python 3.10.12 already installed on VPS
4. **Run deploy**: `pwsh C:\Users\user\watchtower\deploy.ps1`
5. **Set env vars** on VPS: edit `~/watchtower/.env`

### systemd service (installed 2026-11-08)
```ini
[Unit]
Description=Watchtower
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/watchtower/monitor
ExecStart=/home/ubuntu/watchtower/monitor/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
Save to `/etc/systemd/system/watchtower.service`, then:
```bash
sudo systemctl enable watchtower
sudo systemctl start watchtower
sudo journalctl -u watchtower -f
```

---

## Changelog

### 2026-11-08 — Watchtower moved to systemd
- Replaced the April `nohup` process with enabled service `watchtower`, so it starts on boot and restarts after a crash. Verified with `kill -9`; a full VPS reboot was not tested.

### 2026-11-08 — Output checks and alert delivery (audit-2 E01)
- Added 16 output probes for HSI, TakerLongShort, SmartFlow shadow, short-alpha, DevOps-Scanner and five Mac launchd jobs. See `docs/output-checks.md`.
- Added the read-only Windows relay (`relay/relay.py`, task `WatchtowerRelay`). No new port, key or IAM change.
- Found that no alert had ever been delivered: Resend returned 403 for `ALERT_EMAIL`, and Telegram had no chat ID. Changed VPS `ALERT_EMAIL` to the Resend account address; alerts are now recorded only after delivery.
- Production deploy: commits `66b525e`, `0975ae1`. First delivered alerts: `short-alpha-lambda`, `mac-smartflow-research`, `mac-asset-radar`, `devops-scanner`.

### 2026-04-04 — Watchtower goes live
- Renamed from "Monitor Framework" to **Watchtower**
- GitHub repo: https://github.com/tommytang2414/watchtower
- VPS service deployed to: `/home/ubuntu/watchtower/monitor/`
- Port 8080 opened on Lightsail firewall
- Telegram bot configured: `Tommy's nanobot` (8363136217:AAEJk58sDggPZ1Ibr66pyFbwANkH-RtqlUQ)
- GitHub PAT configured for `winwin-autopost-gha` probe
- VPS service running at: http://18.139.210.59:8080/

### 2026-04-03 — Initial implementation
- FastAPI monitoring service with SQLite storage
- 3 HTTP probes (winwinexchangehk.com)
- GitHub Actions poller (daily-rate-card workflow)
- Log parser probe (WinWinAutoPost failure keywords) — removed 2026-04-04 (GitHub Actions covers this)
- Telegram + Resend alerting with 4-hour dedup
- Dark-themed HTML dashboard
- WinWinAutoPost retry decorator (3x, 30s backoff) + FINAL_STATUS line
