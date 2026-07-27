import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or os.getenv("SUPABASE_KEY")
)

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "Supabase URL and anon/service role key must be set in environment variables. "
        "Copy .env.example to .env and set SUPABASE_URL plus SUPABASE_ANON_KEY or SUPABASE_SERVICE_ROLE_KEY."
    )

supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
