"""Structured JSON logging with secret redaction."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys
from pathlib import Path

SECRET_ENV_VARS = (
    "APCA_API_KEY_ID",
    "APCA_API_SECRET_KEY",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "TELEGRAM_BOT_TOKEN",
    "SMTP_PASSWORD",
)
_MIN_SECRET_LEN = 6
_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


def _secret_values() -> list[str]:
    return [v for k in SECRET_ENV_VARS if len(v := os.environ.get(k, "")) >= _MIN_SECRET_LEN]


def redact(text: str) -> str:
    for secret in _secret_values():
        text = text.replace(secret, "***REDACTED***")
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(redact(str(a)) for a in record.args) if isinstance(record.args, tuple) else record.args
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": dt.datetime.fromtimestamp(record.created, tz=dt.timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extras = {k: v for k, v in vars(record).items() if k not in _RESERVED}
        if extras:
            payload["data"] = extras
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(payload, default=str))


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} {record.name}: {record.getMessage()}"
        extras = {k: v for k, v in vars(record).items() if k not in _RESERVED}
        if extras:
            base += " " + json.dumps(extras, default=str)
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return redact(base)


def setup_logging(logs_dir: str | Path, level: str = "INFO", run_name: str = "bot") -> Path:
    logs = Path(logs_dir)
    logs.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = logs / f"{run_name}-{stamp}.jsonl"

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    redactor = RedactingFilter()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(ConsoleFormatter())
    console.addFilter(redactor)
    root.addHandler(console)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(JsonFormatter())
    file_handler.addFilter(redactor)
    root.addHandler(file_handler)

    for noisy in ("urllib3", "matplotlib", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return log_path
