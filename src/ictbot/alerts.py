"""Optional Telegram / e-mail alerts. Enabled only when the secrets exist.

Telegram: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
E-mail:   SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO
Alert failures are logged and swallowed - they must never stop trading logic.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
import urllib.parse
import urllib.request
from email.message import EmailMessage

from .config import AlertsConfig
from .logging_setup import redact

log = logging.getLogger(__name__)
TIMEOUT_S = 10


class Notifier:
    def __init__(self, cfg: AlertsConfig) -> None:
        self._cfg = cfg
        self._tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        self._smtp_host = os.environ.get("SMTP_HOST", "")
        self._smtp_to = os.environ.get("ALERT_EMAIL_TO", "")

    @property
    def channels(self) -> list[str]:
        ch = []
        if self._tg_token and self._tg_chat:
            ch.append("telegram")
        if self._smtp_host and self._smtp_to:
            ch.append("email")
        return ch if self._cfg.enabled else []

    def send(self, kind: str, text: str) -> None:
        flag = {"fill": self._cfg.on_fill, "halt": self._cfg.on_halt, "error": self._cfg.on_error}.get(kind, True)
        if not flag:
            return
        msg = redact(f"[ictbot PAPER] {kind.upper()}: {text}")
        for ch in self.channels:
            try:
                self._telegram(msg) if ch == "telegram" else self._email(kind, msg)
            except Exception as exc:  # noqa: BLE001
                log.warning("alert delivery failed", extra={"channel": ch, "error": redact(str(exc))[:200]})

    def _telegram(self, msg: str) -> None:
        url = f"https://api.telegram.org/bot{self._tg_token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": self._tg_chat, "text": msg[:4000]}).encode()
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=TIMEOUT_S) as resp:
            json.loads(resp.read() or b"{}")

    def _email(self, kind: str, msg: str) -> None:
        em = EmailMessage()
        em["Subject"] = f"ictbot paper: {kind}"
        em["From"] = os.environ.get("SMTP_USER", "ictbot@localhost")
        em["To"] = self._smtp_to
        em.set_content(msg)
        port = int(os.environ.get("SMTP_PORT", "587"))
        with smtplib.SMTP(self._smtp_host, port, timeout=TIMEOUT_S) as s:
            s.starttls(context=ssl.create_default_context())
            user, pwd = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", "")
            if user and pwd:
                s.login(user, pwd)
            s.send_message(em)
