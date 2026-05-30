"""Embedder using sentence-transformers for dense vector representations."""

from sentence_transformers import SentenceTransformer


class Embedder:
    """Wraps sentence-transformers for embedding text."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        """Initialize embedder with sentence-transformers model.

        Args:
            model_name: Name of the sentence-transformers model to use.
                       Default: all-MiniLM-L6-v2 (384 dims, fast)
        """
        self.model = SentenceTransformer(model_name)

    def embed(self, text: str) -> list[float]:
        """Embed a single text string.

        Args:
            text: Text to embed.

        Returns:
            List of floats representing the embedding.
        """
        embedding = self.model.encode(text, convert_to_tensor=False)
        return embedding.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts efficiently.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.
        """
        embeddings = self.model.encode(texts, convert_to_tensor=False)
        return [emb.tolist() for emb in embeddings]
