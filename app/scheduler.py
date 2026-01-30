import os
import time
import threading
import datetime
import hashlib
import re
import feedparser

from .config import settings
from .prompts import DAILY_RESEARCH_SYSTEM, NEWS_SIGNAL_SYSTEM
from .notify import telegram_send
from .engine import submit_request

_TICKER_RE = re.compile(r"(?:\$|\b)([A-Z]{1,5})(?:\b)")

def load_sources() -> list[str]:
    """Daily briefing RSS sources."""
    here = os.path.dirname(__file__)
    p = os.path.join(here, "research_sources.txt")
    lines = []
    try:
        lines = open(p, "r", encoding="utf-8").read().splitlines()
    except Exception:
        return []
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        out.append(ln)
    return out

def load_news_sources() -> list[str]:
    """High-frequency news poller RSS sources."""
    p = settings.NEWS_SOURCES_FILE
    # allow relative paths
    if not os.path.isabs(p):
        base = os.path.dirname(__file__)
        p = os.path.join(base, os.path.basename(p)) if p.startswith("app/") else os.path.join(base, p)
    try:
        lines = open(p, "r", encoding="utf-8").read().splitlines()
    except Exception:
        return []
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        out.append(ln)
    return out

def _extract_tickers(text: str) -> list[str]:
    if not text:
        return []
    cands = _TICKER_RE.findall(text.upper())
    # filter obvious noise tokens
    bad = {"THE","AND","FOR","WITH","THIS","THAT","FROM","WILL","ARE","YOU","NOW","NEW","USA","CAN","USD","CEO","CFO","IPO","ETF","FED"}
    out = []
    for t in cands:
        if t in bad:
            continue
        if 1 <= len(t) <= 5:
            out.append(t)
    # de-dup keep order
    seen=set()
    uniq=[]
    for t in out:
        if t not in seen:
            seen.add(t); uniq.append(t)
    return uniq[:10]

def _in_market_hours(dt: datetime.datetime) -> bool:
    # Basic US market hours heuristic, local time.
    # If you want precision by exchange/timezone, disable NEWS_ENABLE_MARKET_HOURS_ONLY.
    start = dt.replace(hour=9, minute=30, second=0, microsecond=0)
    end = dt.replace(hour=16, minute=0, second=0, microsecond=0)
    if dt.weekday() >= 5:
        return False
    return start <= dt <= end

def run_daily_briefing(llm_provider, model_name: str):
    sources = load_sources()
    items = []
    for url in sources:
        feed = feedparser.parse(url)
        for e in feed.entries[:6]:
            title = getattr(e, "title", "")
            link = getattr(e, "link", "")
            summary = getattr(e, "summary", "")[:600]
            items.append(f"- {title}\n  {link}\n  {summary}")
    prompt = "Summarize today's key developments from these feeds:\n\n" + "\n\n".join(items)

    text = llm_provider.chat(DAILY_RESEARCH_SYSTEM, prompt, model_name)
    telegram_send(text)

def _news_to_proposed_plan(provider, model_name: str, article: dict) -> dict:
    title = article.get("title","")
    link = article.get("link","")
    summary = (article.get("summary","") or "")[:1200]
    raw = f"TITLE: {title}\nURL: {link}\nSUMMARY: {summary}"
    analysis = provider.chat(NEWS_SIGNAL_SYSTEM, raw, model_name)

    # best-effort parse
    sig = None
    try:
        import json
        sig = json.loads(analysis)
    except Exception:
        sig = None

    tickers = sig.get("tickers") if isinstance(sig, dict) else None
    if not tickers:
        tickers = _extract_tickers(title + " " + summary)

    # Optional watchlist filter
    wl = [t.strip().upper() for t in (settings.NEWS_WATCHLIST or "").split(",") if t.strip()]
    if wl:
        tickers = [t for t in tickers if t in wl]

    no_trade = True
    trade = None
    rationale = ""
    risks = []
    if isinstance(sig, dict):
        no_trade = bool(sig.get("no_trade", True))
        trade = sig.get("trade")
        rationale = sig.get("rationale","")
        risks = sig.get("risks") or []
    # Force paper-only constraints
    if trade and isinstance(trade, dict):
        trade["ticker"] = (trade.get("ticker") or (tickers[0] if tickers else "")).upper()
        trade["side"] = (trade.get("side") or "BUY").upper()
        trade["qty"] = float(trade.get("qty") or 1)
        trade["price_hint"] = trade.get("price_hint") or "use next quote"
        no_trade = False

    actions = [
        {"name": "notify", "channel": "telegram", "message": f"News signal (dry-run)\nTickers: {', '.join(tickers) if tickers else '(none)'}\n{title}\n{link}"}
    ]

    if not no_trade and trade and trade.get("ticker"):
        # Always include a paper trade proposal (safe).
        actions.append({
            "name": "paper_trade",
            "ticker": trade["ticker"],
            "side": trade["side"],
            "qty": trade["qty"],
            "price": 1.0,  # placeholder; requires you to confirm a real quote before execution
            "requires_quote": True,
            "note": "Paper trade proposal. You must fill/confirm a real quote price before approving."
        })

        # If Alpaca broker is configured, also include an Alpaca paper-order proposal.
        # Live orders are PROPOSED only (never auto-confirmed) and still require the standard YES approval plus confirm_live_trade=true.
        if settings.TRADING_BROKER.lower() == "alpaca":
            actions.append({
                "name": "alpaca_order",
                "broker_mode": "paper",
                "symbol": trade["ticker"],
                "side": trade["side"].lower(),
                "qty": trade["qty"],
                "order_type": "market",
                "time_in_force": "day",
                "note": "Alpaca PAPER order proposal (requires your YES approval to execute)."
            })

            if getattr(settings, "NEWS_PROPOSE_LIVE", 0):
                actions.append({
                    "name": "alpaca_order",
                    "broker_mode": "live",
                    "symbol": trade["ticker"],
                    "side": trade["side"].lower(),
                    "qty": trade["qty"],
                    "order_type": "market",
                    "time_in_force": "day",
                    "confirm_live_trade": False,
                    "note": "LIVE order proposal only. To execute you must explicitly set confirm_live_trade=true when approving."
                })
    return {
        "type": "trading",
        "dry_run": True,
        "actions": actions,
        "meta": {"tickers": tickers, "rationale": rationale, "risks": risks, "source_url": link}
    }

def start_scheduler(rag, r, providers, council):
    """
    Starts:
      1) 9am daily RSS briefing (existing)
      2) High-frequency news poller that proposes paper-trade ideas (NEW)
    """

    def daily_loop():
        while True:
            now = datetime.datetime.now()
            target = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if target <= now:
                target = target + datetime.timedelta(days=1)
            time.sleep(max(5, (target - now).total_seconds()))
            run_daily_briefing(providers["ollama"], "llama3.1:8b")

    def news_loop():
        sources = load_news_sources()
        if not sources:
            return
        while True:
            try:
                now = datetime.datetime.now()
                if settings.NEWS_ENABLE_MARKET_HOURS_ONLY and not _in_market_hours(now):
                    time.sleep(max(30, settings.NEWS_POLL_INTERVAL_SECONDS))
                    continue

                for url in sources:
                    feed = feedparser.parse(url)
                    for e in feed.entries[: settings.NEWS_MAX_ITEMS_PER_POLL]:
                        title = getattr(e, "title", "")
                        link = getattr(e, "link", "")
                        summary = getattr(e, "summary", "") or getattr(e, "description", "")
                        key = hashlib.sha1((link or title).encode("utf-8", errors="ignore")).hexdigest()[:16]
                        seen_key = f"news:seen:{key}"
                        if r.get(seen_key):
                            continue
                        r.setex(seen_key, 60*60*24*7, b"1")  # 7 days

                        article = {"title": title, "link": link, "summary": summary}

                        # index into RAG for later Q&A
                        try:
                            content = f"[NEWS]\nTITLE: {title}\nURL: {link}\nSUMMARY: {summary}"
                            rag.upsert_doc(f"doc:news:{key}", f"news:{key}", "news", content)
                        except Exception:
                            pass

                        proposed_plan = _news_to_proposed_plan(providers["ollama"], "llama3.1:8b", article)
                        if not proposed_plan.get("actions"):
                            continue

                        action_request = f"React to news: {title}\n{link}\n\nProvide a cautious investing response. Paper trading only."
                        submit_request(
                            rag=rag, r=r, providers=providers, council=council,
                            action_request=action_request,
                            proposed_plan=proposed_plan,
                            rag_mode="advanced"
                        )

                time.sleep(max(30, settings.NEWS_POLL_INTERVAL_SECONDS))
            except Exception as ex:
                try:
                    telegram_send(f"[NewsPoller] error: {ex}")
                except Exception:
                    pass
                time.sleep(max(60, settings.NEWS_POLL_INTERVAL_SECONDS))

    threading.Thread(target=daily_loop, daemon=True).start()
    threading.Thread(target=news_loop, daemon=True).start()
