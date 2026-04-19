from supabase import Client, create_client
from src.config import settings

def get_supabase_client() -> Client:
    """Returns an initialized Supabase client."""
    return create_client(settings.supabase_url, settings.supabase_key)
