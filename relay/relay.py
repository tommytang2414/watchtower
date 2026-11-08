"""Watchtower relay — runs on the Windows PC as scheduled task WatchtowerRelay.

Collects raw status facts that the VPS cannot reach (Mac mini launchd jobs,
the short-alpha Lambda's CloudWatch logs, Windows scheduled tasks) and writes
them to the VPS at ~/watchtower/heartbeats/relay.json. Read-only everywhere;
Watchtower applies the rules (probes/output_checks.py).

Uses only existing access: the pinned Mac SSH key, the `vps` SSH alias and the
default AWS CLI profile. Connection settings come from RELAY_* keys in the
untracked monitor/.env so no LAN address is committed.

Run: pythonw.exe relay\\relay.py   (add --print to print instead of upload)
"""
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = Path(os.getenv("LOCALAPPDATA", ".")) / "watchtower-relay" / "last-run.log"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

MAC_LABELS = [
    "com.smartflow.research.daily",
    "com.asset-radar.daily",
    "com.vulnpulse.scan",
    "com.hk-civic-newsroom.daily",
    "com.meme-agent.research",
]
WINDOWS_TASKS = ["DevOpsScanner"]
LAMBDA_LOG_GROUP = "/aws/lambda/short-alpha-agent"

# Runs on the Mac via `python3 -`. Prints one JSON object of aggregate facts only.
MAC_SCRIPT = r'''
import json, os, re, subprocess
labels = %LABELS%
uid = os.getuid()
jobs = {}
for label in labels:
    p = subprocess.run(["launchctl", "print", f"gui/{uid}/{label}"], capture_output=True, text=True)
    if p.returncode != 0:
        jobs[label] = {"loaded": False}
        continue
    t = p.stdout
    state = re.search(r"^\tstate = (.+)$", t, re.M)
    code = re.search(r"last exit code = (-?\d+)", t)
    out = re.search(r"^\tstdout path = (.+)$", t, re.M)
    path = out.group(1).strip() if out else None
    jobs[label] = {
        "loaded": True,
        "running": bool(state and state.group(1).strip() == "running"),
        "last_exit": int(code.group(1)) if code else None,
        "log_mtime": os.path.getmtime(path) if path and os.path.exists(path) else None,
    }
ar = {}
try:
    base = os.path.expanduser("~/Applications/asset-radar/data/daily")
    days = sorted(d for d in os.listdir(base) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d))
    if days:
        day = os.path.join(base, days[-1])
        ledger = json.load(open(os.path.join(day, "ledger.json")))
        scan = json.load(open(os.path.join(day, "scan.json")))
        ar = {
            "date": ledger.get("date"),
            "status": ledger.get("status"),
            "observations_complete": bool(scan.get("observations_complete")),
            "tools_ran": len(scan.get("tools_ran") or []),
            "tools_ok": len(scan.get("tools_ok") or []),
        }
    else:
        ar = {"error": "no daily run folders"}
except Exception as e:
    ar = {"error": type(e).__name__}
print(json.dumps({"jobs": jobs, "asset_radar": ar}))
'''.replace("%LABELS%", json.dumps(MAC_LABELS))


def load_settings() -> dict:
    settings = {"RELAY_VPS_SSH_TARGET": "vps", "RELAY_AWS_REGION": "ap-southeast-1"}
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("RELAY_") and "=" in line:
                k, v = line.split("=", 1)
                settings[k.strip()] = v.strip()
    settings.update({k: v for k, v in os.environ.items() if k.startswith("RELAY_")})
    return settings


def run(cmd: list[str], stdin: str | None = None, timeout: int = 60) -> str:
    exe = shutil.which(cmd[0]) or cmd[0]
    p = subprocess.run(
        [exe, *cmd[1:]], input=stdin, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, creationflags=NO_WINDOW,
    )
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exit {p.returncode}: {(p.stderr or p.stdout).strip()[:200]}")
    return p.stdout


def collect_mac(s: dict) -> dict:
    target = s.get("RELAY_MAC_SSH_TARGET")
    if not target:
        raise RuntimeError("RELAY_MAC_SSH_TARGET not set")
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=yes",
           "-o", "IdentitiesOnly=yes"]
    if s.get("RELAY_MAC_KNOWN_HOSTS"):
        cmd += ["-o", f"UserKnownHostsFile={s['RELAY_MAC_KNOWN_HOSTS']}"]
    if s.get("RELAY_MAC_SSH_KEY"):
        cmd += ["-i", s["RELAY_MAC_SSH_KEY"]]
    out = run(cmd + [target, "python3 -"], stdin=MAC_SCRIPT, timeout=60)
    return {"ok": True, **json.loads(out)}


def _filter_messages(region: str, pattern: str, start_ms: int) -> list[str]:
    out = run(["aws", "logs", "filter-log-events", "--region", region, "--log-group-name", LAMBDA_LOG_GROUP,
               "--start-time", str(start_ms), "--filter-pattern", pattern,
               "--query", "events[].message", "--output", "json"], timeout=120)
    return json.loads(out or "[]") or []


def collect_aws(s: dict) -> dict:
    region = s["RELAY_AWS_REGION"]
    now_ms = int(time.time() * 1000)
    scans = _filter_messages(region, '"Full scan done"', now_ms - 14 * 86400 * 1000)
    counts = [int(m.group(1)) for msg in scans if (m := re.search(r"Full scan done: (\d+) watch candidates", msg))]
    # 4 days so a Monday-morning check still sees Friday's market-hours runs.
    price = _filter_messages(region, '"Price check unavailable"', now_ms - 4 * 86400 * 1000)
    return {"ok": True, "short_alpha": {
        "scans_14d": len(counts),
        "max_candidates_14d": max(counts) if counts else 0,
        "price_unavailable_4d": len(price),
    }}


def collect_windows() -> dict:
    tasks = {}
    for name in WINDOWS_TASKS:
        try:
            out = run(["schtasks", "/query", "/tn", name, "/fo", "csv", "/v"], timeout=30)
            row = next(csv.DictReader(io.StringIO(out)))
            tasks[name] = {"last_result": int(row["Last Result"]), "last_run": row["Last Run Time"]}
        except Exception as e:
            tasks[name] = None if "cannot find" in str(e).lower() else {"last_result": None, "last_run": str(e)[:100]}
    return {"ok": True, "tasks": {k: v for k, v in tasks.items() if v is not None}}


def section(fn, *args) -> dict:
    try:
        return fn(*args)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def main() -> int:
    s = load_settings()
    report = {
        "relay_version": 1,
        "generated_at": time.time(),
        "mac": section(collect_mac, s),
        "aws": section(collect_aws, s),
        "windows": section(collect_windows),
    }
    payload = json.dumps(report, indent=1)
    if "--print" in sys.argv:
        print(payload)
        return 0
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", s["RELAY_VPS_SSH_TARGET"],
             "mkdir -p ~/watchtower/heartbeats && cat > ~/watchtower/heartbeats/relay.json.tmp"
             " && mv ~/watchtower/heartbeats/relay.json.tmp ~/watchtower/heartbeats/relay.json"],
            stdin=payload, timeout=60)
        status = "uploaded"
    except Exception as e:
        status = f"upload failed: {e}"
    LOG_FILE.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {status}\n{payload}\n", encoding="utf-8")
    return 0 if status == "uploaded" else 1


if __name__ == "__main__":
    sys.exit(main())
