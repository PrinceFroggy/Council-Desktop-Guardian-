from redis import Redis
from redis.commands.search.field import VectorField, TextField, TagField
from redis.commands.search.indexDefinition import IndexDefinition, IndexType

INDEX_NAME = "rag_idx"

def get_redis(redis_url: str) -> Redis:
    return Redis.from_url(redis_url, decode_responses=False)

def ensure_vector_index(r: Redis, dim: int):
    try:
        r.ft(INDEX_NAME).info()
        return
    except Exception:
        pass

    schema = (
        TextField("path"),
        TagField("lang"),
        TextField("content"),
        VectorField("embedding", "HNSW", {"TYPE": "FLOAT32", "DIM": dim, "DISTANCE_METRIC": "COSINE"}),
    )
    r.ft(INDEX_NAME).create_index(
        schema,
        definition=IndexDefinition(prefix=["doc:"], index_type=IndexType.HASH),
    )
