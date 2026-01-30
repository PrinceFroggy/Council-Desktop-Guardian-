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


settings = Settings()