"""Ticker-focused news fetch (best-effort).

If NEWS_API_KEY is set, we call NewsAPI.org "everything" endpoint.
If not set, returns ok=False.

This complements the existing RSS pipeline (app/scheduler + news_sources.txt).
"""

from __future__ import annotations

from typing import Dict, Any, List

import requests

from ..config import settings


def fetch_ticker_news(symbol: str, days: int = 7, max_items: int = 10) -> Dict[str, Any]:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {"ok": False, "error": "missing symbol"}
    if not settings.NEWS_API_KEY:
        return {"ok": False, "error": "NEWS_API_KEY not set"}

    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": symbol,
            "pageSize": int(max_items),
            "sortBy": "publishedAt",
            "language": "en",
        }
        headers = {"X-Api-Key": settings.NEWS_API_KEY}
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code >= 400:
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        payload = resp.json()
        arts = payload.get("articles") or []
        items = []
        for a in arts[: int(max_items)]:
            items.append({
                "title": a.get("title"),
                "source": (a.get("source") or {}).get("name"),
                "url": a.get("url"),
                "publishedAt": a.get("publishedAt"),
                "description": a.get("description"),
            })
        return {"ok": True, "symbol": symbol, "items": items}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
