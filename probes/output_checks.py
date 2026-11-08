"""Output checks: alert when a job runs but leaves no evidence of a good run.

Each check returns {"up": bool, "error_message": str | None, "skip": bool}.
"skip" means "cannot judge right now" (relay stale, job past its end date):
main.py neither alerts nor resolves on a skip.
"""
import asyncio
import json
import os
import re
import subprocess
import time
from datetime import date, datetime, timedelta, timezone

import holidays

HKT = timezone(timedelta(hours=8))
RELAY_FILE = os.path.expanduser(
    os.getenv("WATCHTOWER_RELAY_FILE", "~/watchtower/heartbeats/relay.json")
)
RELAY_MAX_AGE_HOURS = 2

_hk_holidays = holidays.HK()
# Last time a json_log probe saw a successful tail, keyed by path (in-memory).
_last_success: dict[str, float] = {}
# Keys whose clock started at a restart, with no success seen since.
_unconfirmed: set[str] = set()


def _ok() -> dict:
    return {"up": True, "error_message": None, "skip": False}


def _bad(reasons: list[str]) -> dict:
    return {"up": False, "error_message": "; ".join(reasons), "skip": False}


def _skip(reason: str) -> dict:
    return {"up": True, "error_message": reason, "skip": True}


def _age_h(epoch: float | None, now: float) -> float | None:
    return None if epoch is None else (now - epoch) / 3600


def _journal(args: list[str]) -> list[str]:
    out = subprocess.run(
        ["journalctl", "--no-pager", *args],
        capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        raise RuntimeError(f"journalctl exit {out.returncode}: {out.stderr.strip()[:200]}")
    return out.stdout.splitlines()


# ─── HSI short-sell monitor ───────────────────────────────────────────────────

_RUN_START = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) HKT\] 開始執行")
_COUNT = re.compile(r"短倉: (\d+)/(\d+)")
_DATA_DATE = re.compile(r"Z-Score sheet 更新：(\d{4}-\d{2}-\d{2})")


def is_hk_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _hk_holidays


def parse_hsi_runs(lines: list[str]) -> list[dict]:
    """Group hsi-monitor journal lines (-o cat) into runs."""
    runs: list[dict] = []
    for line in lines:
        m = _RUN_START.search(line)
        if m:
            start = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=HKT)
            runs.append({"start": start, "count": None, "data_date": None})
            continue
        if not runs:
            continue
        if m := _COUNT.search(line):
            runs[-1]["count"] = int(m.group(1))
        elif m := _DATA_DATE.search(line):
            runs[-1]["data_date"] = m.group(1)
    return runs


def latest_hsi_deadline(now: datetime) -> tuple[datetime, str] | None:
    """Latest 13:00 (midday) or 17:00 (close) HKT deadline at or before now on a trading day."""
    for back in range(0, 15):
        d = (now - timedelta(days=back)).date()
        if not is_hk_trading_day(d):
            continue
        for hour, kind in ((17, "close"), (13, "midday")):
            deadline = datetime(d.year, d.month, d.day, hour, tzinfo=HKT)
            if deadline <= now:
                return deadline, kind
    return None


def evaluate_hsi(runs: list[dict], now: datetime, min_stocks: int) -> dict:
    found = latest_hsi_deadline(now)
    if not found:
        return _skip("no trading-day deadline in the last 15 days")
    deadline, kind = found
    window_start = deadline - timedelta(hours=2)
    day = deadline.date().isoformat()
    in_window = [r for r in runs if window_start <= r["start"] < deadline]
    if not in_window:
        return _bad([f"no {kind} run on {day} before {deadline:%H:%M} HKT"])
    run = in_window[-1]
    reasons = []
    if run["count"] is None:
        reasons.append(f"{kind} run {run['start']:%H:%M} logged no stock count (crashed?)")
    elif run["count"] < min_stocks:
        reasons.append(f"{kind} run scraped {run['count']} stocks (< {min_stocks})")
    if kind == "close" and run["data_date"] != day:
        reasons.append(f"latest data date {run['data_date']} is not {day}")
    return _bad(reasons) if reasons else _ok()


def check_hsi(probe: dict) -> dict:
    # rsyslog keeps weeks of history; the journal is capped at 50 MB (about 2-4 days),
    # which is too short after a long HK holiday.
    marker = f" {probe['syslog_tag']}"
    lines: list[str] = []
    for path in ("/var/log/syslog.1", "/var/log/syslog"):
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as f:
                lines += [l for l in f if marker in l]
    return evaluate_hsi(parse_hsi_runs(lines), datetime.now(HKT), probe.get("min_stocks", 47))


# ─── systemd journal freshness ────────────────────────────────────────────────

def evaluate_journal_fresh(lines: list[str], pattern: str, now: float, max_age_hours: float) -> dict:
    """lines are journalctl -o short-unix output: '<epoch> host proc[pid]: message'."""
    last = None
    for line in lines:
        if pattern in line:
            try:
                last = float(line.split(" ", 1)[0])
            except ValueError:
                continue
    if last is None:
        return _bad([f"no '{pattern}' line in the last {max_age_hours + 1:g} h"])
    age = _age_h(last, now)
    if age > max_age_hours:
        return _bad([f"last '{pattern}' {age:.1f} h ago (> {max_age_hours:g} h)"])
    return _ok()


def check_journal_fresh(probe: dict) -> dict:
    hours = probe["max_age_hours"]
    lines = _journal(["-u", probe["unit"], "--since", f"-{int(hours) + 1}h", "-o", "short-unix"])
    return evaluate_journal_fresh(lines, probe["pattern"], time.time(), hours)


# ─── Multi-line JSON run logs (SmartFlow shadow collectors) ──────────────────

_TOP_STATUS = re.compile(r'^  "status": "(\w+)"', re.M)


def evaluate_json_log(tail: str, mtime: float, now: float, max_age_hours: float, key: str) -> dict:
    """A run is good when the log ends with a complete JSON block whose top-level status is success."""
    lines = [l for l in tail.splitlines() if l.strip()]
    statuses = _TOP_STATUS.findall(tail)
    tail_ok = bool(lines) and lines[-1] == "}" and bool(statuses) and statuses[-1] == "success"
    if tail_ok:
        _last_success[key] = mtime
        _unconfirmed.discard(key)
    elif key not in _last_success:
        # First sight of a failing tail after a restart: start the clock now.
        _last_success[key] = now
        _unconfirmed.add(key)
    age = _age_h(_last_success[key], now)
    if age > max_age_hours:
        last_state = statuses[-1] if statuses else "no status"
        return _bad([f"no successful run for {age:.1f} h (> {max_age_hours:g} h); last block: {last_state}"])
    if key in _unconfirmed:
        # Reporting up here would falsely resolve an alert opened before the restart.
        return _skip("failing log tail, no success seen since restart")
    return _ok()


def check_json_log(probe: dict) -> dict:
    path = os.path.expanduser(probe["log_path"])
    if not os.path.exists(path):
        return _bad([f"log file missing: {probe['log_path']}"])
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - 16384))
        tail = f.read().decode("utf-8", errors="replace")
    return evaluate_json_log(tail, os.path.getmtime(path), time.time(), probe["max_age_hours"], path)


# ─── Relay (Mac mini, AWS Lambda, Windows tasks via the Windows relay) ───────

def load_relay(path: str = RELAY_FILE) -> tuple[dict | None, str | None]:
    """Return (data, problem). problem is None when the relay file is present and fresh."""
    if not os.path.exists(path):
        return None, "relay file missing"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    age = _age_h(data.get("generated_at"), time.time())
    if age is None or age > RELAY_MAX_AGE_HOURS:
        return data, f"relay last reported {age if age is None else round(age, 1)} h ago"
    return data, None


def evaluate_relay_heartbeat(data: dict | None, problem: str | None) -> dict:
    if problem:
        return _bad([f"{problem} (Windows PC off or WatchtowerRelay task failing)"])
    reasons = [
        f"{section} unreachable: {data[section].get('error')}"
        for section in ("mac", "aws", "windows", "github")
        if not data.get(section, {}).get("ok")
    ]
    return _bad(reasons) if reasons else _ok()


def _relay_section(data: dict | None, problem: str | None, section: str) -> tuple[dict | None, dict | None]:
    if problem:
        return None, _skip(f"relay stale: {problem}")
    sec = data.get(section) or {}
    if not sec.get("ok"):
        return None, _skip(f"relay {section} section unavailable (see watchtower-relay)")
    return sec, None


def evaluate_relay_launchd(probe: dict, data: dict | None, problem: str | None, now: float) -> dict:
    until = probe.get("active_until")
    if until and datetime.fromisoformat(until) <= datetime.now(HKT):
        return _skip(f"job past its end date {until}")
    mac, skip = _relay_section(data, problem, "mac")
    if skip:
        return skip
    job = mac.get("jobs", {}).get(probe["label"])
    if not job or not job.get("loaded"):
        return _bad(["launchd job not loaded"])
    reasons = []
    if probe.get("expect_running") and not job.get("running"):
        reasons.append(f"not running (last exit {job.get('last_exit')})")
    elif job.get("last_exit") not in (0, None):
        reasons.append(f"last exit {job['last_exit']}")
    age = _age_h(job.get("log_mtime"), now)
    if age is None:
        reasons.append("stdout log missing")
    elif age > probe["max_age_hours"]:
        reasons.append(f"stdout log {age:.1f} h old (> {probe['max_age_hours']:g} h)")
    if probe.get("asset_radar"):
        reasons += _asset_radar_reasons(mac.get("asset_radar") or {})
    return _bad(reasons) if reasons else _ok()


def _asset_radar_reasons(ar: dict) -> list[str]:
    reasons = []
    if ar.get("error"):
        return [f"run summary unreadable: {ar['error']}"]
    yesterday = (datetime.now(HKT).date() - timedelta(days=1)).isoformat()
    if (ar.get("date") or "") < yesterday:
        reasons.append(f"latest run date {ar.get('date')}")
    if ar.get("status") != "complete":
        reasons.append(f"run status {ar.get('status')}")
    if not ar.get("observations_complete"):
        reasons.append("observations incomplete")
    ran, ok = ar.get("tools_ran"), ar.get("tools_ok")
    if ran is None or ok is None or ok < ran:
        reasons.append(f"providers ok {ok}/{ran}")
    return reasons


def evaluate_relay_lambda(data: dict | None, problem: str | None) -> dict:
    aws, skip = _relay_section(data, problem, "aws")
    if skip:
        return skip
    sa = aws.get("short_alpha") or {}
    reasons = []
    if not sa.get("scans_14d"):
        reasons.append("no 'Full scan done' in 14 days")
    elif not sa.get("max_candidates_14d"):
        reasons.append(f"0 watch candidates in all {sa['scans_14d']} scans over 14 days")
    if sa.get("price_unavailable_4d"):
        reasons.append(f"'Price check unavailable' x{sa['price_unavailable_4d']} in 4 days")
    return _bad(reasons) if reasons else _ok()


# Task Scheduler result while the task is still running.
_TASK_RUNNING = 0x41301


def _task_epoch(last_run: str | None) -> float | None:
    """schtasks 'Last Run Time' on the PC, for example '11/4/2026 7:46:54 AM' (HKT)."""
    try:
        return datetime.strptime(last_run or "", "%m/%d/%Y %I:%M:%S %p").replace(tzinfo=HKT).timestamp()
    except ValueError:
        return None


def evaluate_relay_win_task(probe: dict, data: dict | None, problem: str | None, now: float) -> dict:
    win, skip = _relay_section(data, problem, "windows")
    if skip:
        return skip
    task = win.get("tasks", {}).get(probe["task_name"])
    if not task:
        return _bad(["scheduled task not found"])
    if task.get("last_result") == _TASK_RUNNING:
        return _skip("task is running; no finished result to judge")
    if task.get("last_result") != 0:
        return _bad([f"last result {task.get('last_result')} (last run {task.get('last_run')})"])
    age = _age_h(_task_epoch(task.get("last_run")), now)
    if age is None:
        return _bad([f"last run time unreadable: {task.get('last_run')}"])
    if age > probe["max_age_hours"]:
        return _bad([f"last run {age:.0f} h ago (> {probe['max_age_hours']:g} h)"])
    return _ok()


def evaluate_relay_gha(probe: dict, data: dict | None, problem: str | None, now: float) -> dict:
    gh, skip = _relay_section(data, problem, "github")
    if skip:
        return skip
    run = gh.get("runs", {}).get(probe["name"])
    if not run:
        return _bad(["no completed workflow run found"])
    reasons = []
    if run.get("conclusion") not in ("success", "skipped"):
        reasons.append(f"latest run conclusion {run.get('conclusion')}")
    age = _age_h(run.get("created_at"), now)
    if age > probe["max_age_hours"]:
        reasons.append(f"latest run {age:.1f} h old (> {probe['max_age_hours']:g} h)")
    return _bad(reasons) if reasons else _ok()


def check_relay(probe: dict) -> dict:
    data, problem = load_relay()
    kind = probe["check"]
    if kind == "relay_heartbeat":
        return evaluate_relay_heartbeat(data, problem)
    if kind == "relay_launchd":
        return evaluate_relay_launchd(probe, data, problem, time.time())
    if kind == "relay_lambda":
        return evaluate_relay_lambda(data, problem)
    if kind == "relay_win_task":
        return evaluate_relay_win_task(probe, data, problem, time.time())
    if kind == "relay_gha":
        return evaluate_relay_gha(probe, data, problem, time.time())
    raise ValueError(f"unknown relay check {kind}")


_CHECKS = {
    "hsi": check_hsi,
    "journal_fresh": check_journal_fresh,
    "json_log": check_json_log,
}


async def run_output_probe(probe: dict) -> dict:
    fn = _CHECKS.get(probe["check"], check_relay)
    try:
        return await asyncio.to_thread(fn, probe)
    except Exception as e:
        return _bad([f"check error: {e}"])
