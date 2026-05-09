import asyncio
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

from graphiti_core import Graphiti
from graphiti_core.driver.kuzu_driver import KuzuDriver 
from graphiti_core.llm_client.gemini_client import GeminiClient, LLMConfig
from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig
from graphiti_core.cross_encoder.gemini_reranker_client import GeminiRerankerClient
from pydantic import BaseModel, Field

load_dotenv()

gemini_api_key = os.environ["GEMINI_API_KEY"]


class Character(BaseModel):
    name: str = Field(description="The primary name of the character")
    role: str = Field(description="The character's role or occupation")
    known_aliases: list[str] = Field(description="Other names this character is called")

class Location(BaseModel):
    name: str = Field(description="Name of the place")

async def main():
    # 1. Initialize the Kuzu Driver first (using a local directory)
    driver = KuzuDriver(db="./my_book_db")
    
    # 2. Pass the driver to Graphiti via the `graph_driver` argument
    graphiti = Graphiti(
        graph_driver=driver,
        llm_client=GeminiClient(config=LLMConfig(api_key=gemini_api_key)),
        embedder=GeminiEmbedder(config=GeminiEmbedderConfig(api_key=gemini_api_key)),
        cross_encoder=GeminiRerankerClient(config=LLMConfig(api_key=gemini_api_key))
    )
    
    try:
        await graphiti.build_indices_and_constraints()
        print("Graphiti initialized successfully!")

        # MAP YOUR CUSTOM ENTITIES TO A DICTIONARY
        my_entity_types = {
            "Character": Character,
            "Location": Location
        }

        chapters = [
            "The young farmboy, Garion, lived on Faldor's Farm.",
            "Garion discovered his true name was Belgarion, a powerful sorcerer."
        ]

        for i, text in enumerate(chapters):
            chapter_number = i + 1
            # Best practice: use timezone-aware datetimes with Graphiti
            chapter_time = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=chapter_number)
            
            print(f"Processing Chapter {chapter_number}...")
            await graphiti.add_episode(
                name=f"Chapter_{chapter_number}",
                episode_body=text,
                source="epub_text", # Or use EpisodeType.text if imported
                reference_time=chapter_time, 
                entity_types=my_entity_types
            )
            await asyncio.sleep(1) 

        print("\n--- Querying knowledge at Chapter 1 ---")
        time_at_chapter_1 = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=1)
        
        results = await graphiti.search(
            "Who is Garion and what is his role?",
            temporal_filter={"end_time": time_at_chapter_1}
        )
        
        for result in results:
            print(f"Fact: {result.fact}") 
            
    finally:
        await graphiti.close()
        print("Kuzu database closed")

if __name__ == '__main__':
    asyncio.run(main())