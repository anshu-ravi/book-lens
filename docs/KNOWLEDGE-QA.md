# Knowledge Graph Q&A System

Ask natural-language questions about a book series using its Neo4j knowledge graph. The system retrieves relevant context and generates answers via Gemini.

## Quick Start

```bash
# Who is this character?
python scripts/ask.py \
  --series red-rising \
  --chapter 4 \
  --question "Who is Eo and what is her relationship with Darrow?"

# World-building question
python scripts/ask.py \
  --series red-rising \
  --chapter 4 \
  --question "What is the color caste system and how does it affect daily life?"

# Spoiler-safe (limits to chapter N)
python scripts/ask.py \
  --series red-rising \
  --chapter 2 \
  --question "What happens in chapters 3 and 4?"
  # Output: "I only have information up to chapter 2..."

# Relationship mapping
python scripts/ask.py \
  --series red-rising \
  --chapter 4 \
  --question "Who does Darrow have conflict with and why?"
```

## How It Works

### 1. Semantic Search
The question is embedded and used to find the **top K characters** most relevant to the query via Neo4j vector index.

```
Query: "Who is Eo and what is her relationship with Darrow?"
                          ↓
        Semantic search → Top 5 characters
        - Eo (ROMANCE) — score 0.85
        - Darrow (PROTAGONIST) — score 0.82
        - Uncle Narol (FAMILY) — score 0.71
        ...
```

### 2. Context Retrieval
For each relevant character, fetch:
- Full profile: name, aliases, faction, description
- All relationships (ALLY, ENEMY, FAMILY, ROMANCE, MENTOR, RIVAL)
- World facts (caste system, technology, ideology)
- Chapter summaries (up to spoiler cutoff)

### 3. Context Formatting
Build a structured context block:

```
## Characters
### Darrow (Red, Protagonist)
- A sixteen-year-old member of the Red caste...
- Relationships: Eo (ROMANCE), Uncle Narol (FAMILY)

### Eo (Red)
- Darrow's wife. She is sixteen years old...

## World Facts
- Color Caste System (Social Structure): A hierarchical society...
- The Noble Lie (Ideology): A rejected democratic philosophy...

## Chapter Summaries
- Chapter 0 (Prologue): Introduces the Gold class...
- Chapter 1 (1: Helldiver): Darrow enters the mines...
- Chapter 2 (2: The Township): Life in the mining settlement...
```

### 4. LLM Generation
Call Gemini 3.1 Flash-Lite with:
- **System Prompt:** Instructions to answer only from context, respect spoiler cutoff
- **User Question:** The actual question
- **Context Block:** Structured data from Neo4j

→ **Answer:** Concise, grounded in the knowledge graph

## CLI Reference

```bash
python scripts/ask.py \
  --series <series_id>      # Required: 'red-rising', etc.
  --chapter <int>           # Required: Spoiler cutoff (0-indexed)
  --question <str>          # Required: Your question
  --top-k <int>             # Optional: Top K chars (default: 5)
```

### Examples

```bash
# Character details
python scripts/ask.py --series red-rising --chapter 4 \
  --question "Describe Darrow's personality and role"

# Plot questions
python scripts/ask.py --series red-rising --chapter 4 \
  --question "What is the Laurel and why does Darrow care about it?"

# Multiple character interactions
python scripts/ask.py --series red-rising --chapter 4 \
  --question "How do Eo, Uncle Narol, and Barlow view Darrow?"

# Predictions/future (should fail gracefully)
python scripts/ask.py --series red-rising --chapter 2 \
  --question "Does Darrow succeed in his goals?"
  # Expected: "I don't have information about chapters 3 and beyond"
```

## Programmatic Usage

```python
import asyncio
from src.knowledge.qa import KnowledgeQA

async def main():
    qa = KnowledgeQA("red-rising")
    
    answer = await qa.ask(
        question="Who is Eo?",
        up_to_chapter=4,
        top_k=5
    )
    
    print(answer)

asyncio.run(main())
```

## Architecture

### `src/knowledge/qa.py` — `KnowledgeQA` Class

**Methods:**

| Method | Signature | Purpose |
|---|---|---|
| `__init__` | `(series_id: str)` | Initialize with series ID |
| `ask` | `(question: str, up_to_chapter: int, top_k: int = 5) -> str` | Answer a question |
| `_build_context` | Private | Format retrieved data into context block |
| `_get_world_facts` | Private | Query Neo4j for world facts |
| `_get_chapter_summaries` | Private | Fetch chapter summaries |

**Dependencies:**
- `KnowledgeQueryEngine` — semantic search, character profiles, relationships
- `GeminiLLMClient` — generation via Gemini 3.1 Flash-Lite
- `get_driver()` — Neo4j access

### `scripts/ask.py` — CLI Wrapper

Parses arguments and calls `KnowledgeQA.ask()` asynchronously.

## Test Results (Red Rising, 5 chapters)

### Test 1: Character Question
```
Q: "Who is Eo and what is her relationship with Darrow?"

A: Based on the chapters provided, Eo is Darrow's wife. She is a 
sixteen-year-old girl with red hair, whom Darrow sees as being made 
of something more ethereal than the mines.
```

✅ **Pass:** Correctly identified character + relationship

### Test 2: World Question
```
Q: "What is the color caste system and how does it affect daily life?"

A: The color caste system is a rigid, hierarchical governing power that 
suppresses the Red population. It is a meritocracy based on birth where 
Gold class serves as ruling elite, Grays act as military enforcers, and 
Reds are the labor class.

Regarding daily life:
* Labor: Reds work in deep tunnels of Mars to extract helium-3
* Resource Control: Society controls distribution of food and comforts
* The Laureltide: Awards "Laurel" to most productive mining clan
* Propaganda: Society broadcasts messages to suppress population
* Enforcement: Grays (like Ugly Dan) oversee Red miners
```

✅ **Pass:** Comprehensive world-building context

### Test 3: Spoiler Safety
```
Q: "What happens in chapters 3 and 4?" (up_to_chapter=2)

A: I do not know the answer to that. Based on the provided instructions, 
I can only provide information from chapters the reader has reached 
(up to chapter 2).
```

✅ **Pass:** Correctly respects spoiler cutoff

### Test 4: Relationship Mapping
```
Q: "Who does Darrow have conflict with and why?"

A: Darrow has a conflict with the Society (the ruling governing power). 
His conflict stems from systemic oppression and injustice enforced by 
the Society. He also harbors resentment toward Uncle Narol, who embodies 
cautious, stagnant acceptance of their harsh conditions that Darrow despises.
```

✅ **Pass:** Identified primary + secondary conflicts

## Advantages Over Simple RAG

| Aspect | Simple RAG | Knowledge Graph |
|---|---|---|
| **Relationships** | Implicit (if mentioned in text) | Explicit (stored as edges) |
| **Identity Resolution** | May confuse aliases | Resolved at query time |
| **World Facts** | Scattered across passages | Structured by category |
| **Spoiler Safety** | Hard to enforce | Built-in (chapter index on every node) |
| **Context Quality** | Best matches by similarity | All relevant entities + their interactions |

## Limitations

1. **Extraction Quality:** Answers limited by quality of BRONZE/SILVER extraction
2. **Early Chapters:** Only 5 chapters extracted; full series needed for comprehensive context
3. **Speculative Questions:** Graph contains only explicit facts, not predictions
4. **Nuance:** LLM answer quality depends on Gemini's understanding of provided context

## Next Steps

1. **Full Extraction:** Extract all chapters of Red Rising trilogy
2. **Multi-Book Support:** Handle relationships between books in same series
3. **Advanced Queries:** Support follow-up questions + conversation history
4. **Web UI:** Add Q&A to frontend alongside reading companion
5. **Explainability:** Return which characters/facts were used for each answer

## Configuration

**Environment:**
```bash
GOOGLE_API_KEY=your-key  # Gemini API key
NEO4J_URI=neo4j://localhost:7687  # Neo4j bolt URI
NEO4J_USER=neo4j
NEO4J_PASS=password
```

**Model:**
- **Generation:** `gemini-3.1-flash-lite` ($0.25/M input tokens)
- **Cost:** ~1-3 cents per question (including context retrieval)

