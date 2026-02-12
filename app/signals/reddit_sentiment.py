"""Reddit attention/sentiment proxy (best-effort).

This module intentionally avoids heavy NLP.
It produces a "buzz" score using Reddit post metadata.

Optional dependency: praw
Required env vars to enable:
- REDDIT_CLIENT_ID
- REDDIT_CLIENT_SECRET
- REDDIT_USER_AGENT
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from ..config import settings


DEFAULT_SUBS = ["stocks", "investing", "wallstreetbets", "SecurityAnalysis"]


def is_enabled() -> bool:
    return bool(settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET)


def fetch_buzz(
    symbol: str,
    subs: Optional[List[str]] = None,
    limit_per_sub: int = 25,
) -> Dict[str, Any]:
    """Return a simple buzz score.

    Score is in roughly [0, 1+] depending on volume. Use it as a weight, not a probability.
    """
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {"ok": False, "error": "missing symbol"}

    if not is_enabled():
        return {"ok": False, "error": "reddit not configured"}

    try:
        import praw  # type: ignore
    except Exception:
        return {"ok": False, "error": "praw not installed"}

    subs = subs or DEFAULT_SUBS

    reddit = praw.Reddit(
        client_id=settings.REDDIT_CLIENT_ID,
        client_secret=settings.REDDIT_CLIENT_SECRET,
        user_agent=settings.REDDIT_USER_AGENT,
    )

    mentions = 0
    weighted = 0.0
    samples: List[Dict[str, Any]] = []

    for sub in subs:
        try:
            sr = reddit.subreddit(sub)
            for post in sr.hot(limit=int(limit_per_sub)):
                title = (getattr(post, "title", "") or "").upper()
                if symbol not in title:
                    continue
                mentions += 1
                score = float(getattr(post, "score", 0) or 0)
                ratio = float(getattr(post, "upvote_ratio", 0.5) or 0.5)
                # normalize a bit: log-ish squashing via tanh
                import math

                w = math.tanh(score / 500.0) * ratio
                weighted += max(0.0, w)
                if len(samples) < 10:
                    samples.append(
                        {
                            "sub": sub,
                            "title": getattr(post, "title", "")[:160],
                            "score": score,
                            "upvote_ratio": ratio,
                            "url": getattr(post, "url", ""),
                        }
                    )
        except Exception:
            continue

    # convert to a bounded-ish score
    buzz = min(1.5, (mentions / 50.0) + (weighted / 10.0))
    return {
        "ok": True,
        "symbol": symbol,
        "mentions": mentions,
        "buzz_score": float(buzz),
        "samples": samples,
    }
