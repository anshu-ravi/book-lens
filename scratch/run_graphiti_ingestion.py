import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv(dotenv_path="notebooks/.env") or load_dotenv()

from graphiti_core import Graphiti
from graphiti_core.driver.neo4j_driver import Neo4jDriver
from graphiti_core.llm_client.gemini_client import GeminiClient, LLMConfig
from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig
from graphiti_core.cross_encoder.gemini_reranker_client import GeminiRerankerClient
import warnings
import logging
logging.getLogger("neo4j").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

from google.genai import types
_orig_config_init = types.GenerateContentConfig.__init__
def _patched_config_init(self, **kwargs):
    kwargs.setdefault("safety_settings", [
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
    ])
    _orig_config_init(self, **kwargs)
types.GenerateContentConfig.__init__ = _patched_config_init

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
EPUB_PATH      = "uploads/red-rising/book_0.epub"
GROUP_ID       = "red_rising_book1"
MAX_CHAPTERS   = 5
os.environ["SEMAPHORE_LIMIT"] = "5"

from datetime import datetime, timezone, timedelta
BASE_DATE = datetime(2000, 1, 1, tzinfo=timezone.utc)
def chapter_timestamp(index: int) -> datetime:
    return BASE_DATE + timedelta(days=index)

async def main():
    graphiti = Graphiti(
        graph_driver=Neo4jDriver(
            uri="bolt://localhost:7687",
            user="neo4j",
            password="",
        ),
        llm_client=GeminiClient(config=LLMConfig(api_key=GOOGLE_API_KEY, model="gemini-2.5-flash-lite")),
        embedder=GeminiEmbedder(config=GeminiEmbedderConfig(api_key=GOOGLE_API_KEY, embedding_model="gemini-embedding-001")),
        cross_encoder=GeminiRerankerClient(config=LLMConfig(api_key=GOOGLE_API_KEY, model="gemini-2.5-flash-lite")),
    )
    await graphiti.build_indices_and_constraints()
    
    sys.path.append("src")
    from graphiti_core.nodes import EpisodeType
    from src.ingestion.epub_parser import parse_epub
    
    CHUNK_WORDS = 800
    def chunk_text(text: str, max_words: int) -> list[str]:
        words = text.split()
        return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]
        
    chapters = parse_epub(EPUB_PATH)[:MAX_CHAPTERS]
    for chapter in chapters:
        chunks = chunk_text(chapter.text, CHUNK_WORDS)
        n = len(chunks)
        print(f"[{chapter.index}] {chapter.label} ({len(chapter.text.split())} words, {n} chunk(s))...", end=" ")
        for i, chunk in enumerate(chunks):
            await graphiti.add_episode(
                name=f"Ch{chapter.index}.{i}: {chapter.label}",
                episode_body=chunk,
                source=EpisodeType.text,
                reference_time=chapter_timestamp(chapter.index),
                source_description=f"Red Rising Book 1 — {chapter.label} (part {i+1}/{n})",
                group_id=GROUP_ID,
            )
        print("done")
        
    from graphiti_core.search.search_filters import SearchFilters, DateFilter, ComparisonOperator
    def at_chapter(boundary: int) -> SearchFilters:
        return SearchFilters(
            valid_at=[[DateFilter(
                date=chapter_timestamp(boundary),
                comparison_operator=ComparisonOperator.less_than_equal,
            )]]
        )
        
    async def query_at_chapter(query, chapter_boundary, n=10):
        return await graphiti.search(
            query=query,
            group_ids=[GROUP_ID],
            num_results=n,
            search_filter=at_chapter(chapter_boundary),
        )

    early = await query_at_chapter("what is happening with Eo", chapter_boundary=1)
    late  = await query_at_chapter("what is happening with Eo", chapter_boundary=4)

    print("\n=== TEST A: Spoiler-safe Retrieval ===")
    print(f"\nEarly query (Chapter <=3, {len(early)} results):")
    print(f"\nLate query (Chapter <=9, {len(late)} results):")
    
if __name__ == "__main__":
    asyncio.run(main())
