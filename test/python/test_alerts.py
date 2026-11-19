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
        "labels": lambda: {},
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
        "days": {},
        "period_start": datetime(2026, 10, 27, 14, 9, tzinfo=timezone.utc),
        "period_end": datetime(2026, 11, 27, 14, 9, tzinfo=timezone.utc),
        "period_total": total,
        "today": 1.0,
        "last7": 2.0,
        "models": [],
        "closest": None,
        "coverage_gap": False,
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

    def test_crossing_is_reported_once_and_rearms_after_reset(self):
        state = {}
        watch.baseline_percent(stats(monthly=3.0), state, self.cfg.percent_thresholds)
        crossings = watch.percent_crossings(self.cfg, stats(monthly=52.0), state)
        self.assertEqual([crossing["window"] for crossing in crossings], ["monthly"])
        text = watch.build_alert_message(stats(monthly=52.0), crossings, self.cfg)
        self.assertIn("Monthly window at 52% (crossed 50%)", text)

        watch.apply_crossings(state, crossings)
        self.assertEqual(watch.percent_crossings(self.cfg, stats(monthly=52.0), state), [])

        state["percent_alerts"]["monthly"]["reset"] = "stale"
        self.assertEqual(len(watch.percent_crossings(self.cfg, stats(monthly=52.0), state)), 1)

    def test_spend_and_percent_crossings_share_one_message(self):
        state = {}
        watch.baseline_percent(stats(weekly=3.0), state, self.cfg.percent_thresholds)
        triggers = [watch.spend_trigger(54.0, 55.0, 55.31)]
        triggers.extend(watch.percent_crossings(self.cfg, stats(weekly=52.0), state))
        text = watch.build_alert_message(stats(weekly=52.0, total=55.31), triggers, self.cfg)
        self.assertIn("2 thresholds reached", text)
        self.assertIn("$55.31", text)
        self.assertIn("crossed $55.00", text)
        self.assertIn("Weekly window at 52% (crossed 50%)", text)
        self.assertEqual(self.sent, [])

    def test_severity_colour_and_emoji(self):
        triggers = [watch.spend_trigger(1.0, 2.0, 2.0)]
        text = watch.build_alert_message(stats(monthly=82.0), triggers, self.cfg)
        self.assertIn("🔴", text)
        crossed = {"kind": "percent", "window": "weekly", "percent": 52.0, "threshold": 50.0}
        text = watch.build_alert_message(stats(monthly=10.0), [crossed], self.cfg)
        self.assertIn("🟠", text)
        self.assertEqual(watch.alert_severity(stats(monthly=10.0), [crossed]), 52.0)
        self.assertEqual(watch.percent_color(82.0), watch.COLOR_RED)
        self.assertEqual(watch.percent_color(60.0), watch.COLOR_AMBER)
        self.assertEqual(watch.percent_color(80.0), watch.COLOR_AMBER)
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

    def test_baselines_then_alerts_once_with_every_trigger(self):
        state = {}
        cfg = config(self.dir, providers=("openrouter",))
        self.snapshots = [self.snapshot(1.5)]
        self.assertTrue(watch.poll_providers(cfg, state))
        self.assertEqual(self.sent, [])

        self.snapshots = [self.snapshot(5.5)]
        self.assertTrue(watch.poll_providers(cfg, state))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("OpenRouter spend", self.sent[0])
        self.assertIn("crossed $1.00–$5.00", self.sent[0])
        self.assertIn("Budget at 55% (crossed 50%)", self.sent[0])

        self.snapshots = [self.snapshot(5.5)]
        self.assertTrue(watch.poll_providers(cfg, state))
        self.assertEqual(len(self.sent), 1)

    def test_changing_the_step_rebaselines_a_provider(self):
        state = {}
        cfg = config(self.dir, providers=("openrouter",))
        self.snapshots = [self.snapshot(1.5, budget=100.0)]
        watch.poll_providers(cfg, state)
        cfg.step = 5.0
        self.snapshots = [self.snapshot(5.5, budget=100.0)]
        watch.poll_providers(cfg, state)
        self.assertEqual(self.sent, [])
        self.snapshots = [self.snapshot(10.2, budget=100.0)]
        watch.poll_providers(cfg, state)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(state["providers"]["openrouter"]["step"], 5.0)

    def test_provider_body_is_the_same_for_every_trigger(self):
        cfg = config(self.dir, providers=("openrouter",))
        spend = watch.build_provider_alert(
            self.snapshot(5.5), [watch.spend_trigger(5.0, 5.5, 5.5)], cfg
        )
        percent = watch.build_provider_alert(
            self.snapshot(5.5),
            [{"kind": "percent", "percent": 55.0, "threshold": 50.0}],
            cfg,
        )
        self.assertEqual(
            spend.split(watch.notify.SECTION, 1)[1],
            percent.split(watch.notify.SECTION, 1)[1],
        )

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
