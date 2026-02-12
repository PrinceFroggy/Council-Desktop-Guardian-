"""Ticker discovery (best-effort).

Goal: produce a list of candidate symbols to research.

We support three modes:
1) watchlist (NEWS_WATCHLIST)
2) extract tickers from recent RSS/news content (you already have RSS)
3) optional web search providers (Perplexity or Serper) for "small cap ideas" queries

This module is safe-by-default: if no providers/inputs are configured, it returns an empty list.
"""

from __future__ import annotations

import re
from typing import List, Dict, Any, Optional

import requests

from ..config import settings

TICKER_RE = re.compile(r"\b[A-Z]{1,5}\b")


def from_watchlist() -> List[str]:
    wl = (settings.NEWS_WATCHLIST or "").strip()
    if not wl:
        return []
    out = []
    for t in wl.split(","):
        t = t.strip().upper()
        if t and t not in out:
            out.append(t)
    return out


def extract_from_text(text: str, whitelist: Optional[List[str]] = None) -> List[str]:
    """Extract naive US-style tickers from text.

    You can pass a whitelist of valid tickers to reduce false positives.
    """
    if not text:
        return []
    cands = TICKER_RE.findall(text.upper())
    # remove common words
    bad = {"THE","A","AN","AND","OR","FOR","TO","IN","ON","WITH","BY","AT","FROM","AS","IS","ARE","WILL","YOU","I","WE","US","EU","USD","CEO","CPI","GDP","FBI","SEC","ETF","AI"}
    out: List[str] = []
    for c in cands:
        if c in bad:
            continue
        if whitelist and c not in whitelist:
            continue
        if c not in out:
            out.append(c)
    return out


def _perplexity_search(query: str, max_items: int = 10) -> List[str]:
    if not settings.PERPLEXITY_API_KEY:
        return []
    # Perplexity API schemas change; we keep this best-effort.
    try:
        url = "https://api.perplexity.ai/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.PERPLEXITY_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "sonar",
            "messages": [
                {"role": "system", "content": "Return a comma-separated list of US stock tickers only."},
                {"role": "user", "content": query},
            ],
            "temperature": 0.2,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code >= 400:
            return []
        data = resp.json()
        content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        tickers = [t.strip().upper() for t in re.split(r"[,\s]+", content) if t.strip()]
        tickers = [t for t in tickers if re.fullmatch(r"[A-Z]{1,5}", t or "")]
        return tickers[:max_items]
    except Exception:
        return []


def _serper_search(query: str, max_items: int = 10) -> List[str]:
    if not settings.SERPER_API_KEY:
        return []
    try:
        url = "https://google.serper.dev/search"
        headers = {"X-API-KEY": settings.SERPER_API_KEY, "Content-Type": "application/json"}
        resp = requests.post(url, headers=headers, json={"q": query}, timeout=30)
        if resp.status_code >= 400:
            return []
        data = resp.json()
        blob = "\n".join([(r.get("title") or "") + "\n" + (r.get("snippet") or "") for r in (data.get("organic") or [])])
        return extract_from_text(blob)[:max_items]
    except Exception:
        return []


def discover_candidates(seed_text: str = "") -> Dict[str, Any]:
    """Return candidates + provenance."""
    candidates: List[str] = []
    sources: Dict[str, Any] = {}

    wl = from_watchlist()
    if wl:
        candidates.extend(wl)
        sources["watchlist"] = wl

    if seed_text:
        ex = extract_from_text(seed_text)
        if ex:
            candidates.extend(ex)
            sources["seed_text"] = ex[:50]

    # Optional web discovery
    q = "Find 10 interesting small and mid cap US stock tickers discussed recently (return tickers only)."
    p = _perplexity_search(q)
    if p:
        candidates.extend(p)
        sources["perplexity"] = p

    s = _serper_search("undervalued small cap stock ticker")
    if s:
        candidates.extend(s)
        sources["serper"] = s

    # de-dup
    uniq: List[str] = []
    for t in candidates:
        t = t.strip().upper()
        if not t:
            continue
        if t not in uniq:
            uniq.append(t)
    uniq = uniq[: int(settings.AUTOPILOT_MAX_CANDIDATES)]

    return {"ok": True, "candidates": uniq, "sources": sources}
