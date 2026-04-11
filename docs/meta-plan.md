# BookLens Meta-Plan & Expert Development Guide

## 📚 Project Overview
A single-user, spoiler-safe reading companion web app built iteratively following industry best practices.

---

# 🎯 Expert-Level Claude Code Usage Guide

## Strategic Workflow Patterns

### 1. **Plan Mode for Complex Features**
- Use `/plan` (or EnterPlanMode) before implementing any multi-file feature
- Benefits: I explore the codebase, understand patterns, present an approach for your approval
- **When to use**: Any feature touching 3+ files, architectural decisions, or ambiguous requirements
- **When to skip**: Single-file tweaks, obvious bug fixes

### 2. **Task Lists for Progress Tracking**
- I'll proactively create task lists for complex work (you'll see checkboxes in the UI)
- You can see real-time progress as I mark tasks in_progress → completed
- **Pro tip**: Use `/tasks` command to view all tasks at any time

### 3. **Memory & Learning System**
- I have auto-memory in `~/.claude/projects/.../memory/`
- As we work, I'll save patterns, conventions, gotchas to `MEMORY.md`
- This persists across sessions - when you return tomorrow, I remember our conventions
- **Your job**: Tell me preferences explicitly ("always use async/await", "prefer composition over inheritance")

### 4. **Incremental Development Pattern**
```
Plan → Implement Minimal → Test → Learn → Document → Next Feature
```
- Never build everything then test
- Each session should produce working, tested code
- I'll update documentation as we go, not at the end

### 5. **Parallel Tool Execution**
- I can read multiple files, run multiple searches simultaneously
- When I need to understand a feature, I'll fan out reads in parallel
- **Your benefit**: Much faster exploration and implementation

### 6. **Git Integration Best Practices**
- I can create commits with `/commit` but ONLY when you ask
- Best practice: You review changes via `git diff`, then explicitly say "commit this"
- I'll write semantic commit messages following conventional commits style
- **Never**: Auto-committing or pushing without explicit approval

---

## 🚀 Session Management Strategies

### Start of Session
1. **Context loading**: Share what we're building today in one message
2. **Constraints first**: Tell me any non-negotiables (libraries, patterns, file structure)
3. **Success criteria**: Define "done" upfront ("runs without errors + passes manual test X")

### During Development
- **Interrupt me** if I'm going off-track - I can course-correct instantly
- **Ask for explanations**: "Why did you choose X?" forces me to justify decisions
- **Request alternatives**: "Show me 2 other ways to do this" for critical paths

### End of Session
- Ask me to summarize what we built and update documentation
- I'll note blockers, next steps, or open questions in memory files

---

## 📁 File Organization

```
book-lens/
├── src/                       # All application code
│   ├── main.py
│   ├── config.py
│   ├── ingestion/
│   ├── query/
│   ├── library/
│   └── static/
├── docs/
│   ├── progress/              # Phase completion reports
│   ├── learnings/             # Domain-specific insights
│   └── architecture/          # ADRs (Architecture Decision Records)
├── tests/
│   ├── integration/           # End-to-end testing scripts
│   └── manual/                # Manual test checklists
├── requirements.txt
└── .env.example
```

---

## 🔬 Testing Strategy

1. **Write testable code first**: Small functions, clear inputs/outputs
2. **Manual testing scripts**: Python scripts that exercise the code
3. **Validation before next phase**: Never move forward with broken code
4. **Test data**: Sample epub files for realistic testing

---

# 🗺️ Development Phases

## Philosophy
- **6-7 phases**, each ending with working, tested code
- **Each phase = 1-3 focused sessions**
- **Documentation updated live, not later**
- **No phase 2 until phase 1 works**

---

## Phase 1: Foundation + Epub Parsing
**Goal**: Parse a real epub into structured chapters

### Deliverables
- Project structure (folders, `config.py`, `.env.example`)
- `requirements.txt` with pinned versions
- `src/ingestion/epub_parser.py` with comprehensive edge case handling
- Manual test script that prints parsed chapters from a real epub
- Documentation: `docs/learnings/epub-parsing-gotchas.md`

### Validation Criteria
- [ ] Parse 2 different epub files successfully
- [ ] Handle edge cases: single-file epubs, missing titles, empty sections
- [ ] Output shows correct chapter count and labels

### Files Created/Modified
```
book-lens/
├── src/
│   ├── config.py
│   └── ingestion/
│       ├── __init__.py
│       └── epub_parser.py
├── tests/
│   └── manual/
│       └── test_epub_parser.py
├── requirements.txt
├── .env.example
├── .gitignore
└── docs/
    └── learnings/
        └── epub-parsing-gotchas.md
```

### Implementation Notes
- Use `ebooklib` + `beautifulsoup4` for parsing
- Extract chapters from spine in reading order
- Handle chapter labeling with fallbacks (h1/h2/h3 → class names → "Section N")
- Skip sections < 100 characters (copyright pages, etc.)

---

## Phase 2: Chunking Pipeline
**Goal**: Convert chapters → semantically meaningful chunks

### Deliverables
- `src/ingestion/chunker.py` with overlap logic
- Test script showing chunk distribution (word counts, overlap verification)
- Validation: no mid-sentence splits in random sample

### Validation Criteria
- [ ] Chunks average 350-450 words
- [ ] 50-word overlap verified between consecutive chunks
- [ ] Chapter metadata preserved in each chunk

### Documentation
- Update `docs/learnings/chunking-strategy.md` with findings on optimal sizes

### Implementation Notes
- Split on paragraph boundaries (`\n\n`)
- Greedy grouping until chunk_size reached
- Overlap: prepend last N words from previous chunk
- Return `ChunkRecord` dataclass with all metadata

---

## Phase 3: Vector Indexing (Qdrant)
**Goal**: Store chunks in Qdrant, verify retrieval

### Deliverables
- `src/ingestion/indexer.py`
- Qdrant cloud setup (free tier)
- Test: upload 1 book, verify vector count matches chunk count
- Test: re-upload same book, verify no duplicates (deletion of old points)

### Validation Criteria
- [ ] Qdrant collection created with correct dimensions (384 for MiniLM)
- [ ] Payloads include all metadata (series_id, book_index, chapter_index, text)
- [ ] Re-indexing clears old data first using filters

### Documentation
- `docs/architecture/decisions.md` - why Qdrant over alternatives
- `docs/learnings/qdrant-integration-notes.md` - gotchas, filter syntax

### Implementation Notes
- Initialize `SentenceTransformer('all-MiniLM-L6-v2')` at app startup
- Collection per series_id
- Before indexing: delete existing points for (series_id, book_index)
- Batch embed chunks (batch_size=64)
- Upsert in batches of 100

---

## Phase 4: Library Manager + Basic API
**Goal**: State management + minimal FastAPI to test ingestion end-to-end

### Deliverables
- `src/library/manager.py` with all CRUD functions
- `src/main.py` with:
  - `/library` (GET)
  - `/library/series` (POST)
  - `/library/series/{id}/books` (POST - upload epub)
- Manual test: Upload via `curl` or Postman, verify `library.json` updated

### Validation Criteria
- [ ] Upload epub → triggers parse → chunk → index → library update
- [ ] `library.json` persists state correctly
- [ ] Re-uploading same book works without errors
- [ ] Pydantic models validate all data

### Documentation
- `docs/progress/phase-4-completion.md` - what works, what's next

### Implementation Notes
- Pydantic models: `Library`, `Series`, `Book`, `Chapter`, `BookStatus`
- `library.json` stored at path from env var
- Read on every request, write on mutation (small file, acceptable)
- FastAPI startup: load SentenceTransformer, initialize Qdrant client
- Upload flow: save epub → parse → chunk → index → update library → save

---

## Phase 5: Query Engine
**Goal**: Ask questions, get spoiler-safe answers

### Deliverables
- `src/query/retriever.py` with chapter filtering logic
- `src/query/prompt_builder.py`
- `/query` (POST) endpoint
- Manual test: Mark Book 1 complete, ask about Book 2 → get "no info" response
- Manual test: Mark reading Book 1 Chapter 5, ask about Chapter 10 → get "no info"

### Validation Criteria
- [ ] Semantic search returns relevant chunks
- [ ] Filtering prevents future spoilers (NOT_STARTED excluded, READING filtered by chapter)
- [ ] Claude API integration works with test questions
- [ ] Prompt includes correct reading progress summary

### Documentation
- `docs/learnings/prompt-engineering-notes.md` - what works for spoiler prevention
- `docs/progress/phase-5-completion.md`

### Implementation Notes
- Build Qdrant filter from library state:
  - COMPLETED: include all chapters
  - READING: include chapters <= current_chapter_index
  - NOT_STARTED: exclude entirely
- Use `should` conditions (OR logic) for multiple books
- Embed question with same model as chunks
- Search with filter, return top_k chunks
- Build prompt with progress summary + context + question
- Call Claude Haiku 4.5, max_tokens=1024

---

## Phase 6: Frontend + Polish
**Goal**: Usable web interface

### Deliverables
- `src/static/index.html` - all 3 views (Library, Upload, Ask)
- Mobile-responsive design
- Progress indicators for uploads
- Error handling throughout

### Validation Criteria
- [ ] End-to-end flow works: upload → update progress → ask question → get answer
- [ ] Works on mobile viewport (375px)
- [ ] All error states handled gracefully
- [ ] Dark theme with book aesthetic

### Documentation
- `docs/progress/phase-6-completion.md` - final feature checklist
- `README.md` - user-facing setup guide

### Design Direction
- Dark theme: deep navy/near-black background, warm cream/parchment text
- Serif headings (Playfair Display), clean sans-serif body
- Minimal animations (subtle fade on view transitions)
- Mobile-first: stacked layout, large tap targets

### Views
1. **Library**: List series → books → status badges → update progress button
2. **Upload**: Series selector (new/existing) → book details → epub picker → progress bar
3. **Ask**: Series selector → reading state summary → textarea → answer card

---

## Phase 7: Deployment (Optional)
**Goal**: Deploy to Render, verify in production

### Deliverables
- `render.yaml`
- Production testing checklist
- Documentation for redeployment

### Notes
- Render free tier has ephemeral storage
- `library.json` and uploads wiped on redeploy (acceptable for V1)
- Future: migrate to persistent storage (Render disk, Supabase, PlanetScale)

---

# 🤝 How We'll Work Together

## Each Session Pattern
1. **You say**: "Let's work on Phase X"
2. **I'll**: Enter plan mode (if complex), explore needed files, propose approach
3. **You approve** or adjust
4. **I implement** incrementally, testing as I go
5. **We validate** together against phase criteria
6. **I document** learnings and update progress files
7. **You decide**: Continue to next piece, or end session

## When to Interrupt Me
- If I'm over-engineering (adding features not in plan)
- If I'm skipping tests
- If I'm making assumptions about your preferences

## What I Need From You
- **Real epub file(s)** for testing (any public domain book works)
- **Qdrant API key** when we hit Phase 3
- **Anthropic API key** when we hit Phase 5
- **Approval** before I write files or make architectural choices

---

# 📝 Documentation I'll Maintain

| File | Purpose | Updated When |
|------|---------|--------------|
| `~/.claude/.../memory/MEMORY.md` | Cross-session conventions, gotchas | As we learn patterns |
| `docs/progress/phase-N-completion.md` | What we built, what works, next steps | End of each phase |
| `docs/learnings/*.md` | Domain-specific insights (epub quirks, etc.) | When we hit edge cases |
| `docs/architecture/decisions.md` | Why we chose X over Y | When making tech choices |

---

# 🎬 Getting Started

**Recommended first step**:
> "Let's start Phase 1. Here's a sample epub file: [path or URL]"

I'll:
1. Enter plan mode
2. Set up project structure with src/ folder
3. Implement epub parser
4. Create test script
5. Validate against real epub
6. Document findings

**Or**, if you want to adjust the meta-plan first, let me know:
- Should we combine/split any phases?
- Different testing strategy?
- Specific coding standards to follow (PEP 8, Black formatting, type hints everywhere)?

---

# 📋 Phase Checklist

- [ ] Phase 1: Foundation + Epub Parsing
- [ ] Phase 2: Chunking Pipeline
- [ ] Phase 3: Vector Indexing (Qdrant)
- [ ] Phase 4: Library Manager + Basic API
- [ ] Phase 5: Query Engine
- [ ] Phase 6: Frontend + Polish
- [ ] Phase 7: Deployment (Optional)

---

*Last updated: 2026-04-11*
