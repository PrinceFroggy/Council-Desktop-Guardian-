"""
News → Council → Telegram "Prayer" Loop

Every N minutes:
- Pulls latest headlines from NewsAPI
- Packs them into an /plan request to your FastAPI server
- Council reasons over the snippets
- If Council says YES, it Telegrams you with the news + prediction + approval code

Run:
  python tools/news_prayer_loop.py

Requires:
  - FastAPI server running (uvicorn app.main:app --env-file .env)
  - .env configured (NEWS_API_KEY, TELEGRAM_*, etc.)
"""

import os
import time
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "").strip()
NEWS_QUERY = os.getenv("NEWS_QUERY", "stock market OR earnings OR guidance OR downgrade OR upgrade").strip()
NEWS_LANGUAGE = os.getenv("NEWS_LANGUAGE", "en").strip()
NEWS_PAGE_SIZE = int(os.getenv("NEWS_PAGE_SIZE", "10"))
NEWS_POLL_INTERVAL_SECONDS = int(os.getenv("NEWS_POLL_INTERVAL_SECONDS", "300"))

# Where your FastAPI is running
PLAN_ENDPOINT = os.getenv("PLAN_ENDPOINT", "http://localhost:7070/plan").strip()

# How Council should build context
RAG_MODE = os.getenv("NEWS_RAG_MODE", os.getenv("RAG_MODE", "naive")).strip()  # naive|advanced|graphrag|agentic|finetune|cag

# Keep this safe by default (no execution)
DRY_RUN = os.getenv("NEWS_DRY_RUN", "1").strip() in ("1", "true", "True", "yes", "YES")

# Simple de-dupe so you don't spam the same headlines
SEEN_IDS_PATH = os.getenv("NEWS_SEEN_IDS_PATH", ".news_seen_ids.json").strip()
MAX_SEEN = int(os.getenv("NEWS_MAX_SEEN", "300"))

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
        open(SEEN_IDS_PATH, "w", encoding="utf-8").write(json.dumps(lst, ensure_ascii=False, indent=2))
    except Exception:
        pass

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
    data = resp.json()
    return data.get("articles", []) or []

def build_snippet_block(articles: list[dict]) -> tuple[str, list[str]]:
    snippets = []
    ids = []
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
            line += f"\n  {desc}"
        if url:
            line += f"\n  {url}"
        snippets.append(line)

    block = "\n\n".join(snippets)
    return block, ids

def call_plan(action_request: str) -> dict:
    payload = {
        "action_request": action_request,
        "proposed_plan": {"type": "trade_signal", "actions": []},
        "rag_mode": RAG_MODE,
        "dry_run": DRY_RUN,
    }
    resp = requests.post(PLAN_ENDPOINT, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()

def main():
    seen = _load_seen()
    print(f"[news-prayer] Starting. endpoint={PLAN_ENDPOINT} interval={NEWS_POLL_INTERVAL_SECONDS}s rag_mode={RAG_MODE} dry_run={DRY_RUN}")
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

                prompt = f"""
You are the Council. I want you to "pray" to me with actionable investing guidance.

Task:
1) Read the news snippets below.
2) Identify any public stock tickers likely impacted.
3) For each impacted ticker, give: (a) direction prediction (bullish/bearish/unclear), (b) confidence 0-100, (c) brief reasoning, (d) a conservative action: INVEST (small), WATCH, or PASS.
4) Write a short message_to_human that includes the headline snippets and your prediction.
5) Keep it safe: DO NOT execute anything automatically; only propose and ask me for approval.

News snippets:
{fresh_block}
""".strip()

                result = call_plan(prompt)
                pending_id = result.get("pending_id")
                status = result.get("status")
                print(f"[{_now_utc().isoformat()}] Sent /plan with {len(fresh_articles)} new headlines -> pending_id={pending_id} status={status}")

                for fid in fresh_ids:
                    seen.add(fid)
                _save_seen(seen)

        except Exception as e:
            print(f"[{_now_utc().isoformat()}] ERROR: {e}")

        time.sleep(NEWS_POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
