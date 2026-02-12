"""Quant autopilot loop.

You requested a pivot to "full quant fund automation" with the Council monitoring.

Behavior:
- Discovers candidate symbols (watchlist, seed text, optional web discovery)
- Gathers signals: fundamentals, trends, reddit buzz, congress trades, ticker news
- Pulls OHLCV, computes indicators + backtest metrics
- Produces a score in [0,1]
- If AUTOPILOT_CAN_EXECUTE=1 and score >= AUTOPILOT_MIN_SCORE, it will place
  Alpaca PAPER or LIVE orders depending on ALPACA_PAPER, using bracket orders
  when ATR is available.
- Always logs a detailed run report to Redis and notifies Telegram.

Safety:
- Long-only
- Position sizing capped by RISK_MAX_POSITION_PCT
- Sector cap is enforced only when sector data is available

You can disable all execution by leaving AUTOPILOT_CAN_EXECUTE=0.
"""

from __future__ import annotations

import json
import time
from typing import Dict, Any, List

from .config import settings
from .notify import telegram_send
from .data_pipeline.ticker_discovery import discover_candidates
from .data_pipeline.fundamentals import fetch_fundamentals
from .signals.google_trends import fetch_trends
from .signals.reddit_sentiment import fetch_buzz
from .signals.congress_trades import fetch_congress_trades
from .signals.news_api import fetch_ticker_news
from .quant.price_data import fetch_ohlcv
from .quant.indicators import compute_snapshot
from .quant.backtester import sma_crossover_backtest
from .risk.engine import assess_long_trade

RUN_KEY = "autopilot:last_run"
HISTORY_KEY = "autopilot:history"


def _score_item(*, indicators: Dict[str, Any], backtest: Dict[str, Any], trends: Dict[str, Any], reddit: Dict[str, Any], congress: Dict[str, Any], fundamentals: Dict[str, Any]) -> float:
    """Combine signals into a normalized score.

    This is deliberately simple and transparent.
    You can replace with an ML model later.
    """
    score = 0.0
    weight = 0.0

    # Trend / momentum
    if trends.get("ok"):
        # momentum can be negative; map to 0..1-ish
        m = float(trends.get("momentum") or 0.0)
        s = max(0.0, min(1.0, (m + 50.0) / 100.0))
        score += 0.10 * s
        weight += 0.10

    # Reddit buzz
    if reddit.get("ok"):
        b = float(reddit.get("buzz_score") or 0.0)
        s = max(0.0, min(1.0, b / 1.5))
        score += 0.10 * s
        weight += 0.10

    # Congress trades: net buy bias
    if congress.get("ok"):
        buys = float(congress.get("buys") or 0)
        sells = float(congress.get("sells") or 0)
        s = 0.5
        if buys + sells > 0:
            s = buys / (buys + sells)
        score += 0.05 * s
        weight += 0.05

    # Indicators: trend + RSI sanity
    rsi = indicators.get("rsi_14")
    if rsi is not None:
        # prefer 40-65 for entries (avoid too hot)
        r = float(rsi)
        s = 1.0 - min(1.0, abs(r - 55.0) / 45.0)
        score += 0.15 * s
        weight += 0.15
    if indicators.get("sma_20") and indicators.get("sma_50"):
        s = 1.0 if float(indicators["sma_20"]) > float(indicators["sma_50"]) else 0.0
        score += 0.15 * s
        weight += 0.15

    # Backtest metrics: Sharpe and drawdown
    try:
        sharpe = float(backtest.get("sharpe") or 0.0)
        mdd = float(backtest.get("mdd") or 0.0)
        s_sh = max(0.0, min(1.0, (sharpe + 0.5) / 2.0))
        s_dd = max(0.0, min(1.0, 1.0 + mdd))  # mdd is negative
        score += 0.25 * (0.6 * s_sh + 0.4 * s_dd)
        weight += 0.25
    except Exception:
        pass

    # Fundamentals: avoid extreme debtEquity if present
    fund = (fundamentals.get("fundamentals") or {}) if fundamentals.get("ok") else {}
    de = fund.get("debtEquity")
    if de is not None:
        try:
            de = float(de)
            s = 1.0 if de <= 1.5 else (0.5 if de <= 3.0 else 0.0)
            score += 0.10 * s
            weight += 0.10
        except Exception:
            pass

    # News presence: if we have articles, small bump
    if isinstance(fundamentals, dict) and fundamentals.get("ok"):
        pass

    if weight <= 0:
        return 0.0
    return float(score / weight)


def run_autopilot_once(r, council=None) -> Dict[str, Any]:
    """Run one cycle. Council object is optional (monitor-only mode)."""
    started = time.time()
    discovery = discover_candidates()
    candidates: List[str] = discovery.get("candidates") or []

    report: Dict[str, Any] = {
        "ts": started,
        "candidates": candidates,
        "results": [],
        "executed": [],
        "settings": {
            "min_score": settings.AUTOPILOT_MIN_SCORE,
            "can_execute": bool(settings.AUTOPILOT_CAN_EXECUTE),
            "broker": settings.TRADING_BROKER,
            "alpaca_paper": bool(settings.ALPACA_PAPER),
        },
        "sources": discovery.get("sources") or {},
    }

    for sym in candidates:
        item: Dict[str, Any] = {"symbol": sym}
        try:
            prices = fetch_ohlcv(sym, lookback_days=settings.BACKTEST_LOOKBACK_DAYS, interval="1d")
            df = prices.df
            indicators = compute_snapshot(df)
            bt = sma_crossover_backtest(df, sym, fast=20, slow=50, rsi_filter=True)
            bt_metrics = bt.metrics

            fundamentals = fetch_fundamentals(sym)
            trends = fetch_trends(sym)
            reddit = fetch_buzz(sym)
            congress = fetch_congress_trades(sym)
            news = fetch_ticker_news(sym)

            last_price = float(df["close"].iloc[-1])
            score = _score_item(
                indicators=indicators,
                backtest=bt_metrics,
                trends=trends,
                reddit=reddit,
                congress=congress,
                fundamentals=fundamentals,
            )

            item.update({
                "last_price": last_price,
                "score": score,
                "indicators": indicators,
                "backtest": bt_metrics,
                "fundamentals": fundamentals,
                "trends": trends,
                "reddit": reddit,
                "congress": congress,
                "news": news,
            })

            # Risk sizing
            equity = float(settings.PAPER_START_CASH)
            rd = assess_long_trade(symbol=sym, last_price=last_price, equity=equity, atr_14=indicators.get("atr_14"))
            item["risk"] = rd.__dict__

            # Decision
            should_buy = rd.ok and score >= float(settings.AUTOPILOT_MIN_SCORE)
            item["decision"] = "BUY" if should_buy else "SKIP"

            # Council monitoring (non-blocking by default)
            if council is not None and should_buy:
                try:
                    proposed_plan = {
                        "type": "trading",
                        "actions": [
                            {
                                "name": "alpaca_order",
                                "broker_mode": "paper" if settings.ALPACA_PAPER else "live",
                                "symbol": sym,
                                "side": "buy",
                                "notional": rd.notional,
                                "order_type": "market",
                                "order_class": "bracket" if (rd.stop_loss_price and rd.take_profit_price) else None,
                                "take_profit_limit_price": rd.take_profit_price,
                                "stop_loss_stop_price": rd.stop_loss_price,
                            }
                        ],
                        "meta": {"score": score, "risk": rd.__dict__, "indicators": indicators, "backtest": bt_metrics},
                    }
                    provider_plan = [
                        ("ollama", "llama3.1:8b"),
                        ("ollama", "qwen2.5-coder:7b"),
                    ]
                    verdict = council.review(
                        action_request=f"Autopilot trade decision for {sym} (monitor-only unless AUTOPILOT_RESPECT_COUNCIL=1).",
                        rag_context=[],
                        proposed_plan=proposed_plan,
                        provider_plan=provider_plan,
                    )
                    item["council_verdict"] = verdict.get("final")
                    if settings.AUTOPILOT_RESPECT_COUNCIL and verdict.get("final", {}).get("verdict") == "NO":
                        item["decision"] = "SKIP"
                        should_buy = False
                except Exception as e:
                    item["council_verdict"] = {"error": str(e)[:200]}

            report["results"].append(item)

            if should_buy and settings.AUTOPILOT_CAN_EXECUTE and settings.TRADING_BROKER.lower() == "alpaca":
                from .brokers.alpaca import place_order

                # Use notional sizing + bracket when available
                oc = "bracket" if (rd.stop_loss_price and rd.take_profit_price) else None
                order = place_order(
                    api_key=settings.ALPACA_API_KEY,
                    api_secret=settings.ALPACA_API_SECRET,
                    paper=bool(settings.ALPACA_PAPER),
                    base_url=(settings.ALPACA_BASE_URL or None),
                    symbol=sym,
                    side="buy",
                    notional=rd.notional,
                    order_type="market",
                    time_in_force="day",
                    order_class=oc,
                    take_profit_limit_price=rd.take_profit_price,
                    stop_loss_stop_price=rd.stop_loss_price,
                )
                report["executed"].append({"symbol": sym, "order": order, "risk": rd.__dict__, "score": score})

        except Exception as e:
            item["error"] = str(e)[:200]
            report["results"].append(item)

        # stop once we hit max trades
        if len(report["executed"]) >= int(settings.AUTOPILOT_MAX_TRADES_PER_RUN):
            break

    report["duration_sec"] = float(time.time() - started)

    # Store to Redis
    try:
        r.set(RUN_KEY, json.dumps(report, ensure_ascii=False).encode("utf-8"))
        r.lpush(HISTORY_KEY, json.dumps({"ts": report["ts"], "executed": report["executed"], "n": len(report["results"])}, ensure_ascii=False).encode("utf-8"))
        r.ltrim(HISTORY_KEY, 0, 200)
    except Exception:
        pass

    # Notify
    try:
        top = sorted([x for x in report["results"] if x.get("score") is not None], key=lambda x: x.get("score") or 0, reverse=True)[:5]
        lines = [f"[Autopilot] candidates={len(candidates)} executed={len(report['executed'])} duration={report['duration_sec']:.1f}s"]
        for t in top:
            lines.append(f"- {t.get('symbol')} score={t.get('score'):.2f} last={t.get('last_price')} decision={t.get('decision')}")
        if report["executed"]:
            lines.append("Executed:")
            for ex in report["executed"]:
                oid = (ex.get("order") or {}).get("id", "")
                lines.append(f"  • {ex.get('symbol')} notional={ex.get('risk',{}).get('notional')} order_id={oid}")
        telegram_send("\n".join(lines))
    except Exception:
        pass

    return report
