import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import notify
import watch


def config(tmp: Path, **extra):
    values = {
        "percent_thresholds": (50.0, 80.0, 95.0),
        "providers": (),
        "alert_log": tmp / "alerts.log",
        "step": 1.0,
        "console_url": "",
        "channels": lambda: notify.Channels(),
        **extra,
    }
    return SimpleNamespace(**values)


def stats(rolling=0.0, weekly=6.0, monthly=3.0, total=5.0):
    return {
        "windows": {
            "rolling": {
                "percent": rolling,
                "resets_at": datetime(2026, 11, 9, 1, tzinfo=timezone.utc),
            },
            "weekly": {
                "percent": weekly,
                "resets_at": datetime(2026, 11, 9, tzinfo=timezone.utc),
            },
            "monthly": {
                "percent": monthly,
                "resets_at": datetime(2026, 11, 27, 14, 9, tzinfo=timezone.utc),
            },
        },
        "period_total": total,
    }


class PercentAlertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = config(self.dir)
        self.sent = []
        self._deliver = watch.deliver
        watch.deliver = lambda cfg, text, color: (
            self.sent.append((text, color)) or [notify.Result("mattermost", True)]
        )

    def tearDown(self):
        watch.deliver = self._deliver
        self.tmp.cleanup()

    def test_baseline_records_crossed_thresholds_without_sending(self):
        state = {}
        watch.baseline_percent(stats(monthly=82.0), state, self.cfg.percent_thresholds)
        self.assertEqual(state["percent_alerts"]["monthly"]["threshold"], 80.0)
        self.assertEqual(self.sent, [])

    def test_crossing_sends_once_and_rearms_after_reset(self):
        state = {}
        watch.baseline_percent(stats(monthly=3.0), state, self.cfg.percent_thresholds)
        self.assertTrue(watch.process_percent_alerts(self.cfg, stats(monthly=52.0), state))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("50% threshold", self.sent[0][0])
        self.assertTrue(watch.process_percent_alerts(self.cfg, stats(monthly=52.0), state))
        self.assertEqual(len(self.sent), 1)

        state["percent_alerts"]["monthly"]["reset"] = "stale"
        watch.process_percent_alerts(self.cfg, stats(monthly=52.0), state)
        self.assertEqual(len(self.sent), 2)

    def test_severity_colour_and_emoji(self):
        text = watch.build_percent_message(stats(monthly=82.0), "monthly", 82.0, 80.0, self.cfg)
        self.assertIn("🚨", text)
        self.assertEqual(watch.percent_color(82.0), watch.COLOR_RED)
        self.assertEqual(watch.percent_color(60.0), watch.COLOR_AMBER)
        self.assertEqual(watch.percent_color(10.0), watch.COLOR_GREEN)


class LogTests(unittest.TestCase):
    def test_appends_one_json_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(Path(tmp))
            watch.log_delivery(
                cfg,
                "threshold",
                "hello",
                [notify.Result("mattermost", True)],
            )
            watch.log_delivery(
                cfg,
                "threshold",
                "again",
                [notify.Result("slack", False, "down")],
            )
            lines = cfg.alert_log.read_text().splitlines()
            self.assertEqual(len(lines), 2)
            record = json.loads(lines[1])
            self.assertEqual(record["kind"], "threshold")
            self.assertFalse(record["channels"][0]["ok"])
            self.assertEqual(record["channels"][0]["error"], "down")


class ProviderPollTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.snapshots = []
        self.errors = []
        self.sent = []
        self._collect = watch.providers.collect
        self._deliver = watch.deliver
        watch.providers.collect = lambda cfg: (self.snapshots, self.errors)
        watch.deliver = lambda cfg, text, color: (
            self.sent.append(text) or [notify.Result("mattermost", True)]
        )

    def tearDown(self):
        watch.providers.collect = self._collect
        watch.deliver = self._deliver
        self.tmp.cleanup()

    def snapshot(self, spend, budget=10.0):
        return watch.providers.Snapshot(
            name="openrouter",
            label="OpenRouter",
            spend=spend,
            budget=budget,
            remaining=budget - spend,
            period_key="lifetime",
            detail="test",
        )

    def test_baselines_then_alerts_on_dollars_and_percent(self):
        state = {}
        cfg = config(self.dir, providers=("openrouter",))
        self.snapshots = [self.snapshot(1.5)]
        self.assertTrue(watch.poll_providers(cfg, state))
        self.assertEqual(self.sent, [])

        self.snapshots = [self.snapshot(5.5)]
        self.assertTrue(watch.poll_providers(cfg, state))
        self.assertEqual(len(self.sent), 2)
        self.assertIn("OpenRouter spend", self.sent[0])
        self.assertIn("usage at 55%", self.sent[1])

        self.snapshots = [self.snapshot(5.5)]
        self.assertTrue(watch.poll_providers(cfg, state))
        self.assertEqual(len(self.sent), 2)

    def test_provider_error_is_reported(self):
        state = {}
        cfg = config(self.dir, providers=("openrouter",))
        self.errors = ["openrouter: missing key"]
        self.assertFalse(watch.poll_providers(cfg, state))

    def test_spend_drop_resets_the_baseline(self):
        state = {}
        cfg = config(self.dir, providers=("openrouter",))
        self.snapshots = [self.snapshot(9.0)]
        watch.poll_providers(cfg, state)
        self.snapshots = [self.snapshot(1.0)]
        watch.poll_providers(cfg, state)
        self.assertEqual(state["providers"]["openrouter"]["last_level"], 1)
        self.snapshots = [self.snapshot(2.0)]
        watch.poll_providers(cfg, state)
        self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main()
