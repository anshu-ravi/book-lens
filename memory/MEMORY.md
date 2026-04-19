# BookLens Project Memory

## Project Structure
- **All application code goes in `src/` folder** (not root)
- Documentation in `docs/` with subdirectories:
  - `docs/progress/` - phase completion reports
  - `docs/learnings/` - domain-specific insights
  - `docs/architecture/` - architecture decision records (ADRs)
- Tests in `tests/manual/` and `tests/integration/`

## Development Philosophy
- **Iterative development**: Build in phases, validate each phase before moving forward
- **Test as we go**: Never build multiple features then test - test each immediately
- **Document live**: Update docs during development, not after
- **No over-engineering**: Build only what's specified, no extra features

## Coding Standards & Tooling
- **Environment Manager**: Poetry (configured for local .venv)
- **Python Version**: 3.11.14 (managed via pyenv)
- **Formatter**: Black (line-length: 100, target: py311)
- **Linter**: Ruff (line-length: 100, target: py311)
- **Type Checker**: Mypy (strict mode: disallow_untyped_defs)
- **Type Hints**: Required on all functions
- **Async/await**: TBD (will establish as we build)
- **Docstring Style**: Google style (clean, readable, widely used)

## Phase Progress
- All 6 phases complete ✅
- Active branch: `feat/improvements` (22 commits ahead of `phase-1`)
- Completed phases:
  - Phase 1 (Foundation + Epub Parsing) ✅
  - Phase 2 (Chunking Pipeline) ✅
  - Phase 3 (Vector Indexing — Qdrant Cloud) ✅
  - Phase 4 (Library State + FastAPI REST API) ✅
  - Phase 5 (Spoiler-safe Query Engine) ✅
  - Phase 6 (Frontend SPA — Alpine.js) ✅

## Key Decisions
- Using `src/` directory for all application logic
- Following meta-plan with 6-7 distinct phases
- Each phase must pass validation criteria before proceeding
- **Epub Parsing**: Use XML parser (not lxml) for XHTML content
- **Epub Parsing**: Check image alt attributes for chapter titles (critical for many epubs)
- **Epub Parsing**: Filter sections < 100 chars to remove metadata pages
- **Epub Parsing**: Use separator="\n\n" in get_text() to preserve paragraph boundaries
- **Chunking**: 400 word target with 50 word overlap (86-94% hit rate across test books)
- **Chunking**: Paragraph-based greedy grouping (no mid-paragraph splits)

## Security Rules
- [Never read .env files](feedback_env_files.md) — use `.env.example` for variable names; never read files with actual secrets

---

For detailed phase breakdown and expert usage guide, see: `docs/meta-plan.md`

## Recent Improvements (feat/improvements branch)
- [Backend: Qdrant → Supabase migration](project_supabase_migration.md) — full infrastructure move
- [Frontend: Literary design system redesign](project_frontend_redesign.md) — new design + auth
- [Feature: Cover art extraction](project_cover_art.md) — epub cover + Open Library fallback
- [Feature: Enhanced query engine](project_query_engine.md) — classifier + entity context builder
