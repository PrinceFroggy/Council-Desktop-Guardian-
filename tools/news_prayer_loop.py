"""
News → Council → Telegram "Prayer" Loop

Every N minutes:
- Pulls latest headlines from NewsAPI
- Packs them into an /plan request to your FastAPI server
- Council reasons over the snippets
- If Council says YES, it Telegrams you with the news + prediction + approval code
"""

import os
import time
import json
import requests
import re
import yfinance as yf
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "").strip()
NEWS_QUERY = os.getenv(
    "NEWS_QUERY",
    "stock market OR earnings OR guidance OR downgrade OR upgrade"
).strip()
NEWS_LANGUAGE = os.getenv("NEWS_LANGUAGE", "en").strip()
NEWS_PAGE_SIZE = int(os.getenv("NEWS_PAGE_SIZE", "10"))
NEWS_POLL_INTERVAL_SECONDS = int(os.getenv("NEWS_POLL_INTERVAL_SECONDS", "300"))

PLAN_ENDPOINT = os.getenv("PLAN_ENDPOINT", "http://localhost:7070/plan").strip()

RAG_MODE = os.getenv("NEWS_RAG_MODE", os.getenv("RAG_MODE", "naive")).strip()

DRY_RUN = os.getenv("NEWS_DRY_RUN", "1").strip() in (
    "1", "true", "True", "yes", "YES"
)

SEEN_IDS_PATH = os.getenv("NEWS_SEEN_IDS_PATH", ".news_seen_ids.json").strip()
MAX_SEEN = int(os.getenv("NEWS_MAX_SEEN", "300"))


# ------------------------------------------------------------------
# Ticker extraction
# ------------------------------------------------------------------

TICKER_STOPWORDS = {
    "A", "AN", "THE", "AND", "OR", "OF", "IN", "ON", "TO", "FOR",
    "GET", "SET", "LOW", "HIGH", "COST", "YEAR", "SHOCK", "FLAGS",
    "BOOST", "SPORT", "NEW", "Q", "Q1", "Q2", "Q3", "Q4", "FY",
    "EPS", "CEO", "CFO", "SEC"
}

# Only extract tickers that appear like tickers in text:
# - $AAPL
# - (AAPL)
# - NASDAQ: AAPL
# - NYSE: TSLA
# - Ticker: AAPL
# - 005930.KS / SHOP.TO
TICKER_PATTERNS = [
    re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z])?)\b"),
    re.compile(r"\(([A-Z]{1,5}(?:\.[A-Z])?)\)"),
    re.compile(r"\b(?:NASDAQ|NYSE|AMEX)\s*:\s*([A-Z]{1,5}(?:\.[A-Z])?)\b"),
    re.compile(r"\b(?:Ticker|Symbol)\s*:\s*([A-Z]{1,5}(?:\.[A-Z])?)\b", re.IGNORECASE),
    re.compile(r"\b(\d{4,6}\.[A-Z]{2})\b"),      # 005930.KS
    re.compile(r"\b([A-Z]{1,4}\.[A-Z]{1,3})\b"), # SHOP.TO
]


def extract_ticker_candidates(text: str) -> list[str]:
    text_up = text.upper()
    found = []

    for rx in TICKER_PATTERNS:
        found.extend(rx.findall(text_up))

    # de-dupe + filter stopwords
    out = []
    seen = set()
    for sym in found:
        sym = sym.strip().upper()
        if sym in TICKER_STOPWORDS:
            continue
        if sym not in seen:
            seen.add(sym)
            out.append(sym)

    return out


def validate_tickers(cands: list[str], limit: int = 8) -> list[str]:
    """
    Fast validation:
    - Use yfinance fast_info where possible
    - Avoid long history calls (slow + noisy)
    """
    valid = []
    for sym in cands:
        if len(valid) >= limit:
            break
        try:
            t = yf.Ticker(sym)
            fi = getattr(t, "fast_info", None)

            # fast_info sometimes triggers network; if it exists and has any market fields, accept
            if fi and (fi.get("last_price") is not None or fi.get("currency") is not None):
                valid.append(sym)
                continue

            # fallback: tiny history request but keep it minimal
            hist = t.history(period="5d", interval="1d")
            if hist is not None and len(hist) > 0:
                valid.append(sym)

        except Exception:
            # swallow everything; don't print
            pass

    return valid


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _now_utc():
    return datetime.now(timezone.utc)


def _load_seen() -> set[str]:
    try:
        return set(json.loads(open(SEEN_IDS_PATH).read()))
    except Exception:
        return set()


def _save_seen(seen: set[str]):
    try:
        open(SEEN_IDS_PATH, "w").write(json.dumps(list(seen)[-MAX_SEEN:]))
    except Exception:
        pass


# ------------------------------------------------------------------
# News
# ------------------------------------------------------------------

def fetch_news() -> list[dict]:
    if not NEWS_API_KEY:
        raise RuntimeError("NEWS_API_KEY missing")

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
    return resp.json().get("articles", [])


def build_snippet_block(articles: list[dict]):
    snippets = []
    ids = []

    for a in articles:
        title = (a.get("title") or "").strip()
        source = ((a.get("source") or {}) or {}).get("name") or ""
        desc = (a.get("description") or "").strip()
        url = (a.get("url") or "").strip()

        aid = (url or title)[:200]
        if not aid:
            continue

        ids.append(aid)

        line = f"- {title}"
        if source:
            line += f" ({source})"
        if desc:
            line += f"\n  {desc[:180]}"

        snippets.append(line)

    return "\n\n".join(snippets), ids


# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------

def call_plan(action_request: str) -> dict:
    payload = {
        "action_request": action_request,
        "proposed_plan": {"type": "trade_signal", "actions": []},
        "rag_mode": RAG_MODE,
        "dry_run": DRY_RUN,
    }

    r = requests.post(PLAN_ENDPOINT, json=payload, timeout=300)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------

def main():
    seen = _load_seen()

    print(f"[news-prayer] endpoint={PLAN_ENDPOINT} interval={NEWS_POLL_INTERVAL_SECONDS}s")

    while True:
        try:
            articles = fetch_news()

            block, ids = build_snippet_block(articles)
            fresh = [(i, a) for i, a in zip(ids, articles) if i not in seen]

            if not fresh:
                print("No new headlines.")

            else:
                fresh_articles = [a for _, a in fresh]

                # ---------------- TICKER EXTRACTION ----------------
                text_blob = " ".join(
                    ((a.get("title") or "") + " " + (a.get("description") or "")).strip()
                    for a in fresh_articles
                )

                candidates = extract_ticker_candidates(text_blob)
                valid_tickers = validate_tickers(candidates, limit=8)

                fresh_block, fresh_ids = build_snippet_block(fresh_articles)
		top5 = fresh_articles[:5]
		top5_lines = []
		for a in top5:
    			title = (a.get("title") or "").strip()
    			src = ((a.get("source") or {}) or {}).get("name") or ""
    			top5_lines.append(f"- {title}" + (f" ({src})" if src else ""))
		top5_block = "\n".join(top5_lines)

                tickers_line = ", ".join(valid_tickers) if valid_tickers else "(none found)"

                prompt = f"""
You must output ONLY JSON.
- If validated_tickers is empty, signals must be [] (empty list).

Key headlines (top 5):
{top5_block}

validated_tickers: [{tickers_line}]

news_snippets:
{fresh_block}

Return:
{{
  "signals":[{{"ticker":"AAPL","direction":"bullish","confidence":60,"action":"WATCH","reason":"..."}}],
  "message_to_human":"short prayer"
}}
""".strip()

                result = call_plan(prompt)

                print(
                    f"[{_now_utc().isoformat()}] "
                    f"Sent /plan with {len(fresh_articles)} headlines -> {result.get('status')}"
                )

                for fid in fresh_ids:
                    seen.add(fid)
                _save_seen(seen)

        except Exception as e:
            print("ERROR:", e)

        time.sleep(NEWS_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

