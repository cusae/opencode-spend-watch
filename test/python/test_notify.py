import json
import ssl
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import notify


def response(status=200):
    reply = mock.MagicMock(status=status)
    reply.__enter__.return_value = reply
    return reply


def request_payload(urlopen):
    request = urlopen.call_args.args[0]
    return request, json.loads(request.data)


class FormatTests(unittest.TestCase):
    def test_to_plain_removes_markdown(self):
        text = "**Title**\n[console](https://example.invalid)\n`code`"
        self.assertEqual(
            notify.to_plain(text),
            "Title\nconsole (https://example.invalid)\ncode",
        )

    def test_byte_chunks_split_without_breaking_utf8(self):
        chunks = notify._byte_chunks("a" * 10 + "é" * 10, 6)
        self.assertTrue(all(len(chunk.encode("utf-8")) <= 6 for chunk in chunks))
        self.assertEqual("".join(chunks).replace(" ", ""), "a" * 10 + "é" * 10)

    def test_truncate_marks_the_cut(self):
        self.assertEqual(notify._truncate("abcdef", 4), "abc…")
        self.assertEqual(notify._truncate("abc", 4), "abc")


class ChannelTests(unittest.TestCase):
    def test_names_lists_only_complete_channels(self):
        channels = notify.Channels(
            mattermost_url="https://mm.invalid/hook",
            slack_url="https://slack.invalid/hook",
            irc_host="irc.invalid",
            irc_channel="#alerts",
            smtp_host="smtp.invalid",
            email_from="from@example.invalid",
            email_to=("to@example.invalid",),
            whatsapp_token="token",
            whatsapp_phone_id="123",
            whatsapp_to="456",
        )
        self.assertEqual(
            channels.names(),
            ["mattermost", "slack", "irc", "email", "whatsapp"],
        )

    def test_names_include_telegram_and_desktop(self):
        channels = notify.Channels(
            telegram_token="token",
            telegram_chat_id="42",
            desktop=True,
        )
        self.assertEqual(channels.names(), ["telegram", "desktop"])

    def test_telegram_payload_and_chunking(self):
        with mock.patch.object(
            notify.urllib.request, "urlopen", return_value=response()
        ) as urlopen:
            notify.send_telegram("secret", "42", "x" * 9000)
        self.assertEqual(urlopen.call_count, 3)
        request, payload = request_payload(urlopen)
        self.assertIn("/botsecret/sendMessage", request.full_url)
        self.assertEqual(payload["chat_id"], "42")

    def test_desktop_uses_notify_send(self):
        with (
            mock.patch.object(notify.sys, "platform", "linux"),
            mock.patch.object(notify.shutil, "which", return_value="/usr/bin/notify-send"),
            mock.patch.object(notify.subprocess, "run") as run,
        ):
            notify.send_desktop("**hello**", "#c62828")
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/notify-send")
        self.assertIn("critical", command)
        self.assertIn("hello", command[-1])

    def test_desktop_reports_a_missing_helper(self):
        with (
            mock.patch.object(notify.sys, "platform", "linux"),
            mock.patch.object(notify.shutil, "which", return_value=None),
            self.assertRaises(notify.DeliveryError),
        ):
            notify.send_desktop("hello", "#000000")

    def test_desktop_uses_osascript_on_macos(self):
        with (
            mock.patch.object(notify.sys, "platform", "darwin"),
            mock.patch.object(notify.subprocess, "run") as run,
        ):
            notify.send_desktop("**hello**", "#000000")
        self.assertEqual(run.call_args.args[0][0], "osascript")

    def test_text_chunks_prefer_line_boundaries(self):
        chunks = notify._text_chunks("a" * 5 + "\n" + "b" * 5, 6)
        self.assertEqual(chunks, ["a" * 5 + "\n", "b" * 5])

    def test_names_include_rss(self):
        channels = notify.Channels(rss_feed="/tmp/feed.xml")
        self.assertEqual(channels.names(), ["rss"])

    def test_rss_feed_appends_and_prunes(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = Path(tmp) / "feed.xml"
            for index in range(3):
                notify.send_rss(
                    str(feed),
                    "OpenCode Spend Alerts",
                    "https://example.invalid",
                    f"**Alert {index}**",
                    max_items=2,
                )
            body = feed.read_text()
            self.assertIn("<rss", body)
            self.assertIn("Alert 2", body)
            self.assertNotIn("Alert 0", body)
            notify.ET.parse(feed)

    def test_rss_feed_rejects_a_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = Path(tmp) / "feed.xml"
            feed.write_text("not xml")
            with self.assertRaises(notify.DeliveryError):
                notify.send_rss(str(feed), "title", "", "hello")

    def test_rss_feed_requires_a_positive_limit(self):
        with self.assertRaises(notify.DeliveryError):
            notify.send_rss("/tmp/feed.xml", "title", "", "hello", max_items=0)

    def test_sections_become_coloured_attachments(self):
        text = f"first{notify.SECTION}second{notify.SECTION}third"
        with mock.patch.object(notify.urllib.request, "urlopen", return_value=response()):
            notify.send_mattermost("https://example.invalid/hook", text, "#2e7d32")
            _, payload = request_payload(notify.urllib.request.urlopen)
        self.assertEqual(len(payload["attachments"]), 3)
        self.assertEqual(payload["attachments"][0]["color"], "#2e7d32")
        self.assertNotEqual(payload["attachments"][1]["color"], payload["attachments"][2]["color"])

    def test_mattermost_payload(self):
        with mock.patch.object(notify.urllib.request, "urlopen", return_value=response()):
            notify.send_mattermost("https://example.invalid/hook", "hello", "#2e7d32")
            request, payload = request_payload(notify.urllib.request.urlopen)
        self.assertEqual(payload["attachments"][0]["text"], "hello")
        self.assertEqual(payload["attachments"][0]["color"], "#2e7d32")
        self.assertEqual(request.get_header("User-agent"), notify.USER_AGENT)

    def test_slack_payload_truncates(self):
        with mock.patch.object(notify.urllib.request, "urlopen", return_value=response()):
            notify.send_slack("https://example.invalid/hook", "x" * 4000, "#c62828")
            _, payload = request_payload(notify.urllib.request.urlopen)
        self.assertEqual(len(payload["attachments"][0]["text"]), notify.SLACK_LIMIT)
        self.assertEqual(payload["attachments"][0]["color"], "#c62828")

    def test_discord_payload_converts_the_colour(self):
        with mock.patch.object(notify.urllib.request, "urlopen", return_value=response()):
            notify.send_discord("https://example.invalid/hook", "hello", "#2e7d32")
            _, payload = request_payload(notify.urllib.request.urlopen)
        self.assertEqual(payload["embeds"][0]["description"], "hello")
        self.assertEqual(payload["embeds"][0]["color"], 0x2E7D32)

    def test_whatsapp_payload_uses_the_cloud_api(self):
        channels = notify.Channels(
            whatsapp_token="secret-token",
            whatsapp_phone_id="12345",
            whatsapp_to="33600000000",
            whatsapp_version="v21.0",
        )
        with mock.patch.object(notify.urllib.request, "urlopen", return_value=response()):
            notify.send_whatsapp(channels, "**hello**")
            request, payload = request_payload(notify.urllib.request.urlopen)
        self.assertIn("/v21.0/12345/messages", request.full_url)
        self.assertEqual(request.headers["Authorization"], "Bearer secret-token")
        self.assertEqual(payload["text"]["body"], "hello")

    def test_invalid_webhook_url_is_rejected(self):
        with self.assertRaises(notify.DeliveryError):
            notify.send_mattermost("file:///tmp/hook", "hello", "#000000")

    def test_delivery_is_retried(self):
        with (
            mock.patch.object(
                notify.urllib.request,
                "urlopen",
                side_effect=[urllib.error.URLError("down"), response()],
            ) as urlopen,
            mock.patch.object(notify.time, "sleep"),
        ):
            notify.send_mattermost("https://example.invalid/hook", "hello", "#000000")
        self.assertEqual(urlopen.call_count, 2)

    def test_a_failed_status_raises(self):
        with (
            mock.patch.object(notify.urllib.request, "urlopen", return_value=response(500)),
            self.assertRaises(notify.DeliveryError),
        ):
            notify.send_mattermost("https://example.invalid/hook", "hello", "#000000", attempts=1)


class EmailTests(unittest.TestCase):
    def channels(self):
        return notify.Channels(
            smtp_host="smtp.example.invalid",
            smtp_port=587,
            smtp_security="starttls",
            smtp_user="user",
            smtp_password="secret",
            email_from="from@example.invalid",
            email_to=("to@example.invalid",),
        )

    def test_starttls_and_login(self):
        client = mock.MagicMock()
        with mock.patch.object(notify.smtplib, "SMTP", return_value=client):
            notify.send_email(self.channels(), "**hello**", "#2e7d32")
        client.starttls.assert_called_once()
        context = client.starttls.call_args.kwargs["context"]
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        client.login.assert_called_once_with("user", "secret")
        message = client.send_message.call_args.args[0]
        self.assertEqual(message["Subject"], "OpenCode spend alert")
        self.assertIn("hello", message.get_body().get_content())
        html_body = message.get_body(preferencelist=("html",)).get_content()
        self.assertIn("#2e7d32", html_body)

    def test_none_security_skips_starttls(self):
        client = mock.MagicMock()
        channels = notify.Channels(
            smtp_host="smtp.example.invalid",
            smtp_security="none",
            email_from="from@example.invalid",
            email_to=("to@example.invalid",),
        )
        with mock.patch.object(notify.smtplib, "SMTP", return_value=client):
            notify.send_email(channels, "hello", "#000000")
        client.starttls.assert_not_called()
        client.send_message.assert_called_once()

    def test_plain_text_alternative_is_mutt_friendly(self):
        client = mock.MagicMock()
        text = (
            f"🟢 **Spend alert**\n**$6.05** used"
            f"{notify.SECTION}**📊 Allowance**"
            f"{notify.SECTION}🔗 [Console](https://example.invalid)"
        )
        with mock.patch.object(notify.smtplib, "SMTP", return_value=client):
            notify.send_email(self.channels(), text, "#2e7d32")
        message = client.send_message.call_args.args[0]
        self.assertEqual(message.get_content_type(), "multipart/alternative")
        self.assertEqual(
            [part.get_content_type() for part in message.iter_parts()],
            ["text/plain", "text/html"],
        )
        plain = message.get_body(preferencelist=("plain",)).get_content()
        self.assertIn("Spend alert", plain)
        self.assertIn("Console (https://example.invalid)", plain)
        self.assertIn("🟢", plain)
        self.assertNotIn("**", plain)
        self.assertNotIn(notify.SECTION, plain)
        self.assertNotIn("<div", plain)

    def test_ssl_and_no_login(self):
        client = mock.MagicMock()
        channels = notify.Channels(
            smtp_host="smtp.example.invalid",
            smtp_port=465,
            smtp_security="ssl",
            email_from="from@example.invalid",
            email_to=("to@example.invalid",),
        )
        with mock.patch.object(notify.smtplib, "SMTP_SSL", return_value=client):
            notify.send_email(channels, "hello", "#000000")
        client.login.assert_not_called()
        client.send_message.assert_called_once()

    def test_smtp_failure_is_wrapped(self):
        with (
            mock.patch.object(notify.smtplib, "SMTP", side_effect=OSError("refused")),
            self.assertRaises(notify.DeliveryError),
        ):
            notify.send_email(self.channels(), "hello", "#000000")


class IrcTests(unittest.TestCase):
    class FakeStream:
        def __init__(self):
            self.writes = []
            self.lines = [
                b":server 001 bot :welcome\r\n",
                b":server 366 bot #alerts :end\r\n",
            ]

        def write(self, data):
            self.writes.append(data.decode("utf-8"))

        def readline(self):
            return self.lines.pop(0) if self.lines else b""

        def close(self):
            pass

    class FakeSocket:
        def __init__(self, stream):
            self.stream = stream

        def makefile(self, mode, buffering=0):
            return self.stream

        def close(self):
            pass

    def test_registers_joins_and_sends(self):
        stream = self.FakeStream()
        socket = self.FakeSocket(stream)
        channels = notify.Channels(
            irc_host="irc.example.invalid",
            irc_port=6667,
            irc_tls=False,
            irc_nick="bot",
            irc_channel="#alerts",
        )
        with (
            mock.patch.object(notify.socket, "create_connection", return_value=socket),
            mock.patch.object(notify.time, "sleep"),
        ):
            notify.send_irc(channels, "**hello**")
        joined = "".join(stream.writes)
        self.assertIn("NICK bot", joined)
        self.assertIn("USER bot 0 * :OpenCode Spend", joined)
        self.assertIn("JOIN #alerts", joined)
        self.assertIn("PRIVMSG #alerts :hello", joined)
        self.assertIn("QUIT", joined)

    def test_sends_the_irc_password(self):
        stream = self.FakeStream()
        socket = self.FakeSocket(stream)
        channels = notify.Channels(
            irc_host="irc.example.invalid",
            irc_tls=False,
            irc_channel="#alerts",
            irc_password="secret",
        )
        with (
            mock.patch.object(notify.socket, "create_connection", return_value=socket),
            mock.patch.object(notify.time, "sleep"),
        ):
            notify.send_irc(channels, "hello")
        self.assertIn("PASS secret", "".join(stream.writes))

    def test_connection_failure_is_wrapped(self):
        channels = notify.Channels(irc_host="irc.example.invalid", irc_channel="#alerts")
        with (
            mock.patch.object(notify.socket, "create_connection", side_effect=OSError("refused")),
            self.assertRaises(notify.DeliveryError),
        ):
            notify.send_irc(channels, "hello")


class SendAllTests(unittest.TestCase):
    def test_isolates_a_broken_channel(self):
        channels = notify.Channels(
            mattermost_url="https://example.invalid/hook",
            slack_url="https://example.invalid/slack",
        )
        with (
            mock.patch.object(notify, "send_mattermost"),
            mock.patch.object(notify, "send_slack", side_effect=notify.DeliveryError("down")),
        ):
            results = notify.send_all(channels, "hello", "#000000")
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0].ok)
        self.assertFalse(results[1].ok)
        self.assertEqual(results[1].channel, "slack")

    def test_no_channels_returns_empty(self):
        self.assertEqual(notify.send_all(notify.Channels(), "hello", "#000000"), [])


if __name__ == "__main__":
    unittest.main()
