"""Google Trends signal (best-effort).

Uses pytrends. No API key required.
We compute:
- latest interest
- 30d mean interest
- momentum = latest - mean

If pytrends is not installed, returns ok=False.
"""

from __future__ import annotations

from typing import Dict, Any

from ..config import settings


def fetch_trends(symbol: str, geo: str | None = None) -> Dict[str, Any]:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {"ok": False, "error": "missing symbol"}

    try:
        from pytrends.request import TrendReq  # type: ignore
    except Exception:
        return {"ok": False, "error": "pytrends not installed"}

    geo = (geo or settings.GOOGLE_TRENDS_GEO or "US").upper()

    try:
        pytrends = TrendReq(hl="en-US", tz=360)
        kw_list = [symbol]
        pytrends.build_payload(kw_list, timeframe="today 3-m", geo=geo)
        df = pytrends.interest_over_time()
        if df is None or len(df) == 0:
            return {"ok": False, "error": "no trends data"}
        series = df[symbol]
        latest = float(series.iloc[-1])
        mean_30 = float(series.tail(30).mean()) if len(series) >= 30 else float(series.mean())
        momentum = float(latest - mean_30)
        return {
            "ok": True,
            "symbol": symbol,
            "geo": geo,
            "latest": latest,
            "mean_30": mean_30,
            "momentum": momentum,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
