"""PAPER-ONLY guard. The bot refuses to start unless everything says "paper"."""

from __future__ import annotations

import os
from dataclasses import dataclass

# Hardcoded. There is deliberately no setting that changes this.
PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_HOST_MARKERS = ("://api.alpaca.markets", "broker-api.alpaca.markets")
# Alpaca convention: paper key IDs start with "PK", live key IDs with "AK".
LIVE_KEY_PREFIX = "AK"
PAPER_ACCOUNT_PREFIX = "PA"

KEY_ENV = ("APCA_API_KEY_ID", "ALPACA_API_KEY")
SECRET_ENV = ("APCA_API_SECRET_KEY", "ALPACA_SECRET_KEY")
URL_ENV = ("APCA_API_BASE_URL", "ALPACA_BASE_URL")


class LiveTradingRefused(RuntimeError):
    """Raised when anything indicates a live (real-money) account."""


@dataclass(frozen=True)
class Credentials:
    key_id: str
    secret_key: str

    def __repr__(self) -> str:  # never print secrets
        return "Credentials(key_id=***, secret_key=***)"


def _first_env(names: tuple[str, ...]) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def load_paper_credentials() -> Credentials:
    key = _first_env(KEY_ENV)
    secret = _first_env(SECRET_ENV)
    if not key or not secret:
        raise LiveTradingRefused(
            "Missing Alpaca PAPER credentials. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY "
            "as environment variables (GitHub Secrets)."
        )
    assert_paper_environment(key)
    return Credentials(key, secret)


def assert_paper_environment(key_id: str) -> None:
    url = _first_env(URL_ENV)
    if url:
        normalized = url.rstrip("/").lower()
        if normalized != PAPER_BASE_URL or any(m in normalized for m in LIVE_HOST_MARKERS):
            raise LiveTradingRefused(f"Configured base URL is not the paper endpoint ({PAPER_BASE_URL}). Refusing.")
    if key_id.upper().startswith(LIVE_KEY_PREFIX):
        raise LiveTradingRefused("API key ID looks like a LIVE key (prefix 'AK'). This bot is paper-only. Refusing.")


def assert_paper_account(account_number: str, client_base_url: str) -> None:
    """Post-connection check against what the broker actually reports."""
    if client_base_url.rstrip("/") != PAPER_BASE_URL:
        raise LiveTradingRefused(f"Trading client is not pointed at {PAPER_BASE_URL}. Refusing.")
    if not str(account_number).upper().startswith(PAPER_ACCOUNT_PREFIX):
        raise LiveTradingRefused(
            "Account number does not carry Alpaca's paper prefix 'PA'. Refusing to trade "
            "(if Alpaca changed its numbering convention, review safety.py before proceeding)."
        )
