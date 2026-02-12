"""Simple strategy backtesting.

This is not meant to be a full-blown research platform.
It provides enough signal to:
- sanity check a rule-based entry/exit
- compute basic metrics (CAGR, max drawdown, Sharpe)
- generate an equity curve for dashboards

We default to a simple trend strategy (SMA crossover) with optional RSI filter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .indicators import sma, rsi


def _require():
    try:
        import pandas as pd  # noqa
        import numpy as np  # noqa
    except Exception as e:
        raise RuntimeError("pandas and numpy are required for backtesting") from e


def _max_drawdown(equity: Any) -> float:
    _require()
    import numpy as np

    peak = equity.cummax()
    dd = (equity / peak) - 1.0
    mdd = float(dd.min())
    return mdd


def _sharpe(daily_returns: Any, risk_free_rate: float = 0.0) -> float:
    _require()
    import numpy as np

    r = daily_returns.dropna()
    if len(r) < 2:
        return 0.0
    excess = r - (risk_free_rate / 252.0)
    std = float(excess.std())
    if std == 0:
        return 0.0
    return float((excess.mean() / std) * (252 ** 0.5))


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    metrics: Dict[str, float]
    equity_curve: Any  # pandas.Series


def sma_crossover_backtest(price_df: Any, symbol: str, fast: int = 20, slow: int = 50, rsi_filter: bool = False) -> BacktestResult:
    """Long-only SMA crossover.

    Entry: fast SMA crosses above slow SMA.
    Exit: fast SMA crosses below slow SMA.

    If rsi_filter=True, we avoid entering when RSI>70 and avoid exiting when RSI<30.
    """
    _require()
    import pandas as pd

    df = price_df.copy()
    df = df.dropna()
    if len(df) < max(fast, slow) + 5:
        equity = pd.Series([1.0] * len(df), index=df.index)
        return BacktestResult(symbol=symbol, strategy="sma_crossover", metrics={"cagr": 0.0, "mdd": 0.0, "sharpe": 0.0, "trades": 0.0}, equity_curve=equity)

    df["fast"] = sma(df["close"], fast)
    df["slow"] = sma(df["close"], slow)
    df["rsi"] = rsi(df["close"], 14)

    df["signal"] = 0
    df.loc[df["fast"] > df["slow"], "signal"] = 1

    # trade when signal changes
    df["position"] = df["signal"].shift(1).fillna(0)

    if rsi_filter:
        # crude filters
        df.loc[(df["position"] == 0) & (df["signal"] == 1) & (df["rsi"] > 70), "position"] = 0
        df.loc[(df["position"] == 1) & (df["signal"] == 0) & (df["rsi"] < 30), "position"] = 1

    df["ret"] = df["close"].pct_change().fillna(0)
    df["strategy_ret"] = df["position"] * df["ret"]
    df["equity"] = (1.0 + df["strategy_ret"]).cumprod()

    equity = df["equity"]
    daily = df["strategy_ret"]

    # Metrics
    days = max(1, (equity.index[-1] - equity.index[0]).days)
    cagr = float(equity.iloc[-1] ** (365.0 / days) - 1.0) if days > 0 else 0.0
    mdd = _max_drawdown(equity)
    sharpe = _sharpe(daily)

    # trade count proxy
    trades = float((df["position"].diff().abs() > 0).sum() / 2)

    return BacktestResult(
        symbol=symbol,
        strategy=f"sma{fast}_{slow}{'_rsi' if rsi_filter else ''}",
        metrics={"cagr": cagr, "mdd": mdd, "sharpe": sharpe, "trades": trades},
        equity_curve=equity,
    )
