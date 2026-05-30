from supabase import Client, create_client
from backend.config import settings

_client: Client | None = None


def get_supabase_client() -> Client:
    """Returns a shared Supabase client, initializing it on first call."""
    global _client
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_key)
    return _client
