"""Technical indicators (SMA/EMA/RSI/MACD/ATR).

Design goals:
- Minimal dependencies (pandas + numpy).
- Deterministic numeric outputs.
- Safe defaults: if insufficient history, we return None values.

Input dataframe must have columns: open, high, low, close, volume.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


def _require_pandas_numpy():
    try:
        import pandas as pd  # noqa: F401
        import numpy as np  # noqa: F401
    except Exception as e:
        raise RuntimeError("pandas and numpy are required for indicators") from e


def sma(series: Any, window: int) -> Any:
    _require_pandas_numpy()
    return series.rolling(int(window)).mean()


def ema(series: Any, window: int) -> Any:
    _require_pandas_numpy()
    return series.ewm(span=int(window), adjust=False).mean()


def rsi(close: Any, window: int = 14) -> Any:
    _require_pandas_numpy()
    import numpy as np

    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / float(window), adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / float(window), adjust=False).mean()

    rs = avg_gain / (avg_loss.replace(0, np.nan))
    out = 100 - (100 / (1 + rs))
    return out


def macd(close: Any, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, Any]:
    _require_pandas_numpy()
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return {"macd": macd_line, "signal": signal_line, "hist": hist}


def atr(df: Any, window: int = 14) -> Any:
    _require_pandas_numpy()
    import pandas as pd

    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    return tr.ewm(alpha=1 / float(window), adjust=False).mean()


@dataclass
class IndicatorSnapshot:
    sma_20: Optional[float]
    sma_50: Optional[float]
    ema_20: Optional[float]
    rsi_14: Optional[float]
    macd_hist: Optional[float]
    atr_14: Optional[float]


def compute_snapshot(price_df: Any) -> Dict[str, Optional[float]]:
    """Compute a compact indicator snapshot for the latest bar."""
    _require_pandas_numpy()

    close = price_df["close"]
    s20 = sma(close, 20)
    s50 = sma(close, 50)
    e20 = ema(close, 20)
    r14 = rsi(close, 14)
    m = macd(close)
    a14 = atr(price_df, 14)

    def _last(x):
        try:
            v = x.iloc[-1]
            if v != v:  # NaN
                return None
            return float(v)
        except Exception:
            return None

    snap = {
        "sma_20": _last(s20),
        "sma_50": _last(s50),
        "ema_20": _last(e20),
        "rsi_14": _last(r14),
        "macd_hist": _last(m["hist"]),
        "atr_14": _last(a14),
    }
    return snap
