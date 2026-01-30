import re
from typing import Dict, List, Tuple

GRAPH_KEY = b"graph:edges"   # Redis hash: node -> json list of neighbors (lightweight)

def extract_entities(text: str) -> List[str]:
    # lightweight entity extraction: identifiers, class names, file-like tokens
    # You can replace with a stronger NER later.
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text)
    # keep some uniqueness
    seen = set()
    out = []
    for t in tokens:
        if t.lower() in {"the","and","for","with","from","return","class","import","public","private"}:
            continue
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:50]

def add_edges(redis_client, entities: List[str], path: str):
    # build co-occurrence edges within a document chunk
    # store as undirected adjacency lists (approx)
    for i, a in enumerate(entities):
        neigh = set(entities[max(0,i-5):i] + entities[i+1:i+6])
        if not neigh:
            continue
        key = f"{a}".encode()
        # merge adjacency in redis set for simplicity
        for b in neigh:
            redis_client.sadd(b"graph:adj:"+key, b.encode())
            redis_client.sadd(b"graph:adj:"+b.encode(), a.encode())

def graph_context(redis_client, query: str, max_nodes: int = 12) -> Dict[str, List[str]]:
    ents = extract_entities(query)
    ctx = {}
    for e in ents[:max_nodes]:
        neigh = [n.decode("utf-8", errors="ignore") for n in redis_client.smembers(b"graph:adj:"+e.encode())]
        if neigh:
            ctx[e] = neigh[:max_nodes]
    return ctx
