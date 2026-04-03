"""
Monitor Framework — main.py
FastAPI app + APScheduler. Run probes periodically and store results.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from jinja2 import Environment, FileSystemLoader, select_autoescape
import httpx

from config import PROBES, ALERT_COOLDOWN_HOURS
from storage import (
    init_db,
    record_check,
    get_last_check,
    get_recent_checks_all,
    get_unresolved_alert,
    upsert_alert,
    resolve_alert,
)
from alerter import send_alert, send_recovered
from probes import run_http_probe, run_github_actions_probe, run_log_parser_probe

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Hong_Kong")


# ─── Probe dispatch ────────────────────────────────────────────────────────────

def should_alert(probe: dict, check_result: dict) -> Optional[str]:
    """Return alert type string if alert should fire, else None."""
    up = check_result.get("up", False)
    alert_on = probe.get("alert_on", [])

    if not up:
        if "down" in alert_on:
            return "down"

    # HTTP-specific checks
    if probe["type"] == "http":
        rt_ms = check_result.get("response_time_ms") or 0
        if rt_ms > probe.get("timeout_seconds", 10) * 1000 and "slow" in alert_on:
            return f"slow_{probe['timeout_seconds']}s"

        if check_result.get("stale") and "stale" in alert_on:
            return "stale"

        if probe.get("content_check"):
            content_ok = check_result.get("content_ok")
            if content_ok is False and "content_missing" in alert_on:
                return "content_missing"

    # GitHub Actions
    if probe["type"] == "github_actions":
        conclusion = check_result.get("conclusion")
        if conclusion == "failure" and "failure" in alert_on:
            return "failure"

    # Log parser
    if probe["type"] == "log_parser":
        if check_result.get("has_failure") and "keyword_found" in alert_on:
            return "keyword_found"

    return None


async def run_probe(probe: dict) -> dict:
    """Dispatch to the correct probe implementation."""
    ptype = probe["type"]

    if ptype == "http":
        return await run_http_probe(
            target=probe["target"],
            timeout_seconds=probe.get("timeout_seconds", 10),
            content_check=probe.get("content_check"),
        )
    elif ptype == "github_actions":
        return await run_github_actions_probe(
            owner=probe["owner"],
            repo=probe["repo"],
            workflow_filename=probe["workflow_filename"],
        )
    elif ptype == "log_parser":
        return await run_log_parser_probe(
            log_path=probe["log_path"],
            keywords=probe.get("keywords", []),
        )
    else:
        return {"up": False, "error_message": f"Unknown probe type: {ptype}"}


async def check_and_alert(probe: dict):
    """Run a probe, record result, fire or resolve alerts."""
    name = probe["name"]
    logger.info(f"Running probe: {name}")

    try:
        result = await run_probe(probe)
    except Exception as e:
        logger.error(f"Probe {name} raised exception: {e}")
        result = {"up": False, "error_message": str(e)}

    # Record to SQLite
    await record_check(
        probe_name=name,
        probe_type=probe["type"],
        up=result.get("up", False),
        response_time_ms=result.get("response_time_ms"),
        status_code=result.get("status_code"),
        stale=result.get("stale"),
        rates_count=result.get("rates_count"),
        content_ok=result.get("content_ok"),
        error_message=result.get("error_message"),
        conclusion=result.get("conclusion"),
        matched_keywords=result.get("matched_keywords"),
    )

    # Determine if alert should fire
    alert_type = should_alert(probe, result)

    if alert_type:
        # Check dedup cooldown
        unresolved = await get_unresolved_alert(name, alert_type)
        if not unresolved:
            await upsert_alert(name, alert_type)
            await send_alert(probe, result, alert_type)
            logger.warning(f"ALERT fired: {name} [{alert_type}]")
        else:
            logger.info(f"Alert suppressed (dedup): {name} [{alert_type}]")
    else:
        # Probe succeeded — check if we need to send RECOVERED
        was_down = await get_unresolved_alert(name, "down")
        was_failure = await get_unresolved_alert(name, "failure")
        was_keyword = await get_unresolved_alert(name, "keyword_found")

        for alert_type_resolve in ["down", "failure", "keyword_found", "stale", "slow_5s", "slow_10s", "content_missing"]:
            resolved = await resolve_alert(name, alert_type_resolve)
            if resolved:
                await send_recovered(probe, result)
                logger.info(f"RECOVERED alert sent: {name}")
                break


async def run_all_probes():
    """Run all probes concurrently."""
    tasks = [check_and_alert(probe) for probe in PROBES]
    await asyncio.gather(*tasks, return_exceptions=True)


# ─── FastAPI app ───────────────────────────────────────────────────────────────

# Jinja2 template loader — reads from templates/ directory
import os as _os
_templates_dir = _os.path.join(_os.path.dirname(__file__), "templates")
_jinja_env = Environment(
    loader=FileSystemLoader(_templates_dir),
    autoescape=select_autoescape(["html", "xml"]),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database initialized")

    # Schedule all probes
    for probe in PROBES:
        interval = probe.get("interval_minutes", 5)
        scheduler.add_job(
            check_and_alert,
            IntervalTrigger(minutes=interval),
            args=[probe],
            id=probe["name"],
            replace_existing=True,
        )
        logger.info(f"Scheduled probe: {probe['name']} every {interval}m")

    scheduler.start()
    logger.info("Scheduler started")

    # Run all probes once at startup
    await run_all_probes()

    yield

    scheduler.shutdown()


app = FastAPI(title="Watchtower", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the HTML dashboard."""
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S HKT")
    checks = await get_recent_checks_all(hours=24, limit_per_probe=20)
    tmpl = _jinja_env.get_template("dashboard.html")
    return tmpl.render(checks=checks, now=now)


@app.get("/health")
async def health():
    """Self health check."""
    return {"status": "ok", "time": datetime.now(timezone(timedelta(hours=8))).isoformat()}


@app.get("/api/checks")
async def api_checks(probe: Optional[str] = None, hours: int = 24):
    """JSON endpoint for check history."""
    if probe:
        checks = await get_recent_checks_all(hours=hours, limit_per_probe=100)
        return {probe: checks.get(probe, [])}
    checks = await get_recent_checks_all(hours=hours, limit_per_probe=100)
    return checks


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
