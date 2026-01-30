import os
import hashlib

from .graph_rag import extract_entities, add_edges

TEXT_EXT = {".md",".txt",".swift",".m",".mm",".h",".hpp",".cpp",".c",".cs",".js",".ts",".py",".json",".yml",".yaml",".xml",".gradle",".java"}

def chunk_text(text: str, max_chars=2200, overlap=200):
    chunks = []
    i = 0
    while i < len(text):
        j = min(len(text), i + max_chars)
        chunks.append(text[i:j])
        i = j - overlap
        if i < 0:
            i = 0
        if i >= len(text):
            break
    return chunks

def file_lang(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return ext[1:] if ext.startswith(".") else "txt"

def index_repo(repo_path: str, rag, redis_client=None):
    for root, _, files in os.walk(repo_path):
        if "/.git/" in root.replace("\\","/"):
            continue
        for fn in files:
            p = os.path.join(root, fn)
            ext = os.path.splitext(p)[1].lower()
            if ext not in TEXT_EXT:
                continue
            try:
                data = open(p, "r", encoding="utf-8", errors="ignore").read()
            except Exception:
                continue

            rel = os.path.relpath(p, repo_path).replace("\\","/")
            lang = file_lang(rel)
            for idx, chunk in enumerate(chunk_text(data)):
                h = hashlib.sha1((rel + str(idx) + chunk[:50]).encode()).hexdigest()
                key = f"doc:{h}"
                rag.upsert_doc(key, rel, lang, chunk)
                if redis_client is not None:
                    ents = extract_entities(chunk)
                    add_edges(redis_client, ents, rel)
