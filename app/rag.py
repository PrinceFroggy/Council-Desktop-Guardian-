import numpy as np
from sentence_transformers import SentenceTransformer
from redis.commands.search.query import Query
from .redis_store import INDEX_NAME


def _to_str(x) -> str:
    """RedisSearch may return fields as bytes or str depending on config/version."""
    if x is None:
        return ""
    if isinstance(x, bytes):
        return x.decode(errors="ignore")
    return str(x)


def _to_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


class RAG:
    def __init__(self, redis_client, model_name="sentence-transformers/all-MiniLM-L6-v2"):
        self.r = redis_client
        self.embedder = SentenceTransformer(model_name)
        self.dim = self.embedder.get_sentence_embedding_dimension()

    def embed(self, text: str) -> bytes:
        v = self.embedder.encode([text], normalize_embeddings=True)[0].astype(np.float32)
        return v.tobytes()

    def upsert_doc(self, key: str, path: str, lang: str, content: str):
        emb = self.embed(content)
        self.r.hset(
            key,
            mapping={
                b"path": path.encode(),
                b"lang": lang.encode(),
                b"content": content.encode(),
                b"embedding": emb,
            },
        )

    def search(self, query: str, k: int = 6):
        qemb = self.embed(query)
        q = (
            Query(f"*=>[KNN {k} @embedding $vec AS score]")
            .sort_by("score")
            .return_fields("path", "lang", "content", "score")
            .dialect(2)
        )

        res = self.r.ft(INDEX_NAME).search(q, query_params={"vec": qemb})

        out = []
        for doc in res.docs:
            # doc.<field> might be bytes or str (or even missing), so be defensive.
            out.append(
                {
                    "path": _to_str(getattr(doc, "path", "")),
                    "lang": _to_str(getattr(doc, "lang", "")),
                    "content": _to_str(getattr(doc, "content", "")),
                    "score": _to_float(getattr(doc, "score", 0.0)),
                }
            )
        return out
