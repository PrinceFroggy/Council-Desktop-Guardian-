import re
from typing import List

INJECTION_PATTERNS: List[str] = [
    r"ignore (all )?(previous|prior) instructions",
    r"system prompt",
    r"developer message",
    r"reveal.*(secret|key|token|password)",
    r"exfiltrate",
    r"jailbreak",
    r"do anything now",
    r"override",
]

def looks_like_prompt_injection(text: str) -> bool:
    t = (text or "").lower()
    return any(re.search(p, t) for p in INJECTION_PATTERNS)

def scrub_secrets(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"(?i)(api[_-]?key\s*[:=]\s*)(\S+)", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(bearer\s+)(\S+)", r"\1[REDACTED]", text)
    return text
