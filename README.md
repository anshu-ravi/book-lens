---
title: BookLens
emoji: 📚
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
---

# BookLens 📚

A single-user, spoiler-safe reading companion web app. Upload epubs, track reading progress by chapter, and ask natural language questions—the system only answers using content from chapters you've already read.

## 🎯 Core Features

- **Epub Ingestion**: Upload epub files, automatically parse and index chapters
- **Series Management**: Organize books into series or track as standalones
- **Progress Tracking**: Mark current chapter, track completion by book
- **Spoiler-Safe Q&A**: Ask questions about the story—only get answers from chapters you've read
- **Natural Language Search**: Semantic search powered by embeddings + LLM

## 🏗️ Tech Stack

| Layer | Choice |
|---|---|
| Backend | FastAPI (Python) |
| Epub Parsing | `ebooklib` + `beautifulsoup4` |
| Embeddings | `sentence-transformers` (all-MiniLM-L6-v2) |
| Vector DB | Qdrant Cloud (free tier) |
| LLM | Claude API (claude-haiku-4-5) |
| Frontend | Vanilla HTML/CSS/JS (single file) |
| State | JSON file on disk |
| Hosting | Render.com (free tier) |

## 📁 Project Structure

```
book-lens/
├── src/                    # All application code
│   ├── main.py            # FastAPI entry point
│   ├── config.py          # Environment configuration
│   ├── ingestion/         # Epub parsing, chunking, indexing
│   ├── query/             # Retrieval + prompt building
│   ├── library/           # Library state management
│   └── static/            # Frontend HTML/CSS/JS
├── docs/
│   ├── meta-plan.md       # Development roadmap
│   ├── progress/          # Phase completion reports
│   ├── learnings/         # Domain-specific insights
│   └── architecture/      # Architecture decision records
├── tests/
│   ├── manual/            # Manual test scripts
│   └── integration/       # End-to-end tests
├── requirements.txt
└── .env.example
```

## 🚀 Development Approach

This project is being built **iteratively in phases** following industry best practices:

1. **Phase 1**: Foundation + Epub Parsing
2. **Phase 2**: Chunking Pipeline
3. **Phase 3**: Vector Indexing (Qdrant)
4. **Phase 4**: Library Manager + Basic API
5. **Phase 5**: Query Engine
6. **Phase 6**: Frontend + Polish
7. **Phase 7**: Deployment (Optional)

Each phase includes:
- ✅ Working, tested code
- ✅ Validation against criteria
- ✅ Documentation of learnings
- ✅ No progression until current phase works

**See [docs/meta-plan.md](docs/meta-plan.md) for the complete development roadmap.**

## 📖 Documentation

- **[Meta-Plan](docs/meta-plan.md)**: Complete development roadmap and expert usage guide
- **[Implementation Plan](docs/booklens_implementation_plan.md)**: Original detailed technical specification
- **[Progress Reports](docs/progress/)**: Phase-by-phase completion status
- **[Learnings](docs/learnings/)**: Domain-specific insights and gotchas
- **[Architecture](docs/architecture/)**: Technical decision records

## 🛠️ Setup

### Quick Start

```bash
# 1. Set Python version (if using pyenv)
pyenv local 3.11.14

# 2. Install dependencies with Poetry
poetry install

# 3. Activate virtual environment
poetry shell

# 4. Copy and configure environment variables
cp .env.example .env
# Edit .env with your API keys
```

**See [docs/SETUP.md](docs/SETUP.md) for detailed setup instructions.**

### Development Tools

- **Formatter**: Black (line-length: 100)
- **Linter**: Ruff
- **Type Checker**: Mypy (strict mode enabled)

```bash
poetry run black src/      # Format code
poetry run ruff check src/ # Lint code
poetry run mypy src/       # Type check
```

## 📊 Current Status

**Phase**: Not started
**Last Updated**: 2026-04-11

Check [docs/progress/](docs/progress/) for detailed phase completion reports.

---

*Built with Claude Code following iterative development best practices.*
