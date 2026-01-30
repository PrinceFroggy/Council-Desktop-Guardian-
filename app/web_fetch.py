import os
import re
from urllib.parse import urlparse
import requests
from typing import Dict, Any, List

class WebFetchError(Exception):
    pass

def _enabled() -> bool:
    return os.getenv("ENABLE_WEB_RESEARCH", "0") == "1"

def _allowlist() -> List[str]:
    raw = os.getenv("WEB_ALLOWLIST", "")
    items = [x.strip().lower() for x in raw.split(",") if x.strip()]
    # If empty, default to RSS sources only (safer)
    return items

def fetch_url(url: str, max_chars: int = 200_000) -> Dict[str, Any]:
    if not _enabled():
        raise WebFetchError("Web research disabled. Set ENABLE_WEB_RESEARCH=1.")
    u = url.strip()
    if not u.startswith("http://") and not u.startswith("https://"):
        raise WebFetchError("Only http(s) URLs allowed")
    host = (urlparse(u).hostname or "").lower()
    allow = _allowlist()
    if allow and not any(host == d or host.endswith("." + d) for d in allow):
        raise WebFetchError("Host not in WEB_ALLOWLIST")
    r = requests.get(u, timeout=20, headers={"User-Agent":"CouncilGuardian/1.0"})
    r.raise_for_status()
    text = r.text
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    else:
        truncated = False
    return {"url": u, "status": r.status_code, "truncated": truncated, "content": text}
