# Phase 1, Task 1: `config.py`

## Goal

Create `config.py` — Pydantic BaseSettings that loads all env vars from `.env` and validates required fields at startup.

**Read first:** `.env.example` (all var names and defaults)

---

## Task

### CREATE `config.py`

`pydantic_settings.BaseSettings` subclass with `SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")`.

Fields:
- `imap_host: str` — required
- `imap_port: int = 993`
- `imap_username: str` — required
- `imap_password: str` — required
- `anthropic_api_key: str` — required
- `claude_model: str = "claude-haiku-4-5"`
- `max_emails_per_run: int = 50`
- `dedup_threshold: float = 0.82`
- `database_url: str = "sqlite+aiosqlite:///./data/digest.db"`
- `host: str = "0.0.0.0"`
- `port: int = 8000`

Instantiate `settings = Settings()` at module level.

- **GOTCHA:** Missing required fields raise `ValidationError` at import time — intentional fail-fast behavior.
- **GOTCHA:** Install `pydantic-settings` separately from `pydantic` — it is a distinct package.

---

## Validation

```bash
python -c "from config import settings; print(settings.imap_host, settings.claude_model)"
```

Expected: prints the values from `.env` without error.
