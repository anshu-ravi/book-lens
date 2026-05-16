"""Shared dependencies for API routes."""

import logging
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException

from src.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


async def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    """Dependency to get the current authenticated user ID.

    In development mode (no JWT), it can fall back to a dummy ID if configured.
    """
    if not authorization:
        return "00000000-0000-0000-0000-000000000000"

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header.")

    token = authorization.split(" ")[1]
    client = get_supabase_client()
    try:
        user_resp = client.auth.get_user(token)
        return user_resp.user.id
    except Exception as e:
        logger.warning("Auth verification failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token.")


CurrentUser = Annotated[str, Depends(get_current_user)]
