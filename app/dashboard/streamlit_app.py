"""Streamlit dashboard for Council Trading Autopilot.

Run:
  streamlit run app/dashboard/streamlit_app.py

Reads Redis keys:
- autopilot:last_run
- autopilot:history
- paper:portfolio:v1
- paper:trades:v1
"""

from __future__ import annotations

import json

import streamlit as st

from ..config import settings
from ..redis_store import get_redis
from ..trading import PORTFOLIO_KEY, TRADES_KEY


def _loads(b, default):
    if not b:
        return default
    try:
        if isinstance(b, (bytes, bytearray)):
            b = b.decode("utf-8", errors="ignore")
        return json.loads(b)
    except Exception:
        return default


def main():
    st.set_page_config(page_title="Council Autopilot", layout="wide")
    st.title("Council Desktop Guardian — Quant Autopilot")

    r = get_redis(settings.REDIS_URL)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Paper Portfolio")
        portfolio = _loads(r.get(PORTFOLIO_KEY), {})
        st.json(portfolio)

    with col2:
        st.subheader("Paper Trades")
        trades = _loads(r.get(TRADES_KEY), [])
        st.write(f"Trades: {len(trades)}")
        st.json(trades[-20:])

    st.divider()
    st.subheader("Autopilot")
    last_run = _loads(r.get(b"autopilot:last_run"), None)
    if not last_run:
        st.info("No autopilot run found yet. Enable AUTOPILOT_ENABLED=1 and restart the app.")
    else:
        st.write(f"Last run: {last_run.get('ts')} | duration: {last_run.get('duration_sec'):.1f}s")
        st.write(f"Executed: {len(last_run.get('executed') or [])}")
        st.json(last_run.get("executed") or [])

        st.write("Top candidates")
        results = last_run.get("results") or []
        results = sorted(results, key=lambda x: x.get("score") or 0, reverse=True)
        st.dataframe([
            {
                "symbol": x.get("symbol"),
                "score": x.get("score"),
                "last_price": x.get("last_price"),
                "decision": x.get("decision"),
                "rsi_14": (x.get("indicators") or {}).get("rsi_14"),
                "sharpe": (x.get("backtest") or {}).get("sharpe"),
                "mdd": (x.get("backtest") or {}).get("mdd"),
            }
            for x in results[:25]
        ])

    st.subheader("History (last 200)")
    hist = [_loads(x, {}) for x in (r.lrange(b"autopilot:history", 0, 200) or [])]
    st.dataframe(hist)


if __name__ == "__main__":
    main()
