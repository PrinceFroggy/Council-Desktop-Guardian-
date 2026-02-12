"""
News → Council → Telegram "Prayer" Loop

Every N minutes:
- Pulls latest headlines from NewsAPI
- Packs them into an /plan request to your FastAPI server
- Council reasons over the snippets
- Telegram pings you with news + prediction + approval code (your server handles Telegram)

Run:
  python tools/news_prayer_loop.py

Requires:
  - FastAPI server running (uvicorn app.main:app --env-file .env)
  - .env configured (NEWS_API_KEY, TELEGRAM_*, etc.)
"""

import os
import time
import json
import re
import io
import logging
import warnings
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone

import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

# -----------------------------
# Quiet noisy libs (yfinance / urllib3)
# -----------------------------
warnings.filterwarnings("ignore")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

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

# Always keep this safe by default
DRY_RUN = True

SEEN_IDS_PATH = os.getenv("NEWS_SEEN_IDS_PATH", ".news_seen_ids.json").strip()
MAX_SEEN = int(os.getenv("NEWS_MAX_SEEN", "300"))

# ------------------------------------------------------------------
# Ticker extraction (STRICT: only $TICKER, (TICKER), NASDAQ: TICKER, etc.)
# ------------------------------------------------------------------

TICKER_STOPWORDS = {
    "A", "AN", "THE", "AND", "OR", "OF", "IN", "ON", "TO", "FOR", "WITH", "AT", "BY", "FROM",
    "GET", "SET", "LOW", "HIGH", "COST", "YEAR", "SHOCK", "FLAGS", "BOOST", "SPORT", "NEW",
    "Q", "Q1", "Q2", "Q3", "Q4", "FY", "EPS", "CEO", "CFO", "SEC", "USA", "EU", "UK",
    "CHINA", "INDIA", "JAPAN", "KOREA", "EUROPE",
}

TICKER_PATTERNS = [
    re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z])?)\b"),  # $AAPL, $BRK.B
    re.compile(r"\(([A-Z]{1,5}(?:\.[A-Z])?)\)"),  # (AAPL)
    re.compile(r"\b(?:NASDAQ|NYSE|AMEX)\s*:\s*([A-Z]{1,5}(?:\.[A-Z])?)\b"),  # NASDAQ: AAPL
    re.compile(r"\b(?:Ticker|Symbol)\s*:\s*([A-Z]{1,5}(?:\.[A-Z])?)\b", re.IGNORECASE),  # Ticker: AAPL
    re.compile(r"\b(\d{4,6}\.[A-Z]{2})\b"),  # 005930.KS
    re.compile(r"\b([A-Z]{1,4}\.[A-Z]{1,3})\b"),  # SHOP.TO
]


def _looks_plausible(sym: str) -> bool:
    sym = sym.strip().upper()
    if not sym:
        return False
    if sym in TICKER_STOPWORDS:
        return False
    if sym.count(".") > 1:
        return False
    if sym.endswith(".") or sym.startswith("."):
        return False
    # avoid very common 2-letter words that slip through
    if sym in {"AS", "AT", "AM", "PM", "IT", "IS", "BE", "WE", "US"}:
        return False
    return True


def extract_ticker_candidates(text: str) -> list[str]:
    text_up = text.upper()
    found: list[str] = []

    for rx in TICKER_PATTERNS:
        found.extend(rx.findall(text_up))

    # de-dupe, preserve order
    out: list[str] = []
    seen: set[str] = set()

    for sym in found:
        sym = sym.strip().upper()
        if not _looks_plausible(sym):
            continue
        if sym not in seen:
            seen.add(sym)
            out.append(sym)

    return out


def validate_tickers(cands: list[str], limit: int = 8) -> list[str]:
    """
    Validate tickers quietly (no console spam).
    Uses yfinance history with stdout/stderr redirected.
    """
    valid: list[str] = []

    for sym in cands:
        if len(valid) >= limit:
            break
        if not _looks_plausible(sym):
            continue

        buf = io.StringIO()
        try:
            with redirect_stdout(buf), redirect_stderr(buf):
                t = yf.Ticker(sym)
                hist = t.history(period="5d", interval="1d")
            if hist is not None and len(hist) > 0:
                valid.append(sym)
        except Exception:
            pass

    return valid


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _now_utc():
    return datetime.now(timezone.utc)


def _load_seen() -> set[str]:
    try:
        data = json.loads(open(SEEN_IDS_PATH, "r", encoding="utf-8").read())
        return set(data if isinstance(data, list) else [])
    except Exception:
        return set()


def _save_seen(seen: set[str]) -> None:
    try:
        lst = list(seen)[-MAX_SEEN:]
        open(SEEN_IDS_PATH, "w", encoding="utf-8").write(
            json.dumps(lst, ensure_ascii=False, indent=2)
        )
    except Exception:
        pass


# ------------------------------------------------------------------
# News
# ------------------------------------------------------------------

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


# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------

def call_plan(action_request: str) -> dict:
    # IMPORTANT: make it clearly non-executing so council is less likely to reject
    payload = {
        "action_request": action_request,
        "proposed_plan": {"type": "notify_only", "actions": []},  # <-- changed
        "rag_mode": RAG_MODE,
        "dry_run": True,  # <-- forced true
    }

    resp = requests.post(PLAN_ENDPOINT, json=payload, headers={"X-Caller": "news_prayer_loop"}, timeout=300)
    resp.raise_for_status()
    return resp.json()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    seen = _load_seen()
    print(
        f"[news-prayer] endpoint={PLAN_ENDPOINT} interval={NEWS_POLL_INTERVAL_SECONDS}s rag_mode={RAG_MODE} dry_run={DRY_RUN}"
    )
    print(f"[news-prayer] query: {NEWS_QUERY}")

    while True:
        try:
            articles = fetch_news()
            block, ids = build_snippet_block(articles)

            fresh = [(i, a) for i, a in zip(ids, articles) if i not in seen]

            if not fresh:
                print(f"[{_now_utc().isoformat()}] No new headlines.")
            else:
                fresh_articles = [a for _, a in fresh]
                fresh_block, fresh_ids = build_snippet_block(fresh_articles)

                # Build a text blob from titles/descriptions to extract candidates
                text_blob = " ".join(
                    ((a.get("title") or "") + " " + (a.get("description") or "")).strip()
                    for a in fresh_articles
                )

                candidates = extract_ticker_candidates(text_blob)
                valid_tickers = validate_tickers(candidates, limit=8)

                tickers_line = ", ".join(valid_tickers) if valid_tickers else ""

                # Keep prompt strict and JSON-only. Also: WATCH/PASS only to reduce council rejection.
                prompt = f"""
Create a cautious NEWS BRIEFING for a human.

Constraints:
- No trading, no orders, no “buy/sell” recommendations.
- Only allow actions: WATCH or PASS.
- Choose up to 3 tickers ONLY from this validated list (do not invent tickers): {tickers_line or "(none)"}
- If the validated list is empty, do not suggest any tickers.

Include in your message:
- 3–5 key headlines (very short)
- The top ticker (if any) + WATCH/PASS + confidence (0–100)
- Ask me to reply YES/NO if I want to continue monitoring.

News snippets:
{fresh_block}
""".strip()

                result = call_plan(prompt)
                pending_id = result.get("pending_id")
                status = result.get("status")

                print(
                    f"[{_now_utc().isoformat()}] Sent /plan with {len(fresh_articles)} headlines "
                    f"-> pending_id={pending_id} status={status}"
                )

                for fid in fresh_ids:
                    seen.add(fid)
                _save_seen(seen)

        except Exception as e:
            print(f"[{_now_utc().isoformat()}] ERROR: {e}")

        time.sleep(NEWS_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()