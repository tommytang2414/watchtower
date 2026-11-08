"""Probe definitions — add new targets here, no core code changes needed."""
import os

# ─── HTTP Probes ──────────────────────────────────────────────────────────────

HTTP_PROBES = [
    {
        "name": "winwin-website",
        "type": "http",
        "target": "https://winwinexchangehk.com/",
        "interval_minutes": 5,
        "timeout_seconds": 10,
        "content_check": "有利兌匯",
        "alert_on": ["down", "content_missing", "slow_10s"],
    },
    {
        "name": "winwin-api-rates",
        "type": "http",
        "target": "https://winwinexchangehk.com/api/rates",
        "interval_minutes": 5,
        "timeout_seconds": 10,
        "alert_on": ["down", "slow_5s", "stale"],
    },
    {
        "name": "winwin-api-history",
        "type": "http",
        "target": "https://winwinexchangehk.com/api/rates/history?days=7",
        "interval_minutes": 5,
        "timeout_seconds": 10,
        "alert_on": ["down", "slow_5s"],
    },
]

# ─── GitHub Actions Probes ─────────────────────────────────────────────────────

GITHUB_PROBES = [
    {
        "name": "winwin-autopost-gha",
        "type": "github_actions",
        "owner": "tommytang2414",
        "repo": "exchange-website",
        "workflow_filename": "daily-rate-card.yml",
        "interval_minutes": 5,
        "alert_on": ["failure"],
    },
]

# ─── Output probes (audit-2 E01) ───────────────────────────────────────────────
# "The job ran but produced nothing useful." Rules live in probes/output_checks.py.
# Design and push/pull choice per job: docs/output-checks.md.

def _output(name: str, check: str, target: str, interval: int = 15, **kw) -> dict:
    return {"name": name, "type": "output", "check": check, "target": target,
            "interval_minutes": interval, "alert_on": ["bad_output"], **kw}


def _journal(name: str, unit: str, pattern: str) -> dict:
    return _output(name, "journal_fresh", f"systemd {unit}", unit=unit, pattern=pattern, max_age_hours=2)


def _shadow(name: str, log: str, max_age_hours: float) -> dict:
    return _output(name, "json_log", f"SmartFlow shadow {log}",
                   log_path=f"~/SmartFlow-shadow/logs/{log}", max_age_hours=max_age_hours)


def _launchd(name: str, label: str, max_age_hours: float, **kw) -> dict:
    return _output(name, "relay_launchd", f"Mac launchd {label}", label=label, max_age_hours=max_age_hours, **kw)


OUTPUT_PROBES = [
    # VPS, pulled locally
    _output("hsi-shortsell", "hsi", "VPS cron hsi-monitor (12:15/16:15 HKT)",
            syslog_tag="hsi-monitor", min_stocks=47),
    _journal("taker-opt", "takerlongshort-opt", "Running checks"),
    _journal("taker-og", "takerlongshort-og", "Running checks"),
    _journal("taker-sheet", "takerlongshort-sheet", "logged"),
    _shadow("smartflow-sec-form4", "sec-shadow-form4.log", 2),
    _shadow("smartflow-sec-form144", "sec-shadow-form144.log", 2),
    _shadow("smartflow-congress-house", "congress-house-shadow.log", 2),
    _shadow("smartflow-sfc-short", "sfc-short-shadow.log", 26),
    # Windows relay (relay/relay.py -> ~/watchtower/heartbeats/relay.json)
    _output("watchtower-relay", "relay_heartbeat", "Windows WatchtowerRelay task"),
    _output("short-alpha-lambda", "relay_lambda", "Lambda short-alpha-agent"),
    _output("devops-scanner", "relay_win_task", "Windows task DevOpsScanner", task_name="DevOpsScanner"),
    _launchd("mac-smartflow-research", "com.smartflow.research.daily", 26),
    _launchd("mac-asset-radar", "com.asset-radar.daily", 26, asset_radar=True),
    _launchd("mac-vulnpulse", "com.vulnpulse.scan", 7),
    _launchd("mac-hk-civic-newsroom", "com.hk-civic-newsroom.daily", 26),
    _launchd("mac-meme-agent", "com.meme-agent.research", 2, expect_running=True,
             active_until="2026-11-13T08:00:00+08:00"),
]

# ─── All probes ────────────────────────────────────────────────────────────────

PROBES = HTTP_PROBES + GITHUB_PROBES + OUTPUT_PROBES

# ─── Alert settings ────────────────────────────────────────────────────────────

ALERT_COOLDOWN_HOURS = 4

# ─── Alert channels ────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
