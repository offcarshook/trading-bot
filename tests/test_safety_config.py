from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ictbot.config import ConfigError, config_from_dict, load_config
from ictbot.logging_setup import RedactingFilter, redact
from ictbot.risk import validate_risk_config
from ictbot.safety import LiveTradingRefused, assert_paper_account, load_paper_credentials

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_config_is_valid():
    cfg = load_config(ROOT / "config.yaml")
    validate_risk_config(cfg)
    assert cfg.symbols == ("SPY", "QQQ")
    assert cfg.session.flatten_time == "15:55"
    assert cfg.risk.max_trades_per_day == 2


def test_unknown_key_rejected():
    with pytest.raises(ConfigError, match="unknown key"):
        config_from_dict({"risk": {"risk_per_trade_pctt": 1.0}})


def test_type_errors_rejected():
    with pytest.raises(ConfigError):
        config_from_dict({"risk": {"max_trades_per_day": "two"}})
    with pytest.raises(ConfigError):
        config_from_dict({"ict": {"fvg": {"entry_mode": "anywhere"}}})


@pytest.fixture
def clean_env(monkeypatch):
    for k in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL", "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_missing_credentials_refused(clean_env):
    with pytest.raises(LiveTradingRefused):
        load_paper_credentials()


def test_live_url_refused(clean_env):
    clean_env.setenv("APCA_API_KEY_ID", "PKTESTKEY123")
    clean_env.setenv("APCA_API_SECRET_KEY", "s3cr3t-value")
    clean_env.setenv("APCA_API_BASE_URL", "https://api.alpaca.markets")
    with pytest.raises(LiveTradingRefused, match="paper"):
        load_paper_credentials()


def test_live_key_prefix_refused(clean_env):
    clean_env.setenv("APCA_API_KEY_ID", "AKLIVEKEY123")
    clean_env.setenv("APCA_API_SECRET_KEY", "s3cr3t-value")
    with pytest.raises(LiveTradingRefused, match="LIVE"):
        load_paper_credentials()


def test_paper_credentials_accepted_and_not_printed(clean_env):
    clean_env.setenv("APCA_API_KEY_ID", "PKTESTKEY123")
    clean_env.setenv("APCA_API_SECRET_KEY", "s3cr3t-value")
    clean_env.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets/")
    creds = load_paper_credentials()
    assert "PKTEST" not in repr(creds) and "s3cr3t" not in repr(creds)


def test_account_must_be_paper():
    assert_paper_account("PA1234567", "https://paper-api.alpaca.markets")
    with pytest.raises(LiveTradingRefused):
        assert_paper_account("123456789", "https://paper-api.alpaca.markets")
    with pytest.raises(LiveTradingRefused):
        assert_paper_account("PA1234567", "https://api.alpaca.markets")


def test_secrets_redacted_from_logs(clean_env):
    clean_env.setenv("APCA_API_SECRET_KEY", "super-secret-xyz")
    assert "super-secret-xyz" not in redact("boom: super-secret-xyz leaked")
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "key=%s", ("super-secret-xyz",), None)
    RedactingFilter().filter(rec)
    assert "super-secret-xyz" not in rec.getMessage()
