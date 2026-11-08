"""Rules and alert lifecycle for output probes. Run from the repo root:

    python -m unittest discover -s tests
"""
import asyncio
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import main
import storage
from probes import output_checks as oc

HOUR = 3600
NOW = 1_800_000_000.0


def run_at(hour: int, minute: int = 15, count: int | None = 49, data_date: str | None = None) -> dict:
    return {"start": datetime(2026, 11, 6, hour, minute, tzinfo=oc.HKT), "count": count, "data_date": data_date}


def relay(**sections) -> dict:
    base = {"generated_at": NOW, "mac": {"ok": True}, "aws": {"ok": True},
            "windows": {"ok": True}, "github": {"ok": True}}
    return {**base, **sections}


class HsiRules(unittest.TestCase):
    # Friday 2026-11-06, a Hong Kong trading day.
    MIDDAY = datetime(2026, 11, 6, 13, 30, tzinfo=oc.HKT)
    CLOSE = datetime(2026, 11, 6, 17, 30, tzinfo=oc.HKT)

    def test_good_midday_run(self):
        self.assertTrue(oc.evaluate_hsi([run_at(12)], self.MIDDAY, 47)["up"])

    def test_missing_run_alerts(self):
        self.assertFalse(oc.evaluate_hsi([], self.MIDDAY, 47)["up"])

    def test_partial_scrape_alerts(self):
        result = oc.evaluate_hsi([run_at(12, count=30)], self.MIDDAY, 47)
        self.assertFalse(result["up"])
        self.assertIn("30 stocks", result["error_message"])

    def test_close_data_must_be_today(self):
        self.assertFalse(oc.evaluate_hsi([run_at(16, data_date="2026-11-05")], self.CLOSE, 47)["up"])
        self.assertTrue(oc.evaluate_hsi([run_at(16, data_date="2026-11-06")], self.CLOSE, 47)["up"])

    def test_sunday_judges_friday(self):
        sunday = datetime(2026, 11, 8, 10, 0, tzinfo=oc.HKT)
        self.assertTrue(oc.evaluate_hsi([run_at(16, data_date="2026-11-06")], sunday, 47)["up"])


class JournalAndLogRules(unittest.TestCase):
    def setUp(self):
        oc._last_success.clear()
        oc._unconfirmed.clear()

    def test_journal_freshness(self):
        line = f"{NOW - HOUR} host proc[1]: Running checks"
        self.assertTrue(oc.evaluate_journal_fresh([line], "Running checks", NOW, 2)["up"])
        self.assertFalse(oc.evaluate_journal_fresh([line], "Running checks", NOW + 2 * HOUR, 2)["up"])
        self.assertFalse(oc.evaluate_journal_fresh([], "Running checks", NOW, 2)["up"])

    GOOD = '{\n  "status": "success",\n  "results": []\n}\n'
    BAD = '{\n  "status": "failed",\n  "results": []\n}\n'

    def test_json_log_success_then_stale(self):
        self.assertTrue(oc.evaluate_json_log(self.GOOD, NOW, NOW, 2, "k")["up"])
        self.assertFalse(oc.evaluate_json_log(self.GOOD, NOW, NOW + 3 * HOUR, 2, "k")["up"])

    def test_json_log_failing_after_a_success_alerts_at_limit(self):
        oc.evaluate_json_log(self.GOOD, NOW, NOW, 2, "k")
        self.assertTrue(oc.evaluate_json_log(self.BAD, NOW + HOUR, NOW + HOUR, 2, "k")["up"])
        self.assertFalse(oc.evaluate_json_log(self.BAD, NOW + 3 * HOUR, NOW + 3 * HOUR, 2, "k")["up"])

    def test_json_log_failing_at_restart_does_not_report_up(self):
        first = oc.evaluate_json_log(self.BAD, NOW, NOW, 2, "k")
        self.assertTrue(first["skip"], "must not resolve an alert opened before the restart")
        self.assertFalse(oc.evaluate_json_log(self.BAD, NOW, NOW + 3 * HOUR, 2, "k")["up"])

    def test_json_log_first_success_after_restart_clears_the_hold(self):
        oc.evaluate_json_log(self.BAD, NOW, NOW, 2, "k")
        result = oc.evaluate_json_log(self.GOOD, NOW + 60, NOW + 60, 2, "k")
        self.assertTrue(result["up"])
        self.assertFalse(result["skip"])


class RelayRules(unittest.TestCase):
    LAUNCHD = {"label": "job", "max_age_hours": 26}

    def launchd(self, job: dict, probe: dict | None = None) -> dict:
        data = relay(mac={"ok": True, "jobs": {"job": job}})
        return oc.evaluate_relay_launchd(probe or self.LAUNCHD, data, None, NOW)

    def test_stale_relay_alerts_once_and_dependents_skip(self):
        self.assertFalse(oc.evaluate_relay_heartbeat(relay(), "relay last reported 3.0 h ago")["up"])
        self.assertTrue(oc.evaluate_relay_lambda(relay(), "relay last reported 3.0 h ago")["skip"])
        self.assertTrue(oc.evaluate_relay_launchd(self.LAUNCHD, relay(), "stale", NOW)["skip"])
        self.assertTrue(oc.evaluate_relay_win_task({"task_name": "t", "max_age_hours": 1}, relay(), "stale", NOW)["skip"])
        self.assertTrue(oc.evaluate_relay_gha({"name": "g", "max_age_hours": 1}, relay(), "stale", NOW)["skip"])

    def test_unreachable_section_alerts_only_on_the_relay_probe(self):
        data = relay(mac={"ok": False, "error": "timeout"})
        self.assertFalse(oc.evaluate_relay_heartbeat(data, None)["up"])
        self.assertTrue(oc.evaluate_relay_launchd(self.LAUNCHD, data, None, NOW)["skip"])

    def test_launchd_exit_and_staleness(self):
        fresh = {"loaded": True, "last_exit": 0, "log_mtime": NOW - HOUR}
        self.assertTrue(self.launchd(fresh)["up"])
        self.assertIn("last exit 1", self.launchd({**fresh, "last_exit": 1})["error_message"])
        self.assertIn("old", self.launchd({**fresh, "log_mtime": NOW - 30 * HOUR})["error_message"])
        self.assertFalse(self.launchd({"loaded": False})["up"])

    def test_asset_radar_needs_a_complete_run(self):
        today = datetime.now(oc.HKT).date().isoformat()
        good = {"date": today, "status": "complete", "observations_complete": True, "tools_ran": 21, "tools_ok": 21}
        self.assertEqual(oc._asset_radar_reasons(good), [])
        self.assertTrue(oc._asset_radar_reasons({**good, "status": "partial"}))
        self.assertTrue(oc._asset_radar_reasons({**good, "tools_ok": 19}))
        old = (datetime.now(oc.HKT).date() - timedelta(days=3)).isoformat()
        self.assertTrue(oc._asset_radar_reasons({**good, "date": old}))

    def lambda_result(self, **short_alpha) -> dict:
        return oc.evaluate_relay_lambda(relay(aws={"ok": True, "short_alpha": short_alpha}), None)

    def test_lambda_range(self):
        self.assertTrue(self.lambda_result(scans_14d=10, max_candidates_14d=2, price_unavailable_4d=0)["up"])
        zero = self.lambda_result(scans_14d=10, max_candidates_14d=0, price_unavailable_4d=0)
        self.assertIn("0 watch candidates", zero["error_message"])
        self.assertFalse(self.lambda_result(scans_14d=0, max_candidates_14d=0, price_unavailable_4d=0)["up"])
        self.assertFalse(self.lambda_result(scans_14d=10, max_candidates_14d=2, price_unavailable_4d=1)["up"])

    def win_task(self, last_result, last_run: str) -> dict:
        probe = {"task_name": "t", "max_age_hours": 14 * 24}
        data = relay(windows={"ok": True, "tasks": {"t": {"last_result": last_result, "last_run": last_run}}})
        when = datetime(2026, 11, 8, 12, 0, tzinfo=oc.HKT).timestamp()
        return oc.evaluate_relay_win_task(probe, data, None, when)

    def test_windows_task(self):
        recent = "11/4/2026 7:46:54 AM"
        self.assertTrue(self.win_task(0, recent)["up"])
        self.assertFalse(self.win_task(2, recent)["up"])
        self.assertTrue(self.win_task(0x41301, recent)["skip"], "a running task must not resolve an open alert")
        self.assertIn("ago", self.win_task(0, "10/1/2026 7:46:54 AM")["error_message"])
        self.assertIn("unreadable", self.win_task(0, "N/A")["error_message"])

    def test_github_run(self):
        probe = {"name": "g", "max_age_hours": 50}
        def result(conclusion, age_h):
            run = {"conclusion": conclusion, "created_at": NOW - age_h * HOUR}
            return oc.evaluate_relay_gha(probe, relay(github={"ok": True, "runs": {"g": run}}), None, NOW)
        self.assertTrue(result("success", 1)["up"])
        self.assertFalse(result("failure", 1)["up"])
        self.assertFalse(result("success", 60)["up"])


class AlertLifecycle(unittest.TestCase):
    """Real main.check_and_alert, real relay file reader and a throwaway SQLite database."""

    PROBE = {"name": "watchtower-relay", "type": "output", "check": "relay_heartbeat", "target": "test",
             "interval_minutes": 15, "alert_on": ["bad_output"]}

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.relay_path = os.path.join(self.dir.name, "relay.json")
        patches = [
            patch.object(storage, "DATABASE_PATH", os.path.join(self.dir.name, "t.db")),
            patch.object(oc, "load_relay", lambda: self.real_load(self.relay_path)),
            patch.object(main, "send_alert", AsyncMock(return_value=True)),
            patch.object(main, "send_recovered", AsyncMock()),
        ]
        self.real_load = oc.load_relay
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        asyncio.run(storage.init_db())

    def beat(self, age_hours: float):
        report = {"generated_at": time.time() - age_hours * HOUR,
                  "mac": {"ok": True}, "aws": {"ok": True}, "windows": {"ok": True}, "github": {"ok": True}}
        with open(self.relay_path, "w", encoding="utf-8") as f:
            json.dump(report, f)

    def check(self, probe: dict | None = None):
        asyncio.run(main.check_and_alert(probe or self.PROBE))

    def test_stale_heartbeat_alerts_once_then_recovers(self):
        self.beat(0)
        self.check()
        main.send_alert.assert_not_awaited()

        self.beat(3)
        for _ in range(3):
            self.check()
        self.assertEqual(main.send_alert.await_count, 1)
        main.send_recovered.assert_not_awaited()

        self.beat(0)
        self.check()
        self.assertEqual(main.send_recovered.await_count, 1)
        self.assertEqual(main.send_alert.await_count, 1)

        self.beat(3)
        self.check()
        self.assertEqual(main.send_alert.await_count, 2, "a new outage alerts again")

    def test_undelivered_alert_retries(self):
        self.beat(3)
        main.send_alert.return_value = False
        self.check()
        self.check()
        self.assertEqual(main.send_alert.await_count, 2)

    def test_skip_neither_alerts_nor_resolves(self):
        probe = {**self.PROBE, "name": "known-bad", "check": "relay_lambda"}
        bad = {"up": False, "error_message": "0 candidates", "skip": False}
        with patch.object(main, "run_probe", AsyncMock(return_value=bad)):
            for _ in range(5):
                self.check(probe)
        self.assertEqual(main.send_alert.await_count, 1)

        self.beat(3)
        self.check(probe)
        self.assertEqual(main.send_alert.await_count, 1)
        main.send_recovered.assert_not_awaited()
        self.assertTrue(asyncio.run(storage.get_unresolved_alert("known-bad", "bad_output")))


if __name__ == "__main__":
    unittest.main()
