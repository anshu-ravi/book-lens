# LLM Model Configuration

Centralized configuration for LLM models used across BookLens. Change models for different purposes without touching code.

## Configuration Methods

### 1. Environment Variables (Recommended)

Set in `.env`:

```bash
# BRONZE stage: Extract structured knowledge from chapters
MODEL_EXTRACTION=gemini-3.1-flash-lite

# Q&A: Answer questions using knowledge graph
MODEL_QA_GENERATION=gemini-3.1-flash-lite

# Series lookup: Determine if book is part of series
MODEL_SERIES_LOOKUP=gemini-3.1-flash-lite

# Fallback for other LLM tasks
MODEL_DEFAULT=gemini-3.1-flash-lite
```

All are optional. Defaults to `gemini-3.1-flash-lite` if not set.

### 2. Programmatic Configuration

```python
from src.config import ModelConfig

# Check current config
print(ModelConfig.to_dict())
# Output: {
#   "extraction": "gemini-3.1-flash-lite",
#   "qa": "gemini-3.1-flash-lite",
#   "series_lookup": "gemini-3.1-flash-lite",
#   "default": "gemini-3.1-flash-lite"
# }

# Change a model at runtime
ModelConfig.set_model("extraction", "gemini-2.0-flash")
ModelConfig.set_model("qa", "gemini-1.5-pro")

# Get model for a purpose
extraction_model = ModelConfig.get_model("extraction")  # "gemini-2.0-flash"
qa_model = ModelConfig.get_model("qa")                  # "gemini-1.5-pro"
```

## Purposes & Defaults

| Purpose | Code Location | Use Case | Default | Cost |
|---|---|---|---|---|
| **extraction** | `src/knowledge/extractor.py` | BRONZE: Extract characters, relationships, world facts from chapter text | gemini-3.1-flash-lite | $0.25/M input |
| **qa** | `src/knowledge/qa.py` | Answer questions using knowledge graph context | gemini-3.1-flash-lite | $0.25/M input |
| **series_lookup** | `src/llm/gemini.py` | Detect if book is part of series + position | gemini-3.1-flash-lite | $0.25/M input |
| **default** | (fallback) | Any other LLM task not covered above | gemini-3.1-flash-lite | $0.25/M input |

## Examples

### Use Fast Model for Extraction, Detailed Model for Q&A

```bash
# .env
MODEL_EXTRACTION=gemini-3.1-flash-lite     # Fast, cheap (~30s per chapter)
MODEL_QA_GENERATION=gemini-1.5-pro         # More capable, higher cost (~1-3 cents per question)
```

**Effect:**
- `python scripts/extract.py` → uses fast model
- `python scripts/ask.py` → uses powerful model for better answers

### Cost-Optimize Everything

```bash
# .env
MODEL_EXTRACTION=gemini-3.1-flash-lite     # $0.25/M input
MODEL_QA_GENERATION=gemini-3.1-flash-lite  # $0.25/M input
MODEL_SERIES_LOOKUP=gemini-3.1-flash-lite  # $0.25/M input
```

**Cost:** ~2 cents to extract full Red Rising book + answer 10 questions

### Experiment with New Models

```python
# At startup or in tests
from src.config import ModelConfig

# Test new model
ModelConfig.set_model("extraction", "gemini-2.5-flash")

# Run extraction — will use new model without code changes
```

## Where Models Are Used

### 1. BRONZE Extraction
**File:** `src/knowledge/extractor.py:160`

```python
extraction_model = ModelConfig.get_model("extraction")
response = self.client.models.generate_content(model=extraction_model, ...)
```

→ Extracts characters, relationships, world facts, summaries from chapter text

### 2. Q&A Generation
**File:** `src/knowledge/qa.py:89`

```python
qa_model = ModelConfig.get_model("qa")
response = await self.gemini_client.aio.models.generate_content(model=qa_model, ...)
```

→ Answers questions using knowledge graph context

### 3. Series Lookup
**File:** `src/llm/gemini.py:159`

```python
series_model = ModelConfig.get_model("series_lookup")
search_response = self._client.models.generate_content(model=series_model, ...)
```

→ Detects if a book is part of a series + its position

## Switching Models at Runtime

```python
import asyncio
from src.config import ModelConfig
from src.knowledge.qa import KnowledgeQA

async def main():
    # Use fast model for Q&A
    ModelConfig.set_model("qa", "gemini-3.1-flash-lite")
    qa = KnowledgeQA("red-rising")
    answer = await qa.ask("Who is Eo?", up_to_chapter=4)
    print(answer)

asyncio.run(main())
```

## Testing Different Models

```bash
# Quick test with fast model
export MODEL_EXTRACTION=gemini-3.1-flash-lite
python scripts/extract.py --epub uploads/red-rising/book_0.epub --series red-rising --limit 1

# Detailed test with better model (if you have access)
export MODEL_EXTRACTION=gemini-2.0-flash
python scripts/extract.py --epub uploads/red-rising/book_0.epub --series red-rising --limit 1
```

Compare extraction quality and speed.

## API Reference

### `ModelConfig` Class

**Methods:**

```python
@classmethod
def get_model(purpose: str) -> str:
    """Get model for a purpose: 'extraction', 'qa', 'series_lookup', 'default'"""

@classmethod
def set_model(purpose: str, model: str) -> None:
    """Set model for a purpose at runtime"""

@classmethod
def to_dict() -> dict[str, str]:
    """Return current config as {purpose: model}"""
```

**Attributes:**

```python
EXTRACTION_MODEL: str           # Current model for extraction
QA_GENERATION_MODEL: str        # Current model for Q&A
SERIES_LOOKUP_MODEL: str        # Current model for series lookup
DEFAULT_MODEL: str              # Fallback model
```

## Error Handling

```python
from src.config import ModelConfig

try:
    ModelConfig.get_model("invalid_purpose")
except ValueError as e:
    print(e)
    # Output: Unknown purpose: invalid_purpose. 
    #         Valid options: extraction, qa, series_lookup, default
```

## Future Enhancements

- [ ] YAML config file: `config/models.yaml` for non-developers
- [ ] Per-series model config: extract Red Rising with fast model, Licanius with detailed
- [ ] Cost tracking: log which model used + estimated cost per operation
- [ ] Performance benchmarking: track extraction speed + Q&A answer quality by model

