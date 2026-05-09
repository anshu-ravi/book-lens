import asyncio
import os
import json
import sys

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# --- CONFIG ---
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    print("Error: GEMINI_API_KEY not found in environment")
    print("Please add GEMINI_API_KEY to your .env file")
    sys.exit(1)

EPUB_PATH = "./uploads/red-rising/book_0.epub"

# Modern Gemini models for extraction
EXTRACTION_MODEL = "gemini-3.1-flash-lite"

# --- NEW SDK IMPORT ---
from google import genai
from google.genai import types

# --- YOUR LOCAL MODULES ---
from src.ingestion.epub_parser import parse_epub

# Initialize the new Client
client = genai.Client(api_key=API_KEY)


async def extract_chapter_json(chapter_text: str, label: str) -> dict | None:
    """
    Extract entities using Gemini's latest JSON schema mode.
    Follows the full schema expected by Graphiti and the knowledge base.
    """
    prompt = f"""
    Analyze the text from chapter: {label}
    Extract ALL story entities and relationships in STRICT JSON format.

    OUTPUT REQUIREMENTS (STRICT - must match exactly):
    {{
      "characters": [
        {{
          "name": "Character Name",
          "aliases": ["Also known as", "nickname"],
          "faction": "Faction or group they belong to",
          "role": "protagonist, antagonist, mentor, ally, etc.",
          "description": "2-3 sentence description of this character based on this chapter",
          "key_events": ["Event 1 that happened to this character", "Event 2"]
        }}
      ],
      "relationships": [
        {{
          "character_a": "Character Name",
          "character_b": "Other Character Name",
          "type": "ally, rival, family, romance, mentor, enemy, or other",
          "description": "Current state of this relationship",
          "moments": ["Key moment showing this relationship"]
        }}
      ],
      "world_facts": [
        {{
          "category": "location, faction, concept, technology, rule, power_system, etc.",
          "name": "Name of the fact",
          "description": "What is this fact about?"
        }}
      ],
      "summary": "200-300 word narrative recap of main events in this chapter"
    }}

    CRITICAL RULES:
    1. Characters MUST be objects with all fields, not just strings
    2. Relationships MUST reference characters that exist in the characters list
    3. Output ONLY valid JSON, no markdown, no code blocks
    4. Include meaningful aliases (titles, nicknames), exclude throwaway terms
    5. Focus on state changes and important plot developments

    TEXT:
    {chapter_text[:25000]}
    """

    try:
        # Use Gemini's JSON schema mode for structured output
        response = await client.aio.models.generate_content(
            model=EXTRACTION_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            ),
        )

        # Parse the JSON response
        if response.text:
            data = json.loads(response.text)
            # Handle case where response is wrapped in a list (shouldn't happen with this prompt)
            if isinstance(data, list):
                return {"characters": [], "relationships": data, "world_facts": [], "summary": ""}
            return data
        return None
    except Exception as e:
        print(f"Extraction error for {label}: {e}")
        return None


async def main(num_chapters: int = 10) -> None:
    """Main extraction pipeline.

    Args:
        num_chapters: Number of chapters to process (default: 10)
    """
    # Check if EPUB exists
    if not os.path.exists(EPUB_PATH):
        print(f"Error: EPUB file not found at {EPUB_PATH}")
        print("Please ensure the EPUB file exists at the specified path")
        return

    # Parse EPUB
    print("Parsing EPUB...")
    try:
        chapters = parse_epub(EPUB_PATH)
        print(f"Parsed {len(chapters)} chapters.")
    except Exception as e:
        print(f"Error parsing EPUB: {e}")
        return

    # Create output directory
    os.makedirs("./notebooks/extractions", exist_ok=True)

    # Process chapters sequentially
    extracted_count = 0
    skipped_count = 0
    chapters_to_process = min(num_chapters, len(chapters))
    for i, chapter in enumerate(chapters[:chapters_to_process]):
        output_file = f"./notebooks/extractions/{chapter.label.replace('/', '_')}.json"
        print(f"\n[{i+1}] Processing: {chapter.label}")

        # Check if already extracted
        if os.path.exists(output_file):
            with open(output_file, "r") as f:
                chapter_data = json.load(f)
            print(f"  ⊘ Already extracted (skipped)")
            print(f"    • {len(chapter_data.get('characters', []))} characters, "
                  f"{len(chapter_data.get('relationships', []))} relationships")
            skipped_count += 1
            continue

        # Extract if not already done
        chapter_data = await extract_chapter_json(chapter.text, chapter.label)

        if chapter_data:
            print(f"  ✓ Extracted: {len(chapter_data.get('characters', []))} characters, "
                  f"{len(chapter_data.get('relationships', []))} relationships")
            extracted_count += 1

            # Save to file for inspection
            with open(output_file, "w") as f:
                json.dump(chapter_data, f, indent=2)
            print(f"  → Saved to {output_file}")
        else:
            print(f"  ✗ Extraction failed")

        # Throttle requests
        await asyncio.sleep(1.0)

    print(f"\n\nSummary:")
    print(f"  • Newly extracted: {extracted_count}")
    print(f"  • Already extracted: {skipped_count}")
    print(f"  • Total: {extracted_count + skipped_count}/{chapters_to_process} chapters")


if __name__ == "__main__":
    num_chapters = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    asyncio.run(main(num_chapters))