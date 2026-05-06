import os
import sys

# Temporary debug: print env vars Railway is injecting
_relevant = {k: v[:4] + "..." for k, v in os.environ.items()
             if any(x in k.upper() for x in ("IMAP", "ANTHROPIC", "CLAUDE", "DATABASE"))}
print(f"DEBUG env vars visible at startup: {_relevant}", file=sys.stderr, flush=True)

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # IMAP
    imap_host: str
    imap_port: int = 993
    imap_username: str
    imap_password: str

    # Claude API
    anthropic_api_key: str
    claude_model: str = "claude-haiku-4-5"

    # Pipeline tuning
    max_emails_per_run: int = 50
    dedup_threshold: float = 0.55

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/digest.db"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()
