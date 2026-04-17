import json
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def _bootstrap_service_account():
    """Write service_account.json from env var if file doesn't exist.

    This allows Docker deployments to inject the credential as an env var
    (GOOGLE_SERVICE_ACCOUNT_JSON) instead of volume-mounting the file.
    """
    creds_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "data/service_account.json")
    if not creds_path:
        creds_path = "data/service_account.json"

    if Path(creds_path).exists():
        return  # File already on disk

    raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not raw_json:
        return  # No env var set either

    try:
        # Validate it's real JSON
        json.loads(raw_json)
        Path(creds_path).parent.mkdir(parents=True, exist_ok=True)
        Path(creds_path).write_text(raw_json)
        logger.info("Wrote service_account.json from env var → %s", creds_path)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to write service_account.json: %s", exc)


_bootstrap_service_account()


class Settings:
    # Kite Connect
    KITE_API_KEY: str = os.getenv("KITE_API_KEY", "")
    KITE_API_SECRET: str = os.getenv("KITE_API_SECRET", "")
    KITE_ACCESS_TOKEN: str = os.getenv("KITE_ACCESS_TOKEN", "")
    KITE_USER_ID: str = os.getenv("KITE_USER_ID", "")
    KITE_PASSWORD: str = os.getenv("KITE_PASSWORD", "")
    KITE_TOTP_KEY: str = os.getenv("KITE_TOTP_KEY", "")
    KITE_REDIRECT_URL: str = os.getenv("KITE_REDIRECT_URL", "https://money.shadowmarket.ai/api/kite_callback")

    # Claude AI (legacy — kept for backward compatibility)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # OpenAI (legacy — kept for backward compatibility)
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # Grok (xAI) — primary AI provider
    GROK_API_KEY: str = os.getenv("GROK_API_KEY", "")
    GROK_MODEL: str = os.getenv("GROK_MODEL", "grok-3-mini")

    # Kimi (Moonshot) — secondary AI provider
    KIMI_API_KEY: str = os.getenv("KIMI_API_KEY", "")
    KIMI_MODEL: str = os.getenv("KIMI_MODEL", "moonshot-v1-8k")

    # AI provider routing
    AI_PRIMARY_PROVIDER: str = os.getenv("AI_PRIMARY_PROVIDER", "grok")  # "grok" or "kimi"

    # Google OAuth
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")

    # Email OTP (SMTP)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASS: str = os.getenv("SMTP_PASS", "")

    # Mobile OTP (MSG91)
    MSG91_AUTH_KEY: str = os.getenv("MSG91_AUTH_KEY", "")

    # Angel One SmartAPI
    ANGEL_API_KEY: str = os.getenv("ANGEL_API_KEY", "")
    ANGEL_API_SECRET: str = os.getenv("ANGEL_API_SECRET", "")
    ANGEL_CLIENT_ID: str = os.getenv("ANGEL_CLIENT_ID", "")
    ANGEL_PASSWORD: str = os.getenv("ANGEL_PASSWORD", "")
    ANGEL_TOTP_SECRET: str = os.getenv("ANGEL_TOTP_SECRET", "")

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/trading_os")

    # Google Sheets
    GOOGLE_SHEETS_CREDENTIALS: str = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "data/service_account.json")
    GOOGLE_SHEET_ID: str = os.getenv("GOOGLE_SHEET_ID", "")

    # n8n
    N8N_WEBHOOK_BASE: str = os.getenv("N8N_WEBHOOK_BASE", "https://n8n.shadowmarket.ai")

    # MCP Server
    MCP_SERVER_HOST: str = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
    MCP_SERVER_PORT: int = int(os.getenv("MCP_SERVER_PORT", "8001"))

    # RRMS Defaults
    RRMS_CAPITAL: float = float(os.getenv("RRMS_CAPITAL", "100000"))
    RRMS_RISK_PCT: float = float(os.getenv("RRMS_RISK_PCT", "0.02"))
    RRMS_MIN_RRR: float = float(os.getenv("RRMS_MIN_RRR", "3.0"))

    # Debate Validator
    DEBATE_ENABLED: bool = os.getenv("DEBATE_ENABLED", "true").lower() == "true"
    DEBATE_UNCERTAIN_LOW: int = int(os.getenv("DEBATE_UNCERTAIN_LOW", "40"))
    DEBATE_UNCERTAIN_HIGH: int = int(os.getenv("DEBATE_UNCERTAIN_HIGH", "75"))
    DEBATE_ROUNDS: int = int(os.getenv("DEBATE_ROUNDS", "2"))

    # Trade Memory
    TRADE_MEMORY_FILE: str = os.getenv("TRADE_MEMORY_FILE", "data/trade_memory.json")
    MEMORY_TOP_K: int = int(os.getenv("MEMORY_TOP_K", "3"))

    # News Monitor
    NEWSAPI_KEY: str = os.getenv("NEWSAPI_KEY", "")
    NEWS_POLL_INTERVAL_MINUTES: int = int(os.getenv("NEWS_POLL_INTERVAL_MINUTES", "30"))

    # Goodwill Connect (GWC) — OAuth broker API
    GWC_API_KEY: str = os.getenv("GWC_API_KEY", "")
    GWC_API_SECRET: str = os.getenv("GWC_API_SECRET", "")
    GWC_CLIENT_ID: str = os.getenv("GWC_CLIENT_ID", "")
    GWC_REDIRECT_URL: str = os.getenv("GWC_REDIRECT_URL", "https://money.shadowmarket.ai/api/gwc_callback")
    # Goodwill auto-login credentials (used by gwc_auth.refresh_gwc_token)
    GOODWILL_PASSWORD: str = os.getenv("GOODWILL_PASSWORD", "")
    GOODWILL_TOTP_KEY: str = os.getenv("GOODWILL_TOTP_KEY", "")

    # Data Provider
    DATA_PROVIDER_PRIMARY: str = os.getenv("DATA_PROVIDER_PRIMARY", "kite")  # "kite" or "yfinance"

    # OHLCV Cache
    OHLCV_CACHE_ENABLED: bool = os.getenv("OHLCV_CACHE_ENABLED", "true").lower() == "true"
    OHLCV_CACHE_DAILY_TTL_HOURS: int = int(os.getenv("OHLCV_CACHE_DAILY_TTL_HOURS", "12"))
    OHLCV_CACHE_INTRADAY_TTL_MINUTES: int = int(os.getenv("OHLCV_CACHE_INTRADAY_TTL_MINUTES", "5"))

    # Redis (optional — for RealtimeEngine tick cache)
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))

    # Paper Trading (set PAPER_MODE=true to trade without Kite)
    PAPER_MODE: bool = os.getenv("PAPER_MODE", "false").lower() == "true"

    # Authentication (opt-in — set AUTH_ENABLED=true to require login)
    AUTH_ENABLED: bool = os.getenv("AUTH_ENABLED", "false").lower() == "true"
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "sales@shadowmarket.ai")
    ADMIN_PASSWORD_HASH: str = os.getenv("ADMIN_PASSWORD_HASH", "")
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "change-this-in-production")
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))


    # Scanner Review Engine
    SCANNER_REVIEW_ENABLED: bool = os.getenv("SCANNER_REVIEW_ENABLED", "true").lower() == "true"
    SCANNER_REVIEW_HOUR: int = int(os.getenv("SCANNER_REVIEW_HOUR", "15"))

    # F&O Analytics Auto-Monitor (IV rank / PCR / OI / expiry alerts)
    FNO_ANALYTICS_ENABLED: bool = os.getenv("FNO_ANALYTICS_ENABLED", "true").lower() == "true"

    # Self-Development System (postmortem RCA + predictive gate + rules engine)
    SELF_DEV_ENABLED: bool = os.getenv("SELF_DEV_ENABLED", "true").lower() == "true"
    PREDICTOR_BLOCK_THRESHOLD: float = float(os.getenv("PREDICTOR_BLOCK_THRESHOLD", "0.75"))
    PREDICTOR_RETRAIN_HOUR: int = int(os.getenv("PREDICTOR_RETRAIN_HOUR", "16"))  # 4 PM IST, after signal monitor closes last trades
    RULES_ENGINE_ENABLED: bool = os.getenv("RULES_ENGINE_ENABLED", "true").lower() == "true"
    RULES_MINE_ON_RETRAIN: bool = os.getenv("RULES_MINE_ON_RETRAIN", "true").lower() == "true"
    POSTMORTEM_LOOKBACK_DAYS: int = int(os.getenv("POSTMORTEM_LOOKBACK_DAYS", "14"))

    # Stitch Data (ETL to data warehouse)
    STITCH_API_TOKEN: str = os.getenv("STITCH_API_TOKEN", "")
    STITCH_CLIENT_ID: str = os.getenv("STITCH_CLIENT_ID", "")
    STITCH_REGION: str = os.getenv("STITCH_REGION", "us")  # "us" or "eu"

    # Options Enrichment (attach concrete option contracts to FNO futures signals)
    OPTION_SIGNALS_ENABLED: bool = os.getenv("OPTION_SIGNALS_ENABLED", "true").lower() == "true"
    OPTION_IV_DEBIT_MAX: float = float(os.getenv("OPTION_IV_DEBIT_MAX", "40"))
    OPTION_IV_CREDIT_MIN: float = float(os.getenv("OPTION_IV_CREDIT_MIN", "60"))
    OPTION_MIN_DAYS_TO_EXPIRY: int = int(os.getenv("OPTION_MIN_DAYS_TO_EXPIRY", "2"))
    # When true, option enrichment is attempted for any ticker present in the
    # Kite NFO instrument list (all ~220 F&O underlyings). When false, only
    # the curated OPTION_UNIVERSE (4 indices + large-cap stocks) is eligible.
    OPTION_UNIVERSE_ALL_FNO: bool = os.getenv("OPTION_UNIVERSE_ALL_FNO", "true").lower() == "true"

    # Dhan auto-authentication (TOTP + PIN). When both are set, the system
    # generates fresh access tokens at startup and on expiry — no manual
    # /dhantoken paste needed. Uses dhanhq.auth.DhanLogin (SDK v2.2.0+).
    DHAN_TOTP_KEY: str = os.getenv("DHAN_TOTP_KEY", "")
    DHAN_PIN: str = os.getenv("DHAN_PIN", "")

    # Intraday signals (ORB, VWAP, 5m momentum) — separate pipeline from MWA
    # daily-swing. Default false so turning this on is an explicit opt-in.
    INTRADAY_SIGNALS_ENABLED: bool = os.getenv("INTRADAY_SIGNALS_ENABLED", "false").lower() == "true"
    INTRADAY_WATCHLIST: str = os.getenv("INTRADAY_WATCHLIST", "")  # empty → scanner's built-in 30-ticker default
    INTRADAY_SCAN_INTERVAL_SEC: int = int(os.getenv("INTRADAY_SCAN_INTERVAL_SEC", "300"))
    INTRADAY_MAX_SIGNALS_PER_DAY: int = int(os.getenv("INTRADAY_MAX_SIGNALS_PER_DAY", "5"))
    INTRADAY_RRR_FLOOR: float = float(os.getenv("INTRADAY_RRR_FLOOR", "2.0"))

    # Telegram behavior
    TELEGRAM_SIGNALS_ONLY: bool = os.getenv("TELEGRAM_SIGNALS_ONLY", "true").lower() == "true"
    # When true: only send actual trade signal cards to Telegram
    # When false: also send MWA scan summaries, reports, etc.

    # AI model for reports (use haiku for cost savings, sonnet for quality)
    AI_REPORT_MODEL: str = os.getenv("AI_REPORT_MODEL", "claude-haiku-4-5-20251001")


settings = Settings()
