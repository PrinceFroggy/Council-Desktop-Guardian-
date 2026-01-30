import hashlib
import json
from typing import Optional, Dict, Any

CACHE_PREFIX = "cag:"

def _key(parts: Dict[str, Any]) -> str:
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()

def cag_get(redis_client, *, prompt: str, rag_mode: str) -> Optional[dict]:
    k = (CACHE_PREFIX + _key({"prompt": prompt, "rag_mode": rag_mode})).encode()
    val = redis_client.get(k)
    if not val:
        return None
    try:
        return json.loads(val.decode("utf-8"))
    except Exception:
        return None

def cag_set(redis_client, *, prompt: str, rag_mode: str, response_obj: dict, ttl_seconds: int = 7*24*3600) -> None:
    k = (CACHE_PREFIX + _key({"prompt": prompt, "rag_mode": rag_mode})).encode()
    redis_client.setex(k, ttl_seconds, json.dumps(response_obj, ensure_ascii=False).encode("utf-8"))
