"""Fundamentals ingestion (best-effort).

Primary support: Financial Modeling Prep (FMP) via FMP_API_KEY.
If not configured, returns ok=False.

We fetch a handful of ratios/fields that are commonly used in screening.
"""

from __future__ import annotations

from typing import Dict, Any

import requests

from ..config import settings


def fetch_fundamentals(symbol: str) -> Dict[str, Any]:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {"ok": False, "error": "missing symbol"}
    if not settings.FMP_API_KEY:
        return {"ok": False, "error": "FMP_API_KEY not set"}

    base = "https://financialmodelingprep.com/api/v3"
    try:
        profile = requests.get(f"{base}/profile/{symbol}", params={"apikey": settings.FMP_API_KEY}, timeout=20).json()
        ratios = requests.get(f"{base}/ratios/{symbol}", params={"limit": 1, "apikey": settings.FMP_API_KEY}, timeout=20).json()
        keym = requests.get(f"{base}/key-metrics/{symbol}", params={"limit": 1, "apikey": settings.FMP_API_KEY}, timeout=20).json()

        p0 = (profile or [{}])[0] if isinstance(profile, list) else {}
        r0 = (ratios or [{}])[0] if isinstance(ratios, list) else {}
        k0 = (keym or [{}])[0] if isinstance(keym, list) else {}

        out = {
            "companyName": p0.get("companyName"),
            "sector": p0.get("sector"),
            "industry": p0.get("industry"),
            "marketCap": p0.get("mktCap") or p0.get("marketCap"),
            "price": p0.get("price"),
            "beta": p0.get("beta"),
            "pe": r0.get("priceEarningsRatio"),
            "pb": r0.get("priceToBookRatio"),
            "ps": r0.get("priceToSalesRatio"),
            "roe": r0.get("returnOnEquity"),
            "debtEquity": r0.get("debtEquityRatio"),
            "grossMargin": r0.get("grossProfitMargin"),
            "operatingMargin": r0.get("operatingProfitMargin"),
            "freeCashFlowPerShare": k0.get("freeCashFlowPerShare"),
            "revenuePerShare": k0.get("revenuePerShare"),
            "netIncomePerShare": k0.get("netIncomePerShare"),
        }

        return {"ok": True, "symbol": symbol, "fundamentals": out}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
