import os
import time
import requests

from .config import settings
from .redis_store import get_redis

_OUTBOUND_PAUSE_KEY = "outbound_pause_until"

def _pause_active() -> bool:
    try:
        r = get_redis(settings.REDIS_URL)
        raw = r.get(_OUTBOUND_PAUSE_KEY.encode())
        if not raw:
            return False
        until = float(raw.decode())
        return time.time() < until
    except Exception:
        return False

def telegram_send(text: str) -> None:
    """
    Send a Telegram message.

    Priority behavior:
    - If the tray has recently sent a prompt, the server sets a short Redis pause window.
      During that window, background messages are suppressed to ensure tray messages arrive
      immediately and aren't buried.
    - Tray messages are identified by the caller prefix "[tray]" / "[tray_app]" etc.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return

    if _pause_active():
        low = (text or "").lower()
        # allow tray-priority messages through
        if not (low.startswith("[tray]") or low.startswith("[tray_app]") or low.startswith("[council_tray]") or low.startswith("[trayapp]") or low.startswith("[news]")):
            return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=20)
