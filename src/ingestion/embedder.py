"""SentenceTransformer embedding wrapper with lazy singleton initialisation."""

from sentence_transformers import SentenceTransformer

from src.config import settings
from src.models import ChunkRecord

_model: SentenceTransformer | None = None


def get_embedder() -> SentenceTransformer:
    """Return the shared SentenceTransformer instance, loading it on first call.

    Returns:
        Loaded SentenceTransformer model.
    """
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.embedding_model)
    return _model


def embed_chunks(chunks: list[ChunkRecord], batch_size: int = 64) -> list[list[float]]:
    """Embed a list of chunks using the shared model.

    Args:
        chunks: ChunkRecords whose text fields will be embedded.
        batch_size: Number of texts to encode in each forward pass.

    Returns:
        List of embedding vectors (one per chunk, same order).
    """
    model = get_embedder()
    texts = [chunk.text for chunk in chunks]
    embeddings = model.encode(texts, batch_size=batch_size, show_progress_bar=False)
    return [e.tolist() for e in embeddings]


def embed_query(text: str) -> list[float]:
    """Embed a single query string.

    Args:
        text: The query text to embed.

    Returns:
        Embedding vector as a list of floats.
    """
    model = get_embedder()
    return model.encode(text).tolist()
