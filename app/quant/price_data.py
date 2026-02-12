"""Market data helpers.

These are intentionally defensive:
- If optional dependencies (pandas/yfinance) aren't installed, functions return a clear error.
- If API keys aren't configured, Alpaca fallback returns a clear error.

The rest of the system should treat these as *best effort* and degrade gracefully.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any

from ..config import settings


@dataclass
class PriceSeries:
    symbol: str
    # pandas.DataFrame with columns: open, high, low, close, volume and datetime index
    df: Any
    provider: str


def _require_pandas():
    try:
        import pandas as pd  # noqa: F401
    except Exception as e:
        raise RuntimeError("pandas is required for price data. Add pandas to requirements.") from e


def fetch_ohlcv(symbol: str, lookback_days: int = 365, interval: str = "1d") -> PriceSeries:
    provider = (settings.PRICE_DATA_PROVIDER or "yfinance").lower()
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")

    if provider == "yfinance":
        _require_pandas()
        try:
            import yfinance as yf
            import pandas as pd
        except Exception as e:
            raise RuntimeError("yfinance + pandas are required for PRICE_DATA_PROVIDER=yfinance") from e

        period = f"{int(max(1, lookback_days))}d"
        data = yf.download(symbol, period=period, interval=interval, auto_adjust=False, progress=False)
        if data is None or len(data) == 0:
            raise RuntimeError(f"No price data returned for {symbol} via yfinance")

        # Normalize columns
        cols = {c.lower(): c for c in data.columns}
        def _col(name: str):
            for k, v in cols.items():
                if k == name:
                    return v
            return None

        df = pd.DataFrame(index=data.index)
        df["open"] = data[_col("open")]
        df["high"] = data[_col("high")]
        df["low"] = data[_col("low")]
        df["close"] = data[_col("close")]
        vol_col = _col("volume")
        df["volume"] = data[vol_col] if vol_col else 0
        df = df.dropna()
        return PriceSeries(symbol=symbol, df=df, provider="yfinance")

    if provider == "alpaca":
        # Fetch bars from Alpaca Data API v2 (requires separate base URL). We'll use a simple best-effort.
        from datetime import datetime, timedelta, timezone
        import requests

        if not settings.ALPACA_API_KEY or not settings.ALPACA_API_SECRET:
            raise RuntimeError("Missing Alpaca credentials for PRICE_DATA_PROVIDER=alpaca")

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=int(max(1, lookback_days)))

        # Alpaca data endpoint (can be overridden via ALPACA_DATA_BASE_URL)
        data_base = (getattr(settings, "ALPACA_DATA_BASE_URL", "") or "https://data.alpaca.markets").rstrip("/")
        url = f"{data_base}/v2/stocks/{symbol}/bars"
        params = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timeframe": "1Day" if interval == "1d" else "1Hour",
            "limit": 10000,
        }
        headers = {
            "APCA-API-KEY-ID": settings.ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": settings.ALPACA_API_SECRET,
        }
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        if resp.status_code >= 400:
            raise RuntimeError(f"Alpaca data error ({resp.status_code}): {resp.text[:200]}")
        payload = resp.json()
        bars = payload.get("bars") or []
        if not bars:
            raise RuntimeError(f"No bars returned for {symbol} via Alpaca")

        _require_pandas()
        import pandas as pd
        idx = [pd.to_datetime(b["t"]) for b in bars]
        df = pd.DataFrame({
            "open": [b["o"] for b in bars],
            "high": [b["h"] for b in bars],
            "low": [b["l"] for b in bars],
            "close": [b["c"] for b in bars],
            "volume": [b.get("v", 0) for b in bars],
        }, index=idx)
        df = df.sort_index().dropna()
        return PriceSeries(symbol=symbol, df=df, provider="alpaca")

    raise RuntimeError(f"Unsupported PRICE_DATA_PROVIDER: {provider}")
