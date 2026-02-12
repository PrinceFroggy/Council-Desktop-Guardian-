import os
from pydantic import BaseModel

class Settings(BaseModel):
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REPO_PATH: str = os.getenv("REPO_PATH", ".")
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:7070")

    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM: str = os.getenv("TWILIO_FROM", "")
    APPROVER_PHONE: str = os.getenv("APPROVER_PHONE", "")

    # News -> Signals -> Trade proposals
    NEWS_POLL_INTERVAL_SECONDS: int = int(os.getenv("NEWS_POLL_INTERVAL_SECONDS", "900"))  # 15 minutes
    NEWS_MAX_ITEMS_PER_POLL: int = int(os.getenv("NEWS_MAX_ITEMS_PER_POLL", "25"))
    NEWS_ENABLE_MARKET_HOURS_ONLY: int = int(os.getenv("NEWS_ENABLE_MARKET_HOURS_ONLY", "0"))
    NEWS_PROPOSE_LIVE: int = int(os.getenv("NEWS_PROPOSE_LIVE", "1"))  # include live trade proposal action (still gated)
    NEWS_WATCHLIST: str = os.getenv("NEWS_WATCHLIST", "")  # comma-separated tickers (optional)
    NEWS_SOURCES_FILE: str = os.getenv("NEWS_SOURCES_FILE", "app/news_sources.txt")


    # Live broker (optional)
    TRADING_BROKER: str = os.getenv("TRADING_BROKER", "none")  # none|alpaca
    ALPACA_API_KEY: str = os.getenv("ALPACA_API_KEY", "")
    ALPACA_API_SECRET: str = os.getenv("ALPACA_API_SECRET", "")
    ALPACA_PAPER: int = int(os.getenv("ALPACA_PAPER", "1"))  # 1=paper, 0=live
    ALPACA_BASE_URL: str = os.getenv("ALPACA_BASE_URL", "")  # optional override

    # Paper trading
    PAPER_START_CASH: float = float(os.getenv("PAPER_START_CASH", "100000"))

    # ===== Quant / Signals / Autopilot (new) =====
    # Master switch for the fully-automated quant loop.
    AUTOPILOT_ENABLED: int = int(os.getenv("AUTOPILOT_ENABLED", "0"))
    # If 1, autopilot is allowed to place orders automatically. If 0, it only produces reports.
    AUTOPILOT_CAN_EXECUTE: int = int(os.getenv("AUTOPILOT_CAN_EXECUTE", "0"))
    AUTOPILOT_INTERVAL_SECONDS: int = int(os.getenv("AUTOPILOT_INTERVAL_SECONDS", "1800"))  # 30 min
    AUTOPILOT_MAX_CANDIDATES: int = int(os.getenv("AUTOPILOT_MAX_CANDIDATES", "10"))
    AUTOPILOT_MAX_TRADES_PER_RUN: int = int(os.getenv("AUTOPILOT_MAX_TRADES_PER_RUN", "2"))
    AUTOPILOT_MIN_SCORE: float = float(os.getenv("AUTOPILOT_MIN_SCORE", "0.70"))
    # If 1, autopilot will skip trades that Council votes NO. If 0, Council is monitor-only.
    AUTOPILOT_RESPECT_COUNCIL: int = int(os.getenv("AUTOPILOT_RESPECT_COUNCIL", "0"))

    # Risk controls (defaults are conservative)
    RISK_MAX_POSITION_PCT: float = float(os.getenv("RISK_MAX_POSITION_PCT", "0.10"))  # 10% of equity
    RISK_MAX_SECTOR_PCT: float = float(os.getenv("RISK_MAX_SECTOR_PCT", "0.30"))      # 30% sector cap
    RISK_DEFAULT_STOP_ATR: float = float(os.getenv("RISK_DEFAULT_STOP_ATR", "2.0"))
    RISK_DEFAULT_TAKEPROFIT_RR: float = float(os.getenv("RISK_DEFAULT_TAKEPROFIT_RR", "2.0"))

    # Market/price data for indicators/backtests
    PRICE_DATA_PROVIDER: str = os.getenv("PRICE_DATA_PROVIDER", "yfinance")  # yfinance|alpaca
    BACKTEST_LOOKBACK_DAYS: int = int(os.getenv("BACKTEST_LOOKBACK_DAYS", "365"))

    # Optional external APIs (set env vars to enable)
    FMP_API_KEY: str = os.getenv("FMP_API_KEY", "")  # Financial Modeling Prep
    NEWS_API_KEY: str = os.getenv("NEWS_API_KEY", "")
    REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "council-desktop-guardian/1.0")
    GOOGLE_TRENDS_GEO: str = os.getenv("GOOGLE_TRENDS_GEO", "US")
    CONGRESS_API_KEY: str = os.getenv("CONGRESS_API_KEY", "")
    FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")

    # Optional web search providers for ticker discovery
    PERPLEXITY_API_KEY: str = os.getenv("PERPLEXITY_API_KEY", "")
    SERPER_API_KEY: str = os.getenv("SERPER_API_KEY", "")

    # SaaS / billing (optional)
    SAAS_ENABLED: int = int(os.getenv("SAAS_ENABLED", "0"))
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./council.db")


settings = Settings()