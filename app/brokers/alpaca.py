
import os
import requests
from typing import Optional, Dict, Any

class AlpacaError(Exception):
    pass

def _base_url(paper: bool, base_url: Optional[str]=None) -> str:
    if base_url:
        return base_url.rstrip("/")
    return ("https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets")

def place_order(
    *,
    api_key: str,
    api_secret: str,
    paper: bool = True,
    base_url: Optional[str] = None,
    symbol: str,
    side: str,
    qty: Optional[float] = None,
    notional: Optional[float] = None,
    order_type: str = "market",
    time_in_force: str = "day",
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    extended_hours: bool = False,
    client_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Places an order via Alpaca Trading API v2 (/v2/orders).
    You must supply either qty or notional.
    """
    if not api_key or not api_secret:
        raise AlpacaError("Missing Alpaca API credentials")
    if not symbol:
        raise AlpacaError("Missing symbol")
    if (qty is None and notional is None) or (qty is not None and notional is not None):
        raise AlpacaError("Provide exactly one of qty or notional")

    side = side.lower()
    if side not in ("buy", "sell"):
        raise AlpacaError("side must be buy or sell")
    order_type = order_type.lower()
    if order_type not in ("market", "limit", "stop", "stop_limit"):
        raise AlpacaError("Unsupported order_type")
    time_in_force = time_in_force.lower()

    payload: Dict[str, Any] = {
        "symbol": symbol.upper(),
        "side": side,
        "type": order_type,
        "time_in_force": time_in_force,
        "extended_hours": bool(extended_hours),
    }
    if client_order_id:
        payload["client_order_id"] = client_order_id

    if qty is not None:
        payload["qty"] = str(qty)
    if notional is not None:
        payload["notional"] = str(notional)

    if order_type in ("limit", "stop_limit"):
        if limit_price is None:
            raise AlpacaError("limit_price required for limit/stop_limit")
        payload["limit_price"] = str(limit_price)
    if order_type in ("stop", "stop_limit"):
        if stop_price is None:
            raise AlpacaError("stop_price required for stop/stop_limit")
        payload["stop_price"] = str(stop_price)

    url = _base_url(paper, base_url) + "/v2/orders"
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
        "Content-Type": "application/json",
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    if resp.status_code >= 400:
        raise AlpacaError(f"Alpaca order error ({resp.status_code}): {resp.text[:500]}")
    return resp.json()
