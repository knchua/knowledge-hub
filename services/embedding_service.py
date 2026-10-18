"""OpenAI embeddings for Knowledge Hub Phase 2 (no chat completions)."""
from __future__ import annotations
import os
from functools import lru_cache

MODEL = "text-embedding-3-small"
DIMENSIONS = 1536
BATCH_SIZE = 64

class EmbeddingError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        try:
            import streamlit as st
            key = str(st.secrets.get("OPENAI_API_KEY", "")).strip()
        except Exception:
            pass
    if not key:
        raise EmbeddingError("OPENAI_API_KEY is not configured.")
    return key


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch embed, preserving order. SDK retries transient failures by default."""
    if not texts or any(not isinstance(t, str) or not t.strip() for t in texts):
        raise EmbeddingError("No valid text to embed.")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=_api_key(), timeout=60.0, max_retries=2)
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), BATCH_SIZE):
            group = texts[offset:offset + BATCH_SIZE]
            response = client.embeddings.create(model=MODEL, input=group, dimensions=DIMENSIONS)
            ordered = sorted(response.data, key=lambda item: item.index)
            if len(ordered) != len(group) or [x.index for x in ordered] != list(range(len(group))):
                raise EmbeddingError("Embedding response did not match the requested chunks.")
            for item in ordered:
                vector = item.embedding
                if len(vector) != DIMENSIONS:
                    raise EmbeddingError("Unexpected embedding dimension.")
                vectors.append(vector)
        return vectors
    except EmbeddingError:
        raise
    except Exception as exc:
        raise EmbeddingError("OpenAI embedding generation failed. Check credentials and provider availability.") from exc
