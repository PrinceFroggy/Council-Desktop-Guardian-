import os
import requests

def _normalize_ollama_host(host: str) -> str:
    host = (host or "http://localhost:11434").strip().rstrip("/")
    if host.endswith("/api"):
        host = host[:-4]
    return host

class OllamaProvider:
    def __init__(self, host: str | None = None):
        self.host = _normalize_ollama_host(host or os.getenv("OLLAMA_HOST", "http://localhost:11434"))

    def chat(self, system: str, user: str, model: str):
        """
        Uses Ollama /api/chat with the same schema as:
          curl -X POST http://localhost:11434/api/chat -d '{...}'
        """
        url = f"{self.host}/api/chat"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }

        # debug (keep for now)
        print(f"[ollama] POST {url}")

        r = requests.post(url, json=payload, timeout=180)
        # If it fails, print body to see why (super important)
        if r.status_code >= 400:
            print("[ollama] status:", r.status_code)
            print("[ollama] body:", r.text[:500])
        r.raise_for_status()

        data = r.json()
        # Ollama returns {"message":{"content":...}} for chat
        msg = (data.get("message") or {}).get("content")
        return msg or ""

def load_providers():
    """
    Keep the interface your app expects: a dict of providers.
    """
    return {
        "ollama": OllamaProvider(),
    }
