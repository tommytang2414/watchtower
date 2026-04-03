# Watchtower — Project Documentation

Self-hosted performance + availability monitoring for all projects. Probes HTTP endpoints, GitHub Actions workflows, and local script logs. Sends alerts via Telegram + Resend email.

**Location**: `C:\Users\user\watchtower`
**GitHub**: https://github.com/tommytang2414/watchtower
**Host**: AWS Lightsail VPS (`18.139.210.59`) — port 8080
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
| `winwin-autopost-log` | log_parser | C:/Users/user/WinWinAutoPost/logs | 5 min |

---

## VPS Setup (First Time)

1. **SSH key**: `C:\Users\user\PycharmProjects\CryptoStrategy\mcp_server\LightsailDefaultKey-ap-southeast-1.pem`
2. **Test SSH**: `ssh -i "C:\Users\user\PycharmProjects\CryptoStrategy\mcp_server\LightsailDefaultKey-ap-southeast-1.pem" ubuntu@18.139.210.59`
3. **Python**: Python 3.10.12 already installed on VPS
4. **Run deploy**: `pwsh C:\Users\user\watchtower\deploy.ps1`
5. **Set env vars** on VPS: edit `~/watchtower/.env`

### systemd service (optional)
```ini
[Unit]
Description=Watchtower
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/watchtower
ExecStart=/home/ubuntu/watchtower/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
```
Save to `/etc/systemd/system/monitor.service`, then:
```bash
sudo systemctl enable monitor
sudo systemctl start monitor
sudo journalctl -u monitor -f
```

---

## Changelog

### 2026-04-03 — Initial implementation
- FastAPI monitoring service with SQLite storage
- 3 HTTP probes (winwinexchangehk.com)
- GitHub Actions poller (daily-rate-card workflow)
- Log parser probe (WinWinAutoPost failure keywords)
- Telegram + Resend alerting with 4-hour dedup
- Dark-themed HTML dashboard
- WinWinAutoPost retry decorator (3x, 30s backoff) + FINAL_STATUS line
