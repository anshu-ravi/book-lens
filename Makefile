FRONTEND := web/frontend
PORT ?= 8000
HOST ?= 127.0.0.1

.PHONY: install dev serve build test clean

install: ## Python and frontend dependencies
	uv sync --extra dev
	cd $(FRONTEND) && npm install

dev: ## API with reload, plus the Vite dev server
	@trap 'kill 0' EXIT INT TERM; \
	uv run uvicorn booklens.web.app:app --host $(HOST) --port $(PORT) --reload & \
	(cd $(FRONTEND) && npm run dev) & \
	wait

serve: ## Serve the built SPA and API from one process
	uv run uvicorn booklens.web.app:app --host $(HOST) --port $(PORT)

build: ## Build the frontend
	cd $(FRONTEND) && npm run build

test: ## Run the test suite
	uv run pytest

clean: ## Remove build and cache artifacts (leaves data/ and uploads/ alone)
	rm -rf *.egg-info build dist .pytest_cache .ruff_cache $(FRONTEND)/build $(FRONTEND)/.svelte-kit
	find . -path ./$(FRONTEND)/node_modules -prune -o -name __pycache__ -type d -print0 | xargs -0 rm -rf
