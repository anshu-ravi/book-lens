#!/usr/bin/env python3
"""Clean up canonical alias registry by removing generic/silly aliases."""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env")

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import ModelConfig
from src.supabase_client import get_supabase_client
from google import genai

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def clean_registry(user_id: str, series_id: str) -> None:
    """Clean up the canonical alias registry for a series.

    Removes lowercase-only aliases and evaluates others with single LLM call.
    """
    logger.info(f"Loading registry for user_id={user_id}, series_id={series_id}")

    client = get_supabase_client()
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    genai_client = genai.Client(api_key=api_key)

    # Load registry
    try:
        registry_path = f"extractions/{user_id}/{series_id}/canonical_registry.json"
        logger.debug(f"Downloading from: {registry_path}")
        registry_raw = client.storage.from_("extractions").download(registry_path)
        registry = json.loads(registry_raw)
        logger.info(f"✓ Loaded {len(registry)} entries")
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return

    logger.info(f"Loaded {len(registry)} entries from registry")

    # Separate aliases from canonical entries
    aliases = {k: v for k, v in registry.items() if k != v}
    canonical_entries = {k: v for k, v in registry.items() if k == v}

    logger.info(f"Found {len(aliases)} aliases, {len(canonical_entries)} canonical names")

    # Rule 1: Remove lowercase-only versions locally
    lowercase_removed = 0
    filtered_aliases = {}
    for alias, canonical in aliases.items():
        if alias.lower() == canonical.lower():
            logger.debug(f"  REMOVE (lowercase): {alias} → {canonical}")
            lowercase_removed += 1
        else:
            filtered_aliases[alias] = canonical

    logger.info(f"Removed {lowercase_removed} lowercase-only aliases")

    # Rule 2: Ask LLM to evaluate remaining aliases in one call
    logger.info(f"Evaluating {len(filtered_aliases)} aliases with LLM...")

    alias_list = "\n".join(
        f"- {alias} → {canonical}" for alias, canonical in sorted(filtered_aliases.items())
    )

    prompt = f"""Review these character name aliases and identify which ones to REMOVE because they are:
1. Too generic (e.g., "boy", "handsome", "brother", "man")
2. Silly/nonsensical variations
3. Adjectives or descriptions rather than names

Keep legitimate contextual nicknames/epithets (e.g., "reaper", "godslayer", "little prince").

Aliases to evaluate:
{alias_list}

Return ONLY a JSON array of aliases to REMOVE (as strings), nothing else:
["alias1", "alias2", "alias3"]

If none should be removed, return: []"""

    try:
        model = ModelConfig.get_model("qa")
        response = await genai_client.aio.models.generate_content(
            model=model,
            contents=prompt,
        )

        # Parse response
        response_text = response.text.strip()
        # Extract JSON array from response (in case there's extra text)
        import re

        match = re.search(r"\[.*\]", response_text, re.DOTALL)
        if match:
            to_remove = json.loads(match.group())
        else:
            logger.warning(f"Could not parse LLM response: {response_text}")
            to_remove = []

        logger.info(f"LLM recommends removing {len(to_remove)} aliases")

        # Build cleaned aliases
        cleaned_aliases = {
            k: v for k, v in filtered_aliases.items() if k not in to_remove
        }

        # Show what was removed
        for alias in to_remove:
            if alias in filtered_aliases:
                logger.debug(f"  REMOVE: {alias} → {filtered_aliases[alias]}")

    except Exception as e:
        logger.error(f"LLM evaluation failed: {e}, keeping all filtered aliases")
        cleaned_aliases = filtered_aliases
        to_remove = []

    # Rebuild registry
    new_registry = {**canonical_entries, **cleaned_aliases}

    total_removed = lowercase_removed + len(to_remove)
    logger.info(
        f"Final registry: {len(aliases)} → {len(cleaned_aliases)} aliases "
        f"({total_removed} total removed)"
    )

    # Save back to Supabase
    try:
        registry_path = f"extractions/{user_id}/{series_id}/canonical_registry.json"

        # Delete existing
        try:
            client.storage.from_("extractions").remove([registry_path])
        except Exception:
            pass

        # Upload cleaned registry
        json_bytes = json.dumps(new_registry, indent=2).encode("utf-8")
        client.storage.from_("extractions").upload(
            path=registry_path,
            file=json_bytes,
            file_options={"content-type": "application/json"},
        )
        logger.info(f"✓ Saved cleaned registry to {registry_path}")
    except Exception as e:
        logger.error(f"Failed to save registry: {e}")


async def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Clean up canonical alias registry")
    parser.add_argument("user_id", help="User ID")
    parser.add_argument("series_id", help="Series ID")

    args = parser.parse_args()

    await clean_registry(args.user_id, args.series_id)


if __name__ == "__main__":
    asyncio.run(main())
