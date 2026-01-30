import numpy as np
from sentence_transformers import SentenceTransformer
from redis.commands.search.query import Query
from .redis_store import INDEX_NAME

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
        self.r.hset(key, mapping={
            b"path": path.encode(),
            b"lang": lang.encode(),
            b"content": content.encode(),
            b"embedding": emb,
        })

    def search(self, query: str, k: int = 6):
        qemb = self.embed(query)
        q = Query(f"*=>[KNN {k} @embedding $vec AS score]") \
            .sort_by("score") \
            .return_fields("path", "lang", "content", "score") \
            .dialect(2)

        res = self.r.ft(INDEX_NAME).search(q, query_params={"vec": qemb})
        out = []
        for doc in res.docs:
            out.append({
                "path": doc.path.decode(errors="ignore"),
                "lang": doc.lang.decode(errors="ignore"),
                "content": doc.content.decode(errors="ignore"),
                "score": float(doc.score),
            })
        return out
