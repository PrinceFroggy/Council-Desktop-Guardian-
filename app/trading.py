import json
import time
from typing import Dict, Any, List, Optional

PORTFOLIO_KEY = "paper:portfolio:v1"
TRADES_KEY = "paper:trades:v1"

def _loads(b: Optional[bytes], default):
    if not b:
        return default
    try:
        if isinstance(b, (bytes, bytearray)):
            b = b.decode("utf-8", errors="ignore")
        return json.loads(b)
    except Exception:
        return default

def get_portfolio(r, start_cash: float = 100000.0) -> Dict[str, Any]:
    data = _loads(r.get(PORTFOLIO_KEY), None)
    if not data:
        data = {"cash": float(start_cash), "positions": {}, "updated_at": int(time.time())}
        r.set(PORTFOLIO_KEY, json.dumps(data).encode("utf-8"))
    return data

def get_trades(r) -> List[Dict[str, Any]]:
    return _loads(r.get(TRADES_KEY), [])

def _save(r, portfolio: Dict[str, Any], trades: List[Dict[str, Any]]):
    portfolio["updated_at"] = int(time.time())
    r.set(PORTFOLIO_KEY, json.dumps(portfolio).encode("utf-8"))
    r.set(TRADES_KEY, json.dumps(trades).encode("utf-8"))

def apply_paper_trade(r, ticker: str, side: str, qty: float, price: float, start_cash: float = 100000.0) -> Dict[str, Any]:
    """
    Very simple paper broker:
      - Market orders only
      - No fees/slippage
      - Supports BUY/SELL
    """
    ticker = (ticker or "").strip().upper()
    side = (side or "").strip().upper()
    qty = float(qty)
    price = float(price)

    if not ticker or side not in ("BUY", "SELL") or qty <= 0 or price <= 0:
        return {"ok": False, "error": "Invalid trade parameters."}

    portfolio = get_portfolio(r, start_cash=start_cash)
    trades = get_trades(r)

    positions = portfolio.get("positions", {})
    pos = positions.get(ticker, {"qty": 0.0, "avg_price": 0.0})

    if side == "BUY":
        cost = qty * price
        if portfolio["cash"] < cost:
            return {"ok": False, "error": f"Insufficient cash for BUY. Need {cost:.2f}, have {portfolio['cash']:.2f}."}
        # update avg price
        new_qty = pos["qty"] + qty
        if new_qty <= 0:
            new_avg = 0.0
        else:
            new_avg = ((pos["qty"] * pos["avg_price"]) + cost) / new_qty
        pos["qty"] = new_qty
        pos["avg_price"] = new_avg
        portfolio["cash"] -= cost

    if side == "SELL":
        if pos["qty"] < qty:
            return {"ok": False, "error": f"Insufficient shares for SELL. Have {pos['qty']}, tried to sell {qty}."}
        proceeds = qty * price
        pos["qty"] -= qty
        portfolio["cash"] += proceeds
        if pos["qty"] <= 0:
            pos = {"qty": 0.0, "avg_price": 0.0}

    if pos["qty"] > 0:
        positions[ticker] = pos
    else:
        positions.pop(ticker, None)

    portfolio["positions"] = positions

    trade = {
        "ts": int(time.time()),
        "ticker": ticker,
        "side": side,
        "qty": qty,
        "price": price,
    }
    trades.append(trade)
    _save(r, portfolio, trades)

    return {"ok": True, "portfolio": portfolio, "trade": trade}

def portfolio_summary(r, start_cash: float = 100000.0) -> Dict[str, Any]:
    p = get_portfolio(r, start_cash=start_cash)
    return {"cash": p.get("cash", 0.0), "positions": p.get("positions", {}), "updated_at": p.get("updated_at")}
