from typing import Any, Dict, List, Optional, Tuple
import os
import json

from .rag import RAG
from .graph_rag import graph_context
from .cache import cag_get, cag_set

RAG_MODES = ["naive", "advanced", "graphrag", "agentic", "finetune", "cag"]

def naive_rag(rag: RAG, query: str, k: int = 6) -> Dict[str, Any]:
    return {"mode": "naive", "chunks": rag.search(query, k=k)}

def _rewrite_query(llm_provider, model: str, query: str) -> str:
    system = "Rewrite the user's query to be more precise for codebase retrieval. Output only the rewritten query."
    try:
        out = llm_provider.chat(system, query, model)
        return out.strip().strip('"')[:800]
    except Exception:
        return query

def _rerank(llm_provider, model: str, query: str, chunks: List[Dict[str, Any]], top_k: int = 6) -> List[Dict[str, Any]]:
    # Lightweight reranker using the LLM: ask it to choose best chunk indices.
    # If LLM fails, fall back to original order.
    if not chunks:
        return chunks
    prompt = {
        "query": query,
        "candidates": [{"i": i, "path": c["path"], "snippet": c["content"][:300]} for i, c in enumerate(chunks)]
    }
    system = 'Select the best candidates for answering the query. Output JSON with key "ranked" containing indices, e.g. {"ranked":[0,2,1]}'
    try:
        raw = llm_provider.chat(system, json.dumps(prompt, ensure_ascii=False), model)
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end+1])
        idxs = [i for i in data.get("ranked", []) if isinstance(i, int) and 0 <= i < len(chunks)]
        if not idxs:
            return chunks[:top_k]
        seen = set()
        ranked = []
        for i in idxs:
            if i in seen: 
                continue
            seen.add(i)
            ranked.append(chunks[i])
            if len(ranked) >= top_k:
                break
        return ranked
    except Exception:
        return chunks[:top_k]

def advanced_rag(rag: RAG, llm_provider, model: str, query: str, k: int = 10) -> Dict[str, Any]:
    rewritten = _rewrite_query(llm_provider, model, query)
    chunks = rag.search(rewritten, k=k)
    reranked = _rerank(llm_provider, model, query, chunks, top_k=6)
    return {"mode": "advanced", "rewritten_query": rewritten, "chunks": reranked}

def graphrag(rag: RAG, redis_client, query: str, k: int = 6) -> Dict[str, Any]:
    # Vector chunks + entity neighborhood context
    chunks = rag.search(query, k=k)
    gctx = graph_context(redis_client, query)
    return {"mode": "graphrag", "graph": gctx, "chunks": chunks}

def agentic_rag(rag: RAG, llm_provider, model: str, query: str) -> Dict[str, Any]:
    # A simple multi-step retrieval plan: the LLM proposes sub-queries, we retrieve for each.
    system = 'Break the task into 2-4 focused retrieval queries for a codebase. Output JSON like {"subqueries":["...","..."]}.'
    subqueries = [query]
    try:
        raw = llm_provider.chat(system, query, model)
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end+1])
        sq = [s for s in data.get("subqueries", []) if isinstance(s, str) and s.strip()]
        if sq:
            subqueries = sq[:4]
    except Exception:
        pass

    bundles = []
    for sq in subqueries:
        bundles.append({"subquery": sq, "chunks": rag.search(sq, k=4)})
    return {"mode": "agentic", "subqueries": subqueries, "bundles": bundles}

def finetune_style(redis_client, query: str) -> Dict[str, Any]:
    # Placeholder "fine-tuning" layer: store and apply style/policy snippets (safe, auditable).
    # This is NOT weight training; it's a controllable style/policy overlay.
    style = redis_client.get(b"finetune:style")
    style_text = style.decode("utf-8", errors="ignore") if style else ""
    return {"mode": "finetune", "style_overlay": style_text, "note": "This is a safe style overlay, not model weight fine-tuning."}

def cag(redis_client, rag: RAG, llm_provider, model: str, query: str) -> Tuple[Optional[dict], Optional[dict]]:
    # Cache-Augmented Generation: if we've seen this prompt, reuse the cached council response object.
    cached = cag_get(redis_client, prompt=query, rag_mode="cag")
    if cached:
        return cached, None
    # If not cached, run advanced retrieval (fast+consistent) and let downstream store response.
    ctx = advanced_rag(rag, llm_provider, model, query, k=8)
    return None, ctx

def get_context(rag: RAG, redis_client, llm_provider, model: str, query: str, mode: str) -> Dict[str, Any]:
    mode = (mode or "naive").lower()
    if mode not in RAG_MODES:
        mode = "naive"

    if mode == "naive":
        return naive_rag(rag, query)
    if mode == "advanced":
        return advanced_rag(rag, llm_provider, model, query)
    if mode == "graphrag":
        return graphrag(rag, redis_client, query)
    if mode == "agentic":
        return agentic_rag(rag, llm_provider, model, query)
    if mode == "finetune":
        return finetune_style(redis_client, query)
    if mode == "cag":
        cached, ctx = cag(redis_client, rag, llm_provider, model, query)
        # return ctx if no cache hit; caller can store final result
        return {"mode": "cag", "cache_hit": bool(cached), "cached": cached, "context": ctx}
    return naive_rag(rag, query)