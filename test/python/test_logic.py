import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("osw", HERE / "watch.py")
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


def make_config(tmp: Path):
    return SimpleNamespace(
        webhook="https://example.invalid/hook",
        plan="go-plus",
        step=1.0,
        state_dir=tmp,
        startup_message=True,
        reset_message=True,
        console_url="https://example.invalid/console",
        limits=lambda: {"deepseek-v4.1-flash": 200.0},
        labels=lambda: {"deepseek-v4.1-flash": "DeepSeek V4.1 Flash"},
        channels=lambda: watch.notify.Channels(mattermost_url="https://example.invalid/hook"),
    )


def make_stats(total: float, end_day: int = 27):
    return {
        "windows": {
            "rolling": {"percent": 0.0, "status": "ok", "resets_at": None},
            "weekly": {
                "percent": 6.0,
                "status": "ok",
                "resets_at": datetime(2026, 11, 9, tzinfo=timezone.utc),
            },
            "monthly": {
                "percent": 3.0,
                "status": "ok",
                "resets_at": datetime(2026, 11, end_day, 14, 9, 59, tzinfo=timezone.utc),
            },
        },
        "days": {"2026-11-08": total},
        "period_start": datetime(2026, 10, 27, 14, 9, 59, tzinfo=timezone.utc),
        "period_end": datetime(2026, 11, end_day, 14, 9, 59, tzinfo=timezone.utc),
        "period_total": total,
        "today": 1.45,
        "last7": 3.54,
        "models": [
            {
                "provider": "opencode-go",
                "model": "deepseek-v4.1-flash",
                "cost": 3.80,
                "requests": 2840,
            },
        ],
        "closest": {
            "provider": "opencode-go",
            "model": "deepseek-v4.1-flash",
            "cost": 3.80,
            "requests": 2840,
            "limit": 200.0,
            "remaining": 196.2,
        },
        "coverage_gap": False,
    }


class PollTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.config = make_config(self.dir)
        self.sent = []
        self.collect_value = 5.0
        self.post_ok = True
        self._orig_collect = watch.collect
        self._orig_deliver = watch.deliver

        def fake_collect(config, stored):
            return make_stats(self.collect_value)

        def fake_deliver(config, text, color):
            if self.post_ok:
                self.sent.append(text)
                return [watch.notify.Result("mattermost", True)]
            return [watch.notify.Result("mattermost", False, "down")]

        watch.collect = fake_collect
        watch.deliver = fake_deliver

    def tearDown(self):
        watch.collect = self._orig_collect
        watch.deliver = self._orig_deliver
        self.tmp.cleanup()

    def state(self):
        return json.loads((self.dir / "state.json").read_text())

    def run_poll(self):
        return watch.poll(self.config)

    def test_initializes_without_backfill_spam(self):
        self.assertEqual(self.run_poll(), 0)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("watcher started", self.sent[0])
        self.assertEqual(self.state()["last_level"], 5)
        self.assertTrue(self.state()["initialized"])

    def test_alerts_once_per_dollar(self):
        self.run_poll()
        self.sent.clear()

        self.collect_value = 5.4
        self.run_poll()
        self.assertEqual(self.sent, [])

        self.collect_value = 6.05
        self.run_poll()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("$6.00", self.sent[0])
        self.assertEqual(self.state()["last_level"], 6)

        self.run_poll()
        self.assertEqual(len(self.sent), 1)

    def test_multiple_crossed_thresholds_in_one_message(self):
        self.run_poll()
        self.sent.clear()
        self.collect_value = 8.2
        self.run_poll()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("$5.00", self.sent[0])
        self.assertIn("$8.00", self.sent[0])
        self.assertEqual(self.state()["last_level"], 8)

    def test_failed_delivery_keeps_threshold_pending(self):
        self.run_poll()
        self.sent.clear()

        self.post_ok = False
        self.collect_value = 7.5
        self.assertEqual(self.run_poll(), 1)
        self.assertEqual(self.state()["last_level"], 5)

        self.post_ok = True
        self.run_poll()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.state()["last_level"], 7)

    def test_period_reset_rearms_thresholds(self):
        self.run_poll()
        self.sent.clear()

        self.collect_value = 0.2
        orig = watch.collect
        watch.collect = lambda config, stored: (
            make_stats(0.2, end_day=27)
            | {"period_end": datetime(2026, 12, 27, 14, 9, 59, tzinfo=timezone.utc)}
        )
        self.run_poll()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("billing period reset", self.sent[0])
        self.assertEqual(self.state()["last_level"], 0)
        watch.collect = orig

    def test_missing_channel_exits_two(self):
        self.config.channels = lambda: watch.notify.Channels()
        self.assertEqual(self.run_poll(), 2)
        self.assertFalse((self.dir / "state.json").exists())

    def test_collection_failure_exits_one(self):
        def explode(config, stored):
            raise RuntimeError("api down")

        watch.collect = explode
        self.assertEqual(self.run_poll(), 1)
        self.assertFalse((self.dir / "state.json").exists())

    def test_startup_delivery_failure_exits_one(self):
        self.post_ok = False
        self.assertEqual(self.run_poll(), 1)
        self.assertFalse((self.dir / "state.json").exists())

    def test_partial_delivery_still_initializes(self):
        watch.deliver = lambda config, text, color: [
            watch.notify.Result("mattermost", True),
            watch.notify.Result("slack", False, "down"),
        ]
        self.assertEqual(self.run_poll(), 0)
        self.assertTrue(self.state()["initialized"])

    def test_reset_delivery_failure_exits_one(self):
        self.run_poll()
        self.assertEqual(self.state()["last_level"], 5)

        orig = watch.collect
        watch.collect = lambda config, stored: (
            make_stats(0.0, end_day=27)
            | {"period_end": datetime(2026, 12, 27, 14, 9, 59, tzinfo=timezone.utc)}
        )
        self.post_ok = False
        self.assertEqual(self.run_poll(), 1)
        self.assertEqual(self.state()["last_level"], 5)
        watch.collect = orig


class MessageTests(unittest.TestCase):
    def test_message_contains_dollars_and_remaining(self):
        config = make_config(Path("/tmp/unused"))
        text = watch.build_message(make_stats(6.05), 5.0, 6.0, config)
        self.assertIn("$6.05", text)
        self.assertIn("97% left", text)
        self.assertIn("$196.20 left of $200.00", text)
        self.assertIn("DeepSeek V4.1 Flash", text)


if __name__ == "__main__":
    unittest.main()
