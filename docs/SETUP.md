# BookLens Setup Guide

## Prerequisites

- Python 3.11+ 
- Poetry 2.x for dependency management
- Git

## Initial Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd book-lens
```

### 2. Set Python Version (if using pyenv)

```bash
pyenv local 3.11.14
```

### 3. Install Dependencies with Poetry

Poetry is configured to create a `.venv` folder in the project directory.

```bash
# Install all dependencies
poetry install

# Install only production dependencies (no dev tools)
poetry install --no-dev
```

### 4. Activate Virtual Environment

```bash
# Option 1: Use Poetry shell
poetry shell

# Option 2: Activate manually
source .venv/bin/activate  # On Unix/macOS
.venv\Scripts\activate     # On Windows
```

### 5. Configure Environment Variables

```bash
# Copy the example env file
cp .env.example .env

# Edit .env with your API keys
# - ANTHROPIC_API_KEY: Get from https://console.anthropic.com/
# - QDRANT_URL & QDRANT_API_KEY: Get from https://cloud.qdrant.io/ (free tier)
```

## Development Tools

### Code Formatting

```bash
# Format all code with Black
poetry run black src/ tests/

# Check formatting without changes
poetry run black --check src/ tests/
```

### Linting

```bash
# Run Ruff linter
poetry run ruff check src/ tests/

# Auto-fix issues
poetry run ruff check --fix src/ tests/
```

### Type Checking

```bash
# Run Mypy type checker
poetry run mypy src/
```

### Running Tests

```bash
# Run all tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=src tests/
```

## Adding New Dependencies

```bash
# Add a production dependency
poetry add package-name

# Add a development dependency
poetry add --group dev package-name

# Update all dependencies
poetry update
```

## Project Structure

```
book-lens/
├── .venv/                 # Virtual environment (created by Poetry)
├── src/                   # Application code
├── tests/                 # Test files
├── docs/                  # Documentation
├── pyproject.toml         # Poetry configuration & dependencies
├── poetry.lock            # Locked dependency versions
├── .env                   # Local environment variables (not in git)
└── .env.example           # Example environment variables
```


See [docs/meta-plan.md](meta-plan.md) for the development roadmap and phase-by-phase implementation guide.