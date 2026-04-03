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

# ─── All probes ────────────────────────────────────────────────────────────────

PROBES = HTTP_PROBES + GITHUB_PROBES

# ─── Alert settings ────────────────────────────────────────────────────────────

ALERT_COOLDOWN_HOURS = 4

# ─── Alert channels ────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
