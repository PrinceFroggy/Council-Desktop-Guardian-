"""Congressional trading data (best-effort).

Data sources vary. This module supports:
- QuiverQuant API (if CONGRESS_API_KEY is set)

If no API key is configured, returns ok=False.

Note: This is informational. It should never be used as the sole reason for a trade.
"""

from __future__ import annotations

from typing import Dict, Any

import requests

from ..config import settings


def fetch_congress_trades(symbol: str) -> Dict[str, Any]:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {"ok": False, "error": "missing symbol"}

    if not settings.CONGRESS_API_KEY:
        return {"ok": False, "error": "CONGRESS_API_KEY not set"}

    # QuiverQuant: https://api.quiverquant.com
    # Endpoint examples change over time; we keep this best-effort and robust.
    try:
        url = "https://api.quiverquant.com/beta/live/congresstrading"
        headers = {"Authorization": f"Token {settings.CONGRESS_API_KEY}"}
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code >= 400:
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        # filter by ticker
        rows = [r for r in (data or []) if str(r.get("Ticker", "")).upper() == symbol]
        rows = rows[:50]
        buys = sum(1 for r in rows if str(r.get("Transaction", "")).lower().startswith("purchase"))
        sells = sum(1 for r in rows if str(r.get("Transaction", "")).lower().startswith("sale"))
        return {
            "ok": True,
            "symbol": symbol,
            "n": len(rows),
            "buys": buys,
            "sells": sells,
            "recent": rows,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
