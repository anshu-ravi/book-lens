import asyncio
import os
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
GROUP_ID = "red_rising_book1"

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
    
    from graphiti_core.search.search_filters import SearchFilters, DateFilter, ComparisonOperator
    from datetime import datetime, timezone, timedelta
    
    BASE_DATE = datetime(2000, 1, 1, tzinfo=timezone.utc)
    def chapter_timestamp(index: int) -> datetime:
        return BASE_DATE + timedelta(days=index)
        
    def at_chapter(boundary: int) -> SearchFilters:
        return SearchFilters(
            valid_at=[[DateFilter(
                date=chapter_timestamp(boundary),
                comparison_operator=ComparisonOperator.less_than_equal,
            )]]
        )
        
    # Query without filter
    res = await graphiti.search(query="what is happening with Eo", group_ids=[GROUP_ID])
    print("Without filter:", len(res))
    
    # Query with filter
    res_filtered = await graphiti.search(query="what is happening with Eo", group_ids=[GROUP_ID], search_filter=at_chapter(10))
    print("With filter:", len(res_filtered))
    
if __name__ == "__main__":
    asyncio.run(main())
