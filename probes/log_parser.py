"""Local log file failure keyword scanner."""
import asyncio
import os
import glob
from datetime import datetime, timezone, timedelta
from typing import Optional


async def run_log_parser_probe(
    log_path: str,
    keywords: list[str],
) -> dict:
    """
    Scan the latest log file in log_path for failure keywords.

    Returns:
        {
            "up": bool,              # True if no keywords found
            "has_failure": bool,
            "matched_keywords": list[str],
            "last_line": str,
            "error_message": str | None,
        }
    """
    result = {
        "up": True,
        "has_failure": False,
        "matched_keywords": [],
        "last_line": None,
        "error_message": None,
    }

    def _fetch():
        if not os.path.isdir(log_path):
            result["error_message"] = f"Log path not found: {log_path}"
            result["up"] = False
            return

        pattern = os.path.join(log_path, "*.log")
        log_files = glob.glob(pattern)

        if not log_files:
            result["error_message"] = f"No .log files found in {log_path}"
            result["up"] = False
            return

        latest_log = max(log_files, key=os.path.getmtime)

        with open(latest_log, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        if not lines:
            result["error_message"] = f"Empty log file: {latest_log}"
            result["up"] = False
            return

        result["last_line"] = lines[-1].strip()

        matched = []
        for line in lines:
            lower = line.lower()
            for kw in keywords:
                if kw.lower() in lower:
                    matched.append(kw)

        if matched:
            result["has_failure"] = True
            result["up"] = False
            result["matched_keywords"] = matched

    try:
        await asyncio.to_thread(_fetch)
    except Exception as e:
        result["error_message"] = f"Error reading log: {e}"
        result["up"] = False

    return result
