"""
Alert dispatch — Telegram + Resend + deduplication.
Phase 1 stub: logging only. Phase 2 adds real Telegram/Resend sends.
"""
import logging
import os
from datetime import datetime, timezone, timedelta

import httpx

logger = logging.getLogger(__name__)


def _hkt_now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M HKT")


async def send_alert(probe: dict, result: dict, alert_type: str) -> bool:
    """Send an alert by email, falling back to Telegram. Returns True only if one channel delivered."""
    target = probe.get("target") or probe.get("log_path") or f"{probe['owner']}/{probe['repo']}"
    name = probe["name"]
    ptype = probe["type"]

    rt_ms = result.get("response_time_ms")
    rt_str = f"{rt_ms:.0f}ms" if rt_ms else "N/A"
    err = result.get("error_message") or result.get("conclusion") or result.get("matched_keywords") or ""
    err_str = str(err) if err else ""

    msg = (
        f"[{name}] FAILED — {alert_type}\n"
        f"Target: {target}\n"
        f"Response: {rt_str}\n"
        f"Detail: {err_str}\n"
        f"Time: {_hkt_now()}"
    )

    logger.warning(f"ALERT: {msg}")

    # Resend email — primary alert channel
    resend_key = os.getenv("RESEND_API_KEY", "")
    alert_email = os.getenv("ALERT_EMAIL", "")
    email_ok = False
    if resend_key and alert_email:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    json={
                        "from": "Watchtower <onboarding@resend.dev>",
                        "to": [alert_email],
                        "subject": f"[{name}] FAILED — {alert_type} — {target}",
                        "text": msg,
                    },
                    headers={"Authorization": f"Bearer {resend_key}"},
                    timeout=15,
                )
            if resp.status_code in (200, 201, 202):
                logger.info(f"Email alert sent for {name}")
                email_ok = True
            else:
                logger.error(f"Email alert failed: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.error(f"Email alert failed: {e}")

    # Telegram — secondary (only if email failed)
    if not email_ok:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if bot_token and chat_id:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": chat_id, "text": msg},
                        timeout=10,
                    )
                if resp.status_code == 200:
                    logger.info(f"Telegram fallback alert sent for {name}")
                    return True
                logger.error(f"Telegram fallback alert failed: {resp.status_code}")
            except Exception as e:
                logger.error(f"Telegram fallback alert also failed: {e}")
        else:
            logger.error("Telegram fallback not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID)")
    return email_ok


async def send_recovered(probe: dict, result: dict):
    """Send a recovery notification."""
    name = probe["name"]
    target = probe.get("target") or probe.get("log_path") or f"{probe['owner']}/{probe['repo']}"
    rt_ms = result.get("response_time_ms")
    rt_str = f"{rt_ms:.0f}ms" if rt_ms else "N/A"

    msg = (
        f"[{name}] RECOVERED\n"
        f"Target: {target}\n"
        f"Response: {rt_str}\n"
        f"Time: {_hkt_now()}"
    )

    logger.info(f"RECOVERED: {msg}")

    # Email — primary
    resend_key = os.getenv("RESEND_API_KEY", "")
    alert_email = os.getenv("ALERT_EMAIL", "")
    email_ok = False
    if resend_key and alert_email:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    json={
                        "from": "Watchtower <onboarding@resend.dev>",
                        "to": [alert_email],
                        "subject": f"[{name}] RECOVERED — {target}",
                        "text": msg,
                    },
                    headers={"Authorization": f"Bearer {resend_key}"},
                    timeout=15,
                )
            if resp.status_code in (200, 201, 202):
                logger.info(f"Recovery email sent for {name}")
                email_ok = True
            else:
                logger.error(f"Recovery email failed: {resp.status_code}")
        except Exception as e:
            logger.error(f"Recovery email failed: {e}")

    # Telegram — secondary fallback
    if not email_ok:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if bot_token and chat_id:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": chat_id, "text": msg},
                        timeout=10,
                    )
            except Exception as e:
                logger.error(f"Telegram recovery fallback also failed: {e}")
