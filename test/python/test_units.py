import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import watch


def fake_config(tmp: Path, limits=None, labels=None):
    return SimpleNamespace(
        webhook="https://example.invalid/hook",
        plan="go-plus",
        step=1.0,
        state_dir=tmp,
        startup_message=True,
        reset_message=True,
        console_url="https://example.invalid/console",
        limits=lambda: limits or {},
        labels=lambda: labels or {},
    )


class ConfigTests(unittest.TestCase):
    def test_reads_quoted_values_and_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.env"
            path.write_text(
                "# comment\n"
                'MATTERMOST_WEBHOOK_URL="https://example.invalid/hook?a=1&b=2"\n'
                "PLAN=go\n"
                "THRESHOLD_STEP_USD=2.5\n"
                "STATE_DIR=~/state\n"
                "STARTUP_MESSAGE=false\n",
                encoding="utf-8",
            )
            config = watch.Config(path)
            self.assertEqual(config.webhook, "https://example.invalid/hook?a=1&b=2")
            self.assertEqual(config.plan, "go")
            self.assertEqual(config.step, 2.5)
            self.assertEqual(config.state_dir, Path.home() / "state")
            self.assertFalse(config.startup_message)

    def test_limits_and_labels_follow_the_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            limits = Path(tmp) / "limits.json"
            limits.write_text(
                '{"labels":{"m1":"Model One"},'
                '"go":{"models":{"m1":10}},'
                '"go-plus":{"models":{"m1":20}}}',
                encoding="utf-8",
            )
            path = Path(tmp) / "config.env"
            path.write_text(f"PLAN=go\nLIMITS_FILE={limits}\n", encoding="utf-8")
            config = watch.Config(path)
            self.assertEqual(config.limits(), {"m1": 10.0})
            self.assertEqual(config.labels(), {"m1": "Model One"})

    def test_missing_limits_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.env"
            path.write_text("PLAN=go\nLIMITS_FILE=/nonexistent/limits.json\n", encoding="utf-8")
            config = watch.Config(path)
            self.assertEqual(config.limits(), {})
            self.assertEqual(config.labels(), {})

    def test_rejects_a_non_numeric_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.env"
            path.write_text("THRESHOLD_STEP_USD=lots\n", encoding="utf-8")
            with self.assertRaisesRegex(watch.ConfigError, "must be a number"):
                watch.Config(path)

    def test_rejects_a_non_positive_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.env"
            path.write_text("THRESHOLD_STEP_USD=0\n", encoding="utf-8")
            with self.assertRaisesRegex(watch.ConfigError, "greater than zero"):
                watch.Config(path)

    def test_builds_every_configured_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.env"
            path.write_text(
                "MATTERMOST_WEBHOOK_URL=https://mm.invalid/hook\n"
                "SLACK_WEBHOOK_URL=https://slack.invalid/hook\n"
                "DISCORD_WEBHOOK_URL=https://discord.invalid/hook\n"
                "IRC_HOST=irc.invalid\nIRC_CHANNEL=#alerts\n"
                "SMTP_HOST=smtp.invalid\nEMAIL_FROM=from@example.invalid\n"
                "EMAIL_TO=a@example.invalid, b@example.invalid\n"
                "WHATSAPP_TOKEN=token\nWHATSAPP_PHONE_NUMBER_ID=123\n"
                "WHATSAPP_TO=456\nTELEGRAM_BOT_TOKEN=token\n"
                "TELEGRAM_CHAT_ID=42\nDESKTOP_NOTIFY=true\n",
                encoding="utf-8",
            )
            channels = watch.Config(path).channels()
            self.assertEqual(
                channels.names(),
                [
                    "mattermost",
                    "slack",
                    "discord",
                    "irc",
                    "email",
                    "whatsapp",
                    "telegram",
                    "desktop",
                ],
            )
            self.assertEqual(channels.email_to, ("a@example.invalid", "b@example.invalid"))
            self.assertTrue(channels.irc_tls)

    def test_rejects_an_invalid_irc_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.env"
            path.write_text("IRC_PORT=not-a-port\n", encoding="utf-8")
            with self.assertRaisesRegex(watch.ConfigError, "IRC_PORT"):
                watch.Config(path)

    def test_rejects_invalid_percentage_thresholds(self):
        for value in ("abc", "0,80", "80,100"):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.env"
                path.write_text(f"PERCENT_THRESHOLDS={value}\n", encoding="utf-8")
                with self.assertRaises(watch.ConfigError):
                    watch.Config(path)

    def test_rejects_invalid_provider_budgets(self):
        for name in ("OPENROUTER_BUDGET_USD", "OPENAI_BUDGET_USD"):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.env"
                path.write_text(f"{name}=lots\n", encoding="utf-8")
                with self.assertRaisesRegex(watch.ConfigError, name):
                    watch.Config(path)

    def test_defaults_for_alerts_and_providers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.env"
            path.write_text("", encoding="utf-8")
            config = watch.Config(path)
            self.assertEqual(config.percent_thresholds, (50.0, 80.0, 95.0))
            self.assertEqual(config.providers, ("opencode",))
            self.assertEqual(config.alert_log, config.state_dir / "alerts.log")

    def test_rejects_an_invalid_smtp_security(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.env"
            path.write_text("SMTP_SECURITY=plain\n", encoding="utf-8")
            with self.assertRaisesRegex(watch.ConfigError, "SMTP_SECURITY"):
                watch.Config(path)


class DateTests(unittest.TestCase):
    def test_parse_iso_accepts_zulu_and_naive_values(self):
        self.assertEqual(
            watch.parse_iso("2026-11-27T14:09:59.000Z"),
            datetime(2026, 11, 27, 14, 9, 59, tzinfo=timezone.utc),
        )
        self.assertEqual(
            watch.parse_iso("2026-11-27T14:09:59"),
            datetime(2026, 11, 27, 14, 9, 59, tzinfo=timezone.utc),
        )

    def test_parse_iso_rejects_invalid_values(self):
        self.assertIsNone(watch.parse_iso(None))
        self.assertIsNone(watch.parse_iso(""))
        self.assertIsNone(watch.parse_iso("not a date"))

    def test_subtract_month_handles_short_months(self):
        self.assertEqual(
            watch.subtract_month(datetime(2026, 3, 31, tzinfo=timezone.utc)),
            datetime(2026, 2, 28, tzinfo=timezone.utc),
        )
        self.assertEqual(
            watch.subtract_month(datetime(2024, 3, 31, tzinfo=timezone.utc)),
            datetime(2024, 2, 29, tzinfo=timezone.utc),
        )
        self.assertEqual(
            watch.subtract_month(datetime(2026, 1, 15, tzinfo=timezone.utc)),
            datetime(2025, 12, 15, tzinfo=timezone.utc),
        )


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = fake_config(Path(self.tmp.name), limits={"m1": 10.0})

    def tearDown(self):
        self.tmp.cleanup()

    def test_sums_only_the_billing_period(self):
        now = datetime.now(timezone.utc)
        reset = now + timedelta(days=10)
        start = watch.subtract_month(reset)
        days = {
            (start.date() - timedelta(days=1)).isoformat(): 99.0,
            start.date().isoformat(): 1.0,
            now.date().isoformat(): 2.0,
        }
        windows = {"monthly": {"percent": 10.0, "status": "ok", "resets_at": reset}}
        models = [{"provider": "p", "model": "m1", "cost": 3.0, "requests": 2}]

        with (
            mock.patch.object(watch, "opencode_go_key", return_value="key"),
            mock.patch.object(watch, "fetch_windows", return_value=windows),
            mock.patch.object(watch, "fetch_daily", return_value=days),
            mock.patch.object(watch, "fetch_models", return_value=models),
        ):
            stats = watch.collect(self.config, {})

        self.assertAlmostEqual(stats["period_total"], 3.0)
        self.assertAlmostEqual(stats["today"], 2.0)
        self.assertAlmostEqual(stats["last7"], 2.0)
        self.assertEqual(stats["closest"]["model"], "m1")
        self.assertAlmostEqual(stats["closest"]["remaining"], 7.0)
        self.assertFalse(stats["coverage_gap"])

    def test_merges_persisted_days_and_flags_a_coverage_gap(self):
        now = datetime.now(timezone.utc)
        reset = now + timedelta(days=10)
        start = watch.subtract_month(reset)
        stored = {(start.date() - timedelta(days=1)).isoformat(): 4.0}
        fresh = {(start.date() + timedelta(days=1)).isoformat(): 2.0}
        windows = {"monthly": {"percent": 1.0, "status": "ok", "resets_at": reset}}

        with (
            mock.patch.object(watch, "opencode_go_key", return_value="key"),
            mock.patch.object(watch, "fetch_windows", return_value=windows),
            mock.patch.object(watch, "fetch_daily", return_value=fresh),
            mock.patch.object(watch, "fetch_models", return_value=[]),
        ):
            stats = watch.collect(self.config, stored)

        self.assertAlmostEqual(stats["period_total"], 2.0)
        self.assertIn((start.date() - timedelta(days=1)).isoformat(), stats["days"])
        self.assertTrue(stats["coverage_gap"])


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = fake_config(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def stats(self):
        return {
            "windows": {
                "rolling": {"percent": 0.0, "resets_at": None},
                "weekly": {"percent": 6.0, "resets_at": None},
                "monthly": {"percent": 3.0, "resets_at": None},
            },
            "days": {},
            "period_start": datetime(2026, 10, 27, tzinfo=timezone.utc),
            "period_end": datetime(2026, 11, 27, tzinfo=timezone.utc),
            "period_total": 6.05,
            "today": 1.45,
            "last7": 3.54,
            "models": [],
            "closest": None,
            "coverage_gap": False,
        }

    def test_money_and_percent_formatting(self):
        self.assertEqual(watch.money(1234.5), "$1,234.50")
        self.assertEqual(watch.format_percent(None), "n/a")
        self.assertEqual(watch.format_percent(3.4), "3%")
        self.assertEqual(watch.format_moment(None), "unknown")

    def test_startup_message(self):
        text = watch.build_message(self.stats(), None, None, self.config, "startup")
        self.assertIn("watcher started", text)
        self.assertIn("$6.05", text)

    def test_reset_message(self):
        text = watch.build_message(self.stats(), None, None, self.config, "reset")
        self.assertIn("billing period reset", text.lower())

    def test_report_notes_a_coverage_gap(self):
        stats = self.stats()
        stats["coverage_gap"] = True
        text = watch.build_message(stats, None, None, self.config, "report")
        self.assertIn("current status", text)
        self.assertIn("30-day API window", text)


class StoreTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = watch.Store(Path(tmp))
            with store.locked():
                store.save({"initialized": True, "last_level": 3})
            self.assertEqual(store.load(), {"initialized": True, "last_level": 3})


if __name__ == "__main__":
    unittest.main()
