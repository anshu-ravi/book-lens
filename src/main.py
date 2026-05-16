"""BookLens FastAPI application."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api import books, library, query
from src.config import settings

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env")

# Suppress verbose INFO logs that aren't actionable
logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise shared resources at startup."""
    yield


app = FastAPI(title="BookLens", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="src/static"), name="static")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    """Serve the frontend."""
    return FileResponse("src/static/index.html")


@app.get("/config")
async def get_config() -> dict:
    """Return public configuration for the frontend."""
    return {
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": settings.supabase_anon_key or settings.supabase_key,
    }


# Include routers
app.include_router(library.router)
app.include_router(books.router)
app.include_router(query.router)
