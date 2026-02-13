""" 
News → Council → Telegram "Prayer" Loop

Every N minutes:
- Pulls latest headlines from NewsAPI
- Extracts ticker candidates (strict patterns) and validates them via yfinance
- Builds a cautious briefing prompt for Council
- Sends /plan to your FastAPI server

What you should expect:
- Telegram message arrives with summary + tickers + BUY/SELL/PASS suggestion + approval code
- If you reply YES <code>, the server executes the proposed plan:
    - PASS (notify_only) -> no trade
    - BUY/SELL -> paper_trade (default) or alpaca_order (if enabled)

Run:
  python tools/news_prayer_loop.py

Env (minimum):
  NEWS_API_KEY=...
  TELEGRAM_* (in server .env)

Optional (trading):
  NEWS_TRADING_ENABLED=1
  NEWS_TRADE_QTY=1
  NEWS_BROKER=paper|alpaca
  NEWS_BROKER_MODE=paper|live   (alpaca only)
  ALPACA_* (in server .env)

Notes:
- This script only POSTS to /plan. Telegram messages are sent by the server.
"""

import os
import time
import json
import re
import logging
import warnings
from datetime import datetime, timezone

import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

# -----------------------------
# Quiet noisy libs
# -----------------------------
warnings.filterwarnings("ignore")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

# -----------------------------
# ENV
# -----------------------------
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "").strip()
NEWS_QUERY = os.getenv(
    "NEWS_QUERY",
    "stock market OR earnings OR guidance OR downgrade OR upgrade",
).strip()
NEWS_LANGUAGE = os.getenv("NEWS_LANGUAGE", "en").strip()
NEWS_PAGE_SIZE = int(os.getenv("NEWS_PAGE_SIZE", "10"))
NEWS_POLL_INTERVAL_SECONDS = int(os.getenv("NEWS_POLL_INTERVAL_SECONDS", "300"))

PLAN_ENDPOINT = os.getenv("PLAN_ENDPOINT", "http://localhost:7070/plan").strip()

RAG_MODE = os.getenv("NEWS_RAG_MODE", os.getenv("RAG_MODE", "finetune")).strip()

SEEN_IDS_PATH = os.getenv("NEWS_SEEN_IDS_PATH", ".news_seen_ids.json").strip()
MAX_SEEN = int(os.getenv("NEWS_MAX_SEEN", "300"))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if raw in ("1", "true", "yes", "y", "on"):
        return True
    if raw in ("0", "false", "no", "n", "off"):
        return False
    return default


DRY_RUN = _env_bool("NEWS_DRY_RUN", _env_bool("DRY_RUN", False))
NEWS_TRADING_ENABLED = _env_bool("NEWS_TRADING_ENABLED", False)
NEWS_BROKER = os.getenv("NEWS_BROKER", "paper").strip().lower()  # paper|alpaca
NEWS_BROKER_MODE = os.getenv("NEWS_BROKER_MODE", "paper").strip().lower()  # paper|live (alpaca only)
NEWS_TRADE_QTY = int(os.getenv("NEWS_TRADE_QTY", "1"))


# -----------------------------
# Strict ticker extraction
# -----------------------------
_TICKER_PATTERNS = [
    re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z])?)\b"),  # $AAPL, $BRK.B
    re.compile(r"\(([A-Z]{1,5}(?:\.[A-Z])?)\)"),  # (AAPL)
    re.compile(r"\b(?:NASDAQ|NYSE|AMEX)\s*:\s*([A-Z]{1,5}(?:\.[A-Z])?)\b"),
    re.compile(r"\b(?:Ticker|Symbol)\s*:\s*([A-Z]{1,5}(?:\.[A-Z])?)\b", re.I),
    re.compile(r"\b(\d{4,6}\.[A-Z]{2})\b"),  # 005930.KS
    re.compile(r"\b([A-Z]{1,4}\.[A-Z]{1,3})\b"),  # SHOP.TO
]


def extract_ticker_candidates(text: str) -> list[str]:
    if not text:
        return []
    t = text.upper()
    found: list[str] = []
    for rx in _TICKER_PATTERNS:
        found.extend(rx.findall(t))
    # normalize + unique
    seen = set()
    out = []
    for s in found:
        s = (s or "").strip().upper()
        if not s:
            continue
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out[:25]


def validate_tickers(candidates: list[str], limit: int = 8) -> list[str]:
    """Best-effort validation: keep tickers that yfinance recognizes."""
    out: list[str] = []
    for sym in candidates:
        if len(out) >= limit:
            break
        try:
            info = yf.Ticker(sym).fast_info
            # fast_info can exist but be empty; check last_price/last_close if present
            last = None
            if isinstance(info, dict):
                last = info.get("last_price") or info.get("lastClose") or info.get("last_close")
            if last is not None:
                out.append(sym)
        except Exception:
            continue
    return out


def get_last_price(symbol: str) -> float | None:
    try:
        info = yf.Ticker(symbol).fast_info
        if isinstance(info, dict):
            v = info.get("last_price") or info.get("lastClose") or info.get("last_close")
            if v is not None:
                return float(v)
    except Exception:
        pass
    return None


# -----------------------------
# Seen IDs
# -----------------------------

def _load_seen() -> set[str]:
    try:
        return set(json.loads(open(SEEN_IDS_PATH).read()))
    except Exception:
        return set()


def _save_seen(seen: set[str]) -> None:
    try:
        open(SEEN_IDS_PATH, "w").write(json.dumps(list(seen)[-MAX_SEEN:], indent=2))
    except Exception:
        pass


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


# -----------------------------
# News
# -----------------------------

def fetch_news() -> list[dict]:
    if not NEWS_API_KEY:
        raise RuntimeError("NEWS_API_KEY is empty. Put your NewsAPI key in .env")

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": NEWS_QUERY,
        "language": NEWS_LANGUAGE,
        "pageSize": NEWS_PAGE_SIZE,
        "sortBy": "publishedAt",
        "apiKey": NEWS_API_KEY,
    }

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("articles", []) or []


def build_snippet_block(articles: list[dict]) -> tuple[str, list[str]]:
    snippets: list[str] = []
    ids: list[str] = []

    for a in articles:
        title = (a.get("title") or "").strip()
        source = ((a.get("source") or {}) or {}).get("name") or ""
        published = (a.get("publishedAt") or "").strip()
        url = (a.get("url") or "").strip()
        desc = (a.get("description") or "").strip()

        aid = (url or title or "")[:220]
        if not aid:
            continue

        ids.append(aid)

        line = f"- {title}"
        if source:
            line += f" ({source})"
        if published:
            line += f" [{published}]"
        if desc:
            line += f"\n  {desc[:220]}{'...' if len(desc) > 220 else ''}"

        snippets.append(line)

    return "\n\n".join(snippets), ids


def simple_reco_from_text(text: str) -> str:
    """Very basic heuristic so we always have *some* suggestion.
    Council still makes the final call; this just prevents empty messages.
    """
    t = (text or "").lower()
    sell_words = ["downgrade", "miss", "lawsuit", "fraud", "recall", "cuts", "layoff", "warn"]
    buy_words = ["upgrade", "beats", "record", "raises guidance", "strong demand", "approval"]

    score = 0
    for w in buy_words:
        if w in t:
            score += 1
    for w in sell_words:
        if w in t:
            score -= 1

    if score >= 1:
        return "BUY"
    if score <= -1:
        return "SELL"
    return "PASS"


# -----------------------------
# API
# -----------------------------

def call_plan(action_request: str, proposed_plan: dict) -> dict:
    payload = {
        "action_request": action_request,
        "proposed_plan": proposed_plan,
        "rag_mode": RAG_MODE,
        "dry_run": DRY_RUN,
    }

    resp = requests.post(
        PLAN_ENDPOINT,
        json=payload,
        headers={"X-Caller": "news_prayer_loop"},
        timeout=300,
    )

    resp.raise_for_status()
    return resp.json()


# -----------------------------
# Main
# -----------------------------

def main():
    seen = _load_seen()

    print(
        f"[news-prayer] endpoint={PLAN_ENDPOINT} interval={NEWS_POLL_INTERVAL_SECONDS}s rag_mode={RAG_MODE} dry_run={DRY_RUN}"
    )
    print(f"[news-prayer] query: {NEWS_QUERY}")
    print(f"[news-prayer] trading_enabled={NEWS_TRADING_ENABLED} broker={NEWS_BROKER} broker_mode={NEWS_BROKER_MODE} qty={NEWS_TRADE_QTY}")

    while True:
        try:
            articles = fetch_news()

            # only consider fresh items
            block, ids = build_snippet_block(articles)
            fresh = [(i, a) for i, a in zip(ids, articles) if i not in seen]

            if not fresh:
                print(f"[{_now_utc()}] No new headlines.")
                time.sleep(NEWS_POLL_INTERVAL_SECONDS)
                continue

            fresh_articles = [a for _, a in fresh]
            fresh_block, fresh_ids = build_snippet_block(fresh_articles)

            # Extract + validate tickers
            text_blob = " ".join(
                ((a.get("title") or "") + " " + (a.get("description") or "")).strip()
                for a in fresh_articles
            )
            candidates = extract_ticker_candidates(text_blob)
            valid_tickers = validate_tickers(candidates, limit=8)
            tickers_line = ", ".join(valid_tickers) if valid_tickers else "(none detected)"

            # Local heuristic
            local_reco = simple_reco_from_text(text_blob)

            # Ask Council for a human-readable briefing + BUY/SELL/PASS
            action_request = (
                "Create a cautious, neutral market news briefing for a human.\n"
                "Include: (1) a 3–6 bullet summary, (2) relevant tickers, (3) a BUY/SELL/PASS suggestion with confidence (0–100) and why, "
                "and (4) a clear 'not financial advice' disclaimer.\n\n"
                f"Validated tickers (choose only from these, do not invent new tickers): {tickers_line}\n"
                f"Local heuristic suggestion (for reference only): {local_reco}\n\n"
                "News snippets:\n"
                f"{fresh_block}"
            )

            # Proposed plan
            proposed_plan: dict = {"type": "notify_only", "actions": []}

            if NEWS_TRADING_ENABLED and valid_tickers and local_reco in ("BUY", "SELL"):
                sym = valid_tickers[0]

                if NEWS_BROKER == "alpaca":
                    proposed_plan = {
                        "type": "trading",
                        "actions": [
                            {
                                "name": "alpaca_order",
                                "symbol": sym,
                                "side": "buy" if local_reco == "BUY" else "sell",
                                "qty": NEWS_TRADE_QTY,
                                "order_type": os.getenv("NEWS_ORDER_TYPE", "market"),
                                "time_in_force": os.getenv("NEWS_TIME_IN_FORCE", "day"),
                                "broker_mode": NEWS_BROKER_MODE,
                                # live trades require explicit confirmation at approval time
                                "confirm_live_trade": False,
                            }
                        ],
                    }
                else:
                    # paper trading: include an approximate quote so execution can proceed
                    px = get_last_price(sym) or 0.0
                    proposed_plan = {
                        "type": "trading",
                        "actions": [
                            {
                                "name": "paper_trade",
                                "ticker": sym,
                                "side": "buy" if local_reco == "BUY" else "sell",
                                "qty": NEWS_TRADE_QTY,
                                "price": float(px),
                                "requires_quote": False,
                                "price_confirmed": True,
                            }
                        ],
                    }

            result = call_plan(action_request, proposed_plan)
            pending_id = result.get("pending_id")
            status = result.get("status")

            print(
                f"[{_now_utc()}] Sent /plan with {len(fresh_articles)} headlines -> pending_id={pending_id} status={status}"
            )

            for fid in fresh_ids:
                seen.add(fid)
            _save_seen(seen)

        except Exception as e:
            print(f"[{_now_utc()}] ERROR: {e}")

        time.sleep(NEWS_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
