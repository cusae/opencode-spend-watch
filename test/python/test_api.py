import io
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import watch


class KeyTests(unittest.TestCase):
    def test_reads_the_key_from_the_opencode_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "opencode.db"
            con = sqlite3.connect(db)
            con.execute("create table credential (id text, integration_id text, value text)")
            con.execute(
                "insert into credential values ('c1', 'opencode-go', ?)",
                (json.dumps({"type": "key", "key": "oc_test"}),),
            )
            con.commit()
            con.close()
            config = SimpleNamespace(api_key_override="", opencode_db=db)
            self.assertEqual(watch.opencode_go_key(config), "oc_test")

    def test_reads_the_key_from_auth_json_when_the_database_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth = Path(tmp) / "opencode" / "auth.json"
            auth.parent.mkdir()
            auth.write_text(json.dumps({"opencode-go": {"key": "oc_auth"}}), encoding="utf-8")
            config = SimpleNamespace(api_key_override="", opencode_db=Path(tmp) / "absent.db")
            with mock.patch.dict("os.environ", {"XDG_DATA_HOME": tmp}):
                self.assertEqual(watch.opencode_go_key(config), "oc_auth")

    def test_override_wins(self):
        config = SimpleNamespace(api_key_override="oc_override", opencode_db=Path("/nonexistent"))
        self.assertEqual(watch.opencode_go_key(config), "oc_override")

    def test_missing_key_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = SimpleNamespace(api_key_override="", opencode_db=Path(tmp) / "absent.db")
            with (
                mock.patch.dict("os.environ", {"XDG_DATA_HOME": tmp}),
                self.assertRaises(RuntimeError),
            ):
                watch.opencode_go_key(config)


class ApiTests(unittest.TestCase):
    def test_api_json_sends_a_bearer_token_and_identity(self):
        response = mock.MagicMock()
        response.read.return_value = b'{"ok": true}'
        response.__enter__.return_value = response
        with mock.patch.object(watch.urllib.request, "urlopen", return_value=response) as urlopen:
            self.assertEqual(watch.api_json("/path", "oc_key"), {"ok": True})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer oc_key")
        self.assertEqual(request.get_header("User-agent"), watch.USER_AGENT)

    def test_api_json_reports_the_http_status(self):
        error = urllib.error.HTTPError(
            "https://example.invalid", 401, "Unauthorized", {}, io.BytesIO(b"denied")
        )
        with (
            mock.patch.object(watch.urllib.request, "urlopen", side_effect=error),
            self.assertRaisesRegex(RuntimeError, "HTTP 401"),
        ):
            watch.api_json("/path", "oc_key")

    def test_fetch_windows_parses_percentages_and_reset_times(self):
        body = {
            "usage": {
                "rolling": {"percent": 1.5, "status": "ok", "resetsAt": "2026-11-09T01:00:00Z"},
                "weekly": {"percent": 6, "status": "ok", "resetsAt": None},
            }
        }
        with mock.patch.object(watch, "api_json", return_value=body):
            windows = watch.fetch_windows("key")
        self.assertEqual(windows["rolling"]["percent"], 1.5)
        self.assertEqual(
            windows["rolling"]["resets_at"],
            datetime(2026, 11, 9, 1, tzinfo=timezone.utc),
        )
        self.assertIsNone(windows["weekly"]["resets_at"])

    def test_fetch_daily_ignores_malformed_entries(self):
        body = [
            {"date": "2026-11-08", "totalCostMicroCents": "123456789"},
            {"date": "bad"},
            {"totalCostMicroCents": "1"},
        ]
        with mock.patch.object(watch, "api_json", return_value=body):
            days = watch.fetch_daily("key")
        self.assertEqual(days, {"2026-11-08": 1.23456789})

    def test_fetch_models_walks_every_page(self):
        pages = [
            {
                "items": [
                    {
                        "provider": "p",
                        "model": "m1",
                        "totalCostMicroCents": "100",
                        "totalRequests": "2",
                    }
                ],
                "pageInfo": {"page": 1, "pageCount": 2},
            },
            {
                "items": [
                    {
                        "provider": "p",
                        "model": "m2",
                        "totalCostMicroCents": "200",
                        "totalRequests": "3",
                    }
                ],
                "pageInfo": {"page": 2, "pageCount": 2},
            },
        ]
        with mock.patch.object(watch, "api_json", side_effect=pages):
            models = watch.fetch_models("key")
        self.assertEqual([m["model"] for m in models], ["m1", "m2"])
        self.assertAlmostEqual(models[1]["cost"], 0.000002)


class DeliveryTests(unittest.TestCase):
    def test_post_webhook_sends_the_message(self):
        response = mock.MagicMock(status=200)
        response.__enter__.return_value = response
        with mock.patch.object(watch.urllib.request, "urlopen", return_value=response) as urlopen:
            self.assertTrue(watch.post_webhook("https://example.invalid/hook", "hello"))
        request = urlopen.call_args.args[0]
        attachment = json.loads(request.data)["attachments"][0]
        self.assertEqual(attachment["text"], "hello")
        self.assertEqual(attachment["color"], watch.COLOR_BLUE)

    def test_post_webhook_returns_false_after_a_failure(self):
        with mock.patch.object(
            watch.urllib.request, "urlopen", side_effect=urllib.error.URLError("down")
        ):
            self.assertFalse(
                watch.post_webhook("https://example.invalid/hook", "hello", attempts=1)
            )

    def test_post_webhook_returns_false_on_a_non_2xx_status(self):
        response = mock.MagicMock(status=500)
        response.__enter__.return_value = response
        with mock.patch.object(watch.urllib.request, "urlopen", return_value=response):
            self.assertFalse(
                watch.post_webhook("https://example.invalid/hook", "hello", attempts=1)
            )

    def test_post_webhook_rejects_a_non_http_url(self):
        self.assertFalse(watch.post_webhook("file:///tmp/hook", "hello", attempts=1))
        self.assertFalse(watch.post_webhook("not-a-url", "hello", attempts=1))


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.config = SimpleNamespace(
            api_key_override="oc_key",
            opencode_db=Path("/nonexistent"),
            webhook="https://example.invalid/hook",
            plan="go-plus",
            step=1.0,
            state_dir=self.dir,
            startup_message=True,
            reset_message=True,
            console_url="",
            percent_thresholds=(50.0, 80.0, 95.0),
            providers=(),
            alert_log=self.dir / "alerts.log",
            limits=lambda: {"m1": 10.0},
            labels=lambda: {},
            channels=lambda: watch.notify.Channels(mattermost_url="https://example.invalid/hook"),
        )
        self.stats = {
            "windows": {"monthly": {"percent": 3.0, "resets_at": None}},
            "days": {},
            "period_start": datetime(2026, 10, 27, tzinfo=timezone.utc),
            "period_end": datetime(2026, 11, 27, tzinfo=timezone.utc),
            "period_total": 1.0,
            "today": 1.0,
            "last7": 1.0,
            "models": [],
            "closest": None,
            "coverage_gap": False,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_check_reports_success(self):
        with (
            mock.patch.object(watch, "opencode_go_key", return_value="oc_key"),
            mock.patch.object(watch, "fetch_windows", return_value={}),
            mock.patch.object(watch, "fetch_daily", return_value={"2026-11-08": 1.0}),
            mock.patch.object(watch, "fetch_models", return_value=[]),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(watch.check(self.config), 0)
        self.assertIn("api: ok", output.getvalue())

    def test_check_reports_an_api_failure(self):
        with (
            mock.patch.object(watch, "opencode_go_key", return_value="oc_key"),
            mock.patch.object(watch, "fetch_windows", side_effect=RuntimeError("boom")),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(watch.check(self.config), 1)

    def test_test_webhook_requires_a_channel(self):
        config = SimpleNamespace(step=1.0, channels=lambda: watch.notify.Channels())
        self.assertEqual(watch.test_webhook(config), 2)

    def test_test_webhook_sends(self):
        with (
            mock.patch.object(
                watch,
                "deliver",
                return_value=[watch.notify.Result("mattermost", True)],
            ),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(watch.test_webhook(self.config), 0)

    def test_test_webhook_reports_a_failure(self):
        with (
            mock.patch.object(
                watch,
                "deliver",
                return_value=[watch.notify.Result("mattermost", False, "down")],
            ),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(watch.test_webhook(self.config), 1)

    def test_report_prints_the_current_status(self):
        with (
            mock.patch.object(watch, "collect", return_value=self.stats),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(watch.report(self.config), 0)
        self.assertIn("current status", output.getvalue())

    def test_check_reports_missing_channels(self):
        config = SimpleNamespace(
            api_key_override="oc_key",
            opencode_db=Path("/nonexistent"),
            webhook="",
            plan="go-plus",
            step=1.0,
            state_dir=self.dir,
            percent_thresholds=(50.0, 80.0, 95.0),
            providers=(),
            alert_log=self.dir / "alerts.log",
            limits=lambda: {},
            labels=lambda: {},
            channels=lambda: watch.notify.Channels(),
        )
        with (
            mock.patch.object(watch, "opencode_go_key", return_value="oc_key"),
            mock.patch.object(watch, "fetch_windows", return_value={}),
            mock.patch.object(watch, "fetch_daily", return_value={}),
            mock.patch.object(watch, "fetch_models", return_value=[]),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(watch.check(config), 1)
        self.assertIn("configure at least one channel", output.getvalue())

    def test_check_reports_a_missing_key(self):
        with (
            mock.patch.object(watch, "opencode_go_key", side_effect=RuntimeError("no key")),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(watch.check(self.config), 1)
        self.assertIn("key: FAIL", output.getvalue())

    def test_report_reports_an_api_failure(self):
        with (
            mock.patch.object(watch, "collect", side_effect=RuntimeError("boom")),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(watch.report(self.config), 1)

    def test_main_dispatches_commands(self):
        with mock.patch.dict("os.environ", {"OSW_CONFIG": str(self.dir / "config.env")}):
            with mock.patch.object(watch, "check", return_value=0) as check:
                self.assertEqual(watch.main(["watch.py", "check"]), 0)
                check.assert_called_once()
            with mock.patch.object(watch, "poll", return_value=0) as poll:
                self.assertEqual(watch.main(["watch.py"]), 0)
                poll.assert_called_once()

    def test_main_dispatches_merge_config_without_loading_the_config(self):
        with (
            mock.patch.dict("os.environ", {"OSW_CONFIG": "/nonexistent/config.env"}),
            mock.patch.object(watch.configmerge, "main", return_value=0) as merge,
        ):
            self.assertEqual(watch.main(["watch.py", "merge-config", "--dry-run"]), 0)
        merge.assert_called_once_with(["--dry-run"])

    def test_main_rejects_an_unknown_command(self):
        with mock.patch.dict("os.environ", {"OSW_CONFIG": str(self.dir / "config.env")}):
            self.assertEqual(watch.main(["watch.py", "bogus"]), 2)

    def test_main_prints_help_and_version(self):
        with mock.patch.dict("os.environ", {"OSW_CONFIG": str(self.dir / "config.env")}):
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(watch.main(["watch.py", "--help"]), 0)
            self.assertIn("usage:", output.getvalue())
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(watch.main(["watch.py", "--version"]), 0)
            self.assertIn(watch.VERSION, output.getvalue())

    def test_main_reports_a_configuration_error(self):
        path = self.dir / "bad.env"
        path.write_text("THRESHOLD_STEP_USD=zero\n", encoding="utf-8")
        with (
            mock.patch.dict("os.environ", {"OSW_CONFIG": str(path)}),
            redirect_stderr(io.StringIO()) as output,
        ):
            self.assertEqual(watch.main(["watch.py", "poll"]), 2)
        self.assertIn("configuration error", output.getvalue())


class DeliveryResultTests(unittest.TestCase):
    def test_partial_delivery_counts_as_delivered(self):
        results = [
            watch.notify.Result("mattermost", True),
            watch.notify.Result("slack", False, "down"),
        ]
        with redirect_stdout(io.StringIO()):
            self.assertTrue(watch.delivery_ok(results))

    def test_every_channel_failing_is_a_failure(self):
        results = [watch.notify.Result("mattermost", False, "down")]
        with redirect_stdout(io.StringIO()):
            self.assertFalse(watch.delivery_ok(results))
            self.assertFalse(watch.delivery_ok([]))


class MessageBranchTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(step=1.0, console_url="", labels=lambda: {})

    def stats(self):
        return {
            "windows": {"monthly": {"percent": 50.0, "resets_at": None}},
            "days": {},
            "period_start": datetime(2026, 10, 27, tzinfo=timezone.utc),
            "period_end": datetime(2026, 11, 27, tzinfo=timezone.utc),
            "period_total": 9.0,
            "today": 1.0,
            "last7": 2.0,
            "models": [],
            "closest": None,
            "coverage_gap": False,
        }

    def test_reports_a_range_of_crossed_thresholds(self):
        text = watch.build_message(self.stats(), 5.0, 9.0, self.config)
        self.assertIn("$5.00–$9.00", text)

    def test_reports_a_single_threshold_without_a_console_link(self):
        text = watch.build_message(self.stats(), 8.0, 9.0, self.config)
        self.assertIn("crossed $9.00", text)
        self.assertNotIn("Open the console", text)

    def test_handles_a_missing_monthly_window(self):
        stats = self.stats()
        stats["windows"] = {}
        text = watch.build_message(stats, None, None, self.config)
        self.assertIn("n/a", text)

    def test_colors_follow_the_monthly_percentage(self):
        stats = self.stats()
        for percent, color, emoji in (
            (10.0, watch.COLOR_GREEN, "🟢"),
            (60.0, watch.COLOR_AMBER, "🟡"),
            (90.0, watch.COLOR_RED, "🔴"),
        ):
            stats["windows"] = {"monthly": {"percent": percent, "resets_at": None}}
            self.assertEqual(watch.message_color(stats), color)
            self.assertEqual(watch.message_emoji(stats), emoji)

    def test_the_closest_model_limit_can_raise_the_severity(self):
        stats = self.stats()
        stats["windows"] = {"monthly": {"percent": 1.0, "resets_at": None}}
        stats["closest"] = {
            "model": "m1",
            "limit": 10.0,
            "remaining": 1.0,
            "cost": 9.0,
        }
        self.assertEqual(watch.message_color(stats), watch.COLOR_RED)
        self.assertEqual(watch.usage_severity(stats), 90.0)

    def test_startup_reset_and_report_have_fixed_colors(self):
        stats = self.stats()
        self.assertEqual(watch.message_color(stats, "startup"), watch.COLOR_BLUE)
        self.assertEqual(watch.message_color(stats, "reset"), watch.COLOR_GREEN)
        self.assertEqual(watch.message_color(stats, "report"), watch.COLOR_BLUE)
        self.assertIn("ℹ️", watch.build_message(stats, None, None, self.config, "startup"))
        self.assertIn("🔄", watch.build_message(stats, None, None, self.config, "reset"))


if __name__ == "__main__":
    unittest.main()
