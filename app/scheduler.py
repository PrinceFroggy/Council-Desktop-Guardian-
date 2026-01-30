import os
import time
import threading
import datetime
import feedparser

from .prompts import DAILY_RESEARCH_SYSTEM
from .notify import telegram_send

def load_sources() -> list[str]:
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
        if ln and not ln.startswith("#"):
            out.append(ln)
    return out

def fetch_rss_items(max_items: int = 8) -> list[dict]:
    sources = load_sources()
    items = []
    for url in sources:
        try:
            d = feedparser.parse(url)
            for e in getattr(d, "entries", [])[:3]:
                items.append({"source": url, "title": getattr(e, "title", ""), "link": getattr(e, "link", "")})
        except Exception:
            continue
    return items[:max_items]

def run_daily_briefing(llm_provider, model_name: str):
    items = fetch_rss_items()
    if not items:
        telegram_send("Daily briefing: no RSS items fetched.")
        return
    lines = [f"- {it['title']} ({it['link']})" for it in items]
    prompt = "Today's items:\n" + "\n".join(lines) + "\n\nSummarize and reflect briefly."
    try:
        text = llm_provider.chat(DAILY_RESEARCH_SYSTEM, prompt, model_name)
    except Exception as e:
        text = "Daily briefing error: " + str(e)
    telegram_send(text)

def start_scheduler(llm_provider, model_name: str):
    def loop():
        while True:
            now = datetime.datetime.now()
            target = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if target <= now:
                target = target + datetime.timedelta(days=1)
            time.sleep(max(5, (target - now).total_seconds()))
            run_daily_briefing(llm_provider, model_name)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
