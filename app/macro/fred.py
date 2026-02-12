"""Macro indicators from FRED (best-effort).

We use FRED's official API (requires FRED_API_KEY).

Common series:
- CPIAUCSL (CPI)
- UNRATE (unemployment)
- GDP
- DGS10 (10y)
- DGS2 (2y)

Docs: https://fred.stlouisfed.org/docs/api/fred/
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

import requests

from ..config import settings


def fetch_series(series_id: str, limit: int = 30) -> Dict[str, Any]:
    series_id = (series_id or "").strip().upper()
    if not series_id:
        return {"ok": False, "error": "missing series_id"}
    if not settings.FRED_API_KEY:
        return {"ok": False, "error": "FRED_API_KEY not set"}

    try:
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": settings.FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": int(limit),
        }
        resp = requests.get(url, params=params, timeout=20)
        if resp.status_code >= 400:
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        obs = data.get("observations") or []
        values = []
        for o in obs:
            v = o.get("value")
            try:
                fv = float(v)
            except Exception:
                continue
            values.append({"date": o.get("date"), "value": fv})
        values = list(reversed(values))
        return {"ok": True, "series_id": series_id, "values": values}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def fetch_macro_snapshot() -> Dict[str, Any]:
    """A small curated macro snapshot for dashboard + prompt context."""
    series = {
        "CPI": "CPIAUCSL",
        "UNRATE": "UNRATE",
        "GDP": "GDP",
        "DGS10": "DGS10",
        "DGS2": "DGS2",
        "VIX": "VIXCLS",
    }
    out: Dict[str, Any] = {"ok": True, "series": {}}
    for name, sid in series.items():
        res = fetch_series(sid, limit=24)
        out["series"][name] = res
    return out
