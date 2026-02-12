import os
import requests

def _normalize_ollama_host(host: str) -> str:
    host = (host or "http://localhost:11434").strip().rstrip("/")
    # If someone put /api in the env var, strip it so we don't end up with /api/api/chat
    if host.endswith("/api"):
        host = host[:-4]
    return host

class LLMProvider:
    def chat(self, system: str, user: str, model: str) -> str:
        raise NotImplementedError

class OllamaProvider:
    def __init__(self, host: str):
        self.host = _normalize_ollama_host(host)

    def chat(self, system: str, user: str, model: str):
        url = f"{self.host}/api/chat"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }

        # TEMP debug: print the exact URL once so you can confirm
        # (you can delete this after it works)
        print(f"[ollama] POST {url}")

        r = requests.post(url, json=payload, timeout=180)
        r.raise_for_status()
        data = r.json()
        msg = (data.get("message") or {}).get("content")
        return msg or ""


class OpenRouterProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def chat(self, system: str, user: str, model: str) -> str:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        r = requests.post(url, headers=headers, json=payload, timeout=180)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

class GroqProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def chat(self, system: str, user: str, model: str) -> str:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": 0.2}
        r = requests.post(url, headers=headers, json=payload, timeout=180)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

def build_providers(ollama_host: str):
    providers = {"ollama": OllamaProvider(ollama_host)}
    if os.getenv("OPENROUTER_API_KEY"):
        providers["openrouter"] = OpenRouterProvider(os.getenv("OPENROUTER_API_KEY"))
    if os.getenv("GROQ_API_KEY"):
        providers["groq"] = GroqProvider(os.getenv("GROQ_API_KEY"))
    return providers
