"""Risk management helpers.

This layer is broker-agnostic. It takes:
- account equity (or paper cash)
- current positions
- indicator snapshot (ATR)

And returns:
- suggested position size (qty or notional)
- bracket order params (stop loss / take profit)
- exposure diagnostics
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple

from ..config import settings


@dataclass
class RiskDecision:
    ok: bool
    reason: str
    symbol: str
    notional: float
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    meta: Optional[Dict[str, Any]] = None


def cap_notional(equity: float, proposed_notional: float) -> float:
    cap = float(equity) * float(settings.RISK_MAX_POSITION_PCT)
    return float(min(max(0.0, proposed_notional), cap))


def compute_bracket_from_atr(*, last_price: float, atr_14: Optional[float], stop_atr: Optional[float] = None, rr: Optional[float] = None) -> Tuple[Optional[float], Optional[float]]:
    if last_price <= 0:
        return None, None
    if not atr_14 or atr_14 <= 0:
        return None, None
    stop_mult = float(stop_atr or settings.RISK_DEFAULT_STOP_ATR)
    rr_mult = float(rr or settings.RISK_DEFAULT_TAKEPROFIT_RR)
    stop = last_price - (atr_14 * stop_mult)
    tp = last_price + ((last_price - stop) * rr_mult)
    if stop <= 0:
        stop = None
    if tp <= 0:
        tp = None
    return stop, tp


def assess_long_trade(
    *,
    symbol: str,
    last_price: float,
    equity: float,
    sector_exposure_pct: float = 0.0,
    atr_14: Optional[float] = None,
    desired_notional: Optional[float] = None,
) -> RiskDecision:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return RiskDecision(False, "Missing symbol", symbol, 0.0)
    if last_price <= 0:
        return RiskDecision(False, "Invalid last_price", symbol, 0.0)

    if sector_exposure_pct > settings.RISK_MAX_SECTOR_PCT:
        return RiskDecision(False, f"Sector exposure cap exceeded ({sector_exposure_pct:.2f} > {settings.RISK_MAX_SECTOR_PCT:.2f})", symbol, 0.0)

    if desired_notional is None:
        # default: 5% equity before caps
        desired_notional = float(equity) * 0.05

    notional = cap_notional(equity, float(desired_notional))
    if notional <= 0:
        return RiskDecision(False, "Notional capped to 0", symbol, 0.0)

    stop, tp = compute_bracket_from_atr(last_price=last_price, atr_14=atr_14)

    return RiskDecision(True, "OK", symbol, notional, stop_loss_price=stop, take_profit_price=tp, meta={
        "equity": float(equity),
        "sector_exposure_pct": float(sector_exposure_pct),
        "atr_14": atr_14,
        "max_position_pct": float(settings.RISK_MAX_POSITION_PCT),
    })
