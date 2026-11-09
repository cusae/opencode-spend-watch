"""Notification backends for opencode-spend-watch.

Every channel is optional. A channel is enabled when its configuration is
complete. Failures are isolated per channel: one broken backend does not stop
the others, and the caller decides whether to advance the alert checkpoint.
"""

from __future__ import annotations

import contextlib
import hashlib
import html
import json
import os
import re
import shutil
import smtplib
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from typing import Any

USER_AGENT = "opencode-spend-watch/1.0"
IRC_LINE_LIMIT = 400
SLACK_LIMIT = 3000
DISCORD_LIMIT = 4096
WHATSAPP_LIMIT = 4096
TELEGRAM_LIMIT = 4000


@dataclass(frozen=True)
class Channels:
    mattermost_url: str = ""
    slack_url: str = ""
    discord_url: str = ""
    irc_host: str = ""
    irc_port: int = 6697
    irc_tls: bool = True
    irc_nick: str = "opencode-spend"
    irc_channel: str = ""
    irc_password: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: str = "starttls"
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: tuple[str, ...] = ()
    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    whatsapp_to: str = ""
    whatsapp_version: str = "v21.0"
    telegram_token: str = ""
    telegram_chat_id: str = ""
    desktop: bool = False
    rss_feed: str = ""
    rss_title: str = "OpenCode Spend Alerts"
    rss_link: str = ""
    rss_max_items: int = 100

    def names(self) -> list[str]:
        names = []
        if self.mattermost_url:
            names.append("mattermost")
        if self.slack_url:
            names.append("slack")
        if self.discord_url:
            names.append("discord")
        if self.irc_host and self.irc_channel:
            names.append("irc")
        if self.smtp_host and self.email_from and self.email_to:
            names.append("email")
        if self.whatsapp_token and self.whatsapp_phone_id and self.whatsapp_to:
            names.append("whatsapp")
        if self.telegram_token and self.telegram_chat_id:
            names.append("telegram")
        if self.desktop:
            names.append("desktop")
        if self.rss_feed:
            names.append("rss")
        return names


@dataclass(frozen=True)
class Result:
    channel: str
    ok: bool
    error: str | None = None


class DeliveryError(RuntimeError):
    """A channel rejected or could not accept the message."""


def _tls_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_default_certs(ssl.Purpose.SERVER_AUTH)
    return context


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def to_plain(text: str) -> str:
    """Reduce the alert Markdown to text for IRC, email, and WhatsApp."""
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    return text.replace("**", "").replace("`", "")


def _post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    attempts: int = 3,
    timeout: int = 15,
) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise DeliveryError("webhook URL must be HTTP(S)")
    body = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    error = "delivery failed"
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if 200 <= response.status < 300:
                    return
                error = f"HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            details = exc.read()[:200].decode("utf-8", "replace")
            error = f"HTTP {exc.code}: {details}"
        except (urllib.error.URLError, OSError) as exc:
            error = str(exc)
        if attempt < attempts:
            time.sleep(2)
    raise DeliveryError(error)


def send_mattermost(url: str, text: str, color: str, attempts: int = 3) -> None:
    _post_json(
        url,
        {
            "username": "OpenCode Spend",
            "icon_emoji": ":money_with_wings:",
            "attachments": [{"color": color, "text": text}],
        },
        attempts=attempts,
    )


def send_slack(url: str, text: str, color: str, attempts: int = 3) -> None:
    _post_json(
        url,
        {
            "username": "OpenCode Spend",
            "icon_emoji": ":money_with_wings:",
            "attachments": [
                {
                    "color": color,
                    "text": _truncate(text, SLACK_LIMIT),
                    "mrkdwn_in": ["text"],
                }
            ],
        },
        attempts=attempts,
    )


def send_discord(url: str, text: str, color: str, attempts: int = 3) -> None:
    try:
        color_int = int(color.lstrip("#"), 16)
    except ValueError:
        color_int = 0
    _post_json(
        url,
        {
            "username": "OpenCode Spend",
            "embeds": [{"description": _truncate(text, DISCORD_LIMIT), "color": color_int}],
        },
        attempts=attempts,
    )


def send_whatsapp(channels: Channels, text: str, attempts: int = 3) -> None:
    version = channels.whatsapp_version.strip("/")
    url = f"https://graph.facebook.com/{version}/{channels.whatsapp_phone_id}/messages"
    _post_json(
        url,
        {
            "messaging_product": "whatsapp",
            "to": channels.whatsapp_to,
            "type": "text",
            "text": {"body": _truncate(to_plain(text), WHATSAPP_LIMIT)},
        },
        headers={"Authorization": f"Bearer {channels.whatsapp_token}"},
        attempts=attempts,
    )


def _byte_chunks(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    for line in text.splitlines() or [""]:
        current = ""
        size = 0
        for char in line:
            width = len(char.encode("utf-8"))
            if size + width > limit and current:
                chunks.append(current)
                current, size = char, width
            else:
                current += char
                size += width
        chunks.append(current)
    return [chunk if chunk else " " for chunk in chunks]


def _irc_write(stream: Any, line: str) -> None:
    stream.write(f"{line}\r\n".encode())


def _irc_wait(stream: Any, token: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = stream.readline()
        if not raw:
            raise DeliveryError("IRC server closed the connection")
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if line.startswith("PING"):
            _irc_write(stream, "PONG " + line.partition(" ")[2])
        if token in line:
            return
    raise DeliveryError(f"IRC timeout waiting for {token.strip()}")


def send_irc(channels: Channels, text: str) -> None:
    host = channels.irc_host
    port = channels.irc_port
    nick = channels.irc_nick
    channel = channels.irc_channel
    if not channel.startswith(("#", "&")):
        channel = f"#{channel}"
    sock: socket.socket | ssl.SSLSocket | None = None
    stream = None
    try:
        sock = socket.create_connection((host, port), timeout=15)
        if channels.irc_tls:
            sock = _tls_context().wrap_socket(sock, server_hostname=host)
        stream = sock.makefile("rwb", buffering=0)
        if channels.irc_password:
            _irc_write(stream, f"PASS {channels.irc_password}")
        _irc_write(stream, f"NICK {nick}")
        _irc_write(stream, f"USER {nick} 0 * :OpenCode Spend")
        _irc_wait(stream, " 001 ")
        _irc_write(stream, f"JOIN {channel}")
        with contextlib.suppress(DeliveryError):
            _irc_wait(stream, " 366 ", timeout=5)
        for chunk in _byte_chunks(to_plain(text), IRC_LINE_LIMIT):
            _irc_write(stream, f"PRIVMSG {channel} :{chunk}")
            time.sleep(0.2)
        _irc_write(stream, "QUIT :spend report sent")
    except (OSError, ssl.SSLError) as exc:
        raise DeliveryError(str(exc)) from None
    finally:
        if stream is not None:
            stream.close()
        if sock is not None:
            sock.close()


def _text_chunks(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) <= limit:
            current += line
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        current = line
    if current:
        chunks.append(current)
    return chunks or [""]


def send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in _text_chunks(to_plain(text), TELEGRAM_LIMIT):
        _post_json(
            url,
            {
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            },
        )


def send_desktop(text: str, color: str) -> None:
    plain = to_plain(text)
    title = "OpenCode spend"
    body = _truncate(plain.strip(), 500)
    urgency = "critical" if color == "#c62828" else "normal"
    if sys.platform == "darwin":
        script = f'display notification {json.dumps(body)} with title "{title}"'
        command = ["osascript", "-e", script]
    else:
        binary = shutil.which("notify-send")
        if not binary:
            raise DeliveryError("notify-send not found")
        command = [binary, "-a", "OpenCode Spend", "-u", urgency, title, body]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeliveryError(str(exc)) from None


def send_rss(
    feed: str,
    title: str,
    link: str,
    text: str,
    max_items: int = 100,
) -> None:
    if max_items < 1:
        raise DeliveryError("RSS_MAX_ITEMS must be at least 1")
    path = Path(feed).expanduser()
    now = datetime.now(timezone.utc)
    try:
        if path.exists():
            tree = ET.parse(path)
            root = tree.getroot()
            channel = root.find("channel")
            if channel is None:
                raise DeliveryError("existing RSS feed has no channel element")
        else:
            root = ET.Element("rss", version="2.0")
            channel = ET.SubElement(root, "channel")
            tree = ET.ElementTree(root)

        for tag, value in (
            ("title", title),
            ("description", "OpenCode, OpenRouter, and OpenAI spend alerts."),
        ):
            node = channel.find(tag)
            if node is None:
                node = ET.SubElement(channel, tag)
            node.text = value
        if link:
            node = channel.find("link")
            if node is None:
                node = ET.SubElement(channel, "link")
            node.text = link
        build = channel.find("lastBuildDate")
        if build is None:
            build = ET.SubElement(channel, "lastBuildDate")
        build.text = format_datetime(now)

        first_line = to_plain(text).strip().splitlines()[0] if text.strip() else "Alert"
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = first_line.lstrip("*# ").strip()
        ET.SubElement(item, "guid", isPermaLink="false").text = hashlib.sha256(
            f"{now.isoformat()}{text}".encode()
        ).hexdigest()
        ET.SubElement(item, "pubDate").text = format_datetime(now)
        ET.SubElement(item, "description").text = to_plain(text)

        items = channel.findall("item")
        for old in items[:-max_items]:
            channel.remove(old)

        ET.indent(tree, space="  ")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        tree.write(temporary, encoding="utf-8", xml_declaration=True)
        os.replace(temporary, path)
    except (OSError, ET.ParseError) as exc:
        raise DeliveryError(f"RSS feed: {exc}") from None


def _html_body(text: str, color: str) -> str:
    return (
        f'<div style="border-left:4px solid {color};padding:8px 14px">'
        '<pre style="font-family:monospace;white-space:pre-wrap">'
        f"{html.escape(text)}</pre></div>"
    )


def send_email(channels: Channels, text: str, color: str) -> None:
    message = EmailMessage()
    message["Subject"] = "OpenCode spend alert"
    message["From"] = channels.email_from
    message["To"] = ", ".join(channels.email_to)
    message.set_content(to_plain(text))
    message.add_alternative(_html_body(text, color), subtype="html")

    security = channels.smtp_security
    client: smtplib.SMTP | None = None
    try:
        if security == "ssl":
            client = smtplib.SMTP_SSL(
                channels.smtp_host,
                channels.smtp_port,
                timeout=20,
                context=_tls_context(),
            )
        else:
            client = smtplib.SMTP(channels.smtp_host, channels.smtp_port, timeout=20)
            client.ehlo()
            if security == "starttls":
                client.starttls(context=_tls_context())
                client.ehlo()
        if channels.smtp_user:
            client.login(channels.smtp_user, channels.smtp_password)
        client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise DeliveryError(str(exc)) from None
    finally:
        if client is not None:
            with contextlib.suppress(OSError, smtplib.SMTPException):
                client.quit()


def send_all(channels: Channels, text: str, color: str) -> list[Result]:
    senders: list[tuple[str, Callable[[], None]]] = []
    if channels.mattermost_url:
        senders.append(
            ("mattermost", lambda: send_mattermost(channels.mattermost_url, text, color))
        )
    if channels.slack_url:
        senders.append(("slack", lambda: send_slack(channels.slack_url, text, color)))
    if channels.discord_url:
        senders.append(("discord", lambda: send_discord(channels.discord_url, text, color)))
    if channels.irc_host and channels.irc_channel:
        senders.append(("irc", lambda: send_irc(channels, text)))
    if channels.smtp_host and channels.email_from and channels.email_to:
        senders.append(("email", lambda: send_email(channels, text, color)))
    if channels.whatsapp_token and channels.whatsapp_phone_id and channels.whatsapp_to:
        senders.append(("whatsapp", lambda: send_whatsapp(channels, text)))
    if channels.telegram_token and channels.telegram_chat_id:
        senders.append(
            (
                "telegram",
                lambda: send_telegram(channels.telegram_token, channels.telegram_chat_id, text),
            )
        )
    if channels.desktop:
        senders.append(("desktop", lambda: send_desktop(text, color)))
    if channels.rss_feed:
        senders.append(
            (
                "rss",
                lambda: send_rss(
                    channels.rss_feed,
                    channels.rss_title,
                    channels.rss_link,
                    text,
                    channels.rss_max_items,
                ),
            )
        )

    results: list[Result] = []
    for name, send in senders:
        try:
            send()
            results.append(Result(name, True))
        except Exception as exc:  # one broken channel must not block the others
            results.append(Result(name, False, str(exc)))
    return results
