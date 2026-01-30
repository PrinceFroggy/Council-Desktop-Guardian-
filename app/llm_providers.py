import os
import requests

class LLMProvider:
    def chat(self, system: str, user: str, model: str) -> str:
        raise NotImplementedError

class OllamaProvider(LLMProvider):
    def __init__(self, host: str):
        self.host = host.rstrip("/")

    def chat(self, system: str, user: str, model: str) -> str:
        url = f"{self.host}/api/chat"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        r = requests.post(url, json=payload, timeout=180)
        r.raise_for_status()
        return r.json()["message"]["content"]

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
