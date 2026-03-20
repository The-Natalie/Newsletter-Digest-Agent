# CLAUDE.md

## Project Overview

**Newsletter Digest Agent** — a personal web tool that reads newsletters from a user-designated IMAP folder, removes duplicate stories that appear across multiple sources, and produces a single consolidated digest via the Claude API. The user interacts entirely through a browser UI; all email credentials and backend configuration are set once by the developer.

Full requirements: `PRD.md`

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Database | SQLite via SQLAlchemy Core (async) + aiosqlite + Alembic |
| Email | IMAPClient, html2text, BeautifulSoup4 + lxml |
| AI / NLP | Anthropic SDK (`claude-haiku-4-5` default), sentence-transformers (`all-MiniLM-L6-v2`) |
| PDF export | weasyprint (primary), reportlab (fallback) |
| Frontend | Vanilla HTML/CSS/JS, Pico.css, marked.js (no build step) |
| Config | pydantic-settings, python-dotenv |

---

## Commands

```bash
# Run the development server
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Run the pipeline from the CLI (Phase 1 / debugging)
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-10 --end 2026-03-17

# Install dependencies
pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Create a new migration
alembic revision --autogenerate -m "description"
```

---

## Project Structure

```
newsletter-digest/
├── main.py              # FastAPI app factory, router registration, StaticFiles mount
├── config.py            # Pydantic BaseSettings — all env vars, validated at startup
├── database.py          # SQLAlchemy async engine, session factory
│
├── ingestion/
│   ├── imap_client.py   # IMAP connection, folder selection, UID search, batched fetch
│   └── email_parser.py  # MIME parsing, HTML→text, link extraction
│
├── processing/
│   ├── embedder.py      # sentence-transformers encoding + community_detection clustering
│   ├── deduplicator.py  # Cluster → merged story groups with combined source links
│   └── digest_builder.py # Orchestrates full pipeline end-to-end; returns digest JSON
│
├── ai/
│   └── claude_client.py # Anthropic SDK wrapper, prompt templates, tool-use schema
│
├── api/
│   ├── digests.py       # POST /api/digests/generate, GET /api/digests/latest
│   ├── export.py        # GET /api/digests/{id}/pdf
│   └── health.py        # GET /api/health
│
├── static/
│   ├── index.html       # Single-page frontend shell (Pico.css)
│   ├── style.css        # Custom overrides only
│   └── app.js           # All UI logic — state, form handling, fetch, rendering
│
├── data/digest.db       # SQLite database (gitignored)
├── alembic/             # Migrations
├── .env                 # Credentials (gitignored)
└── .env.example         # Template with all required keys
```

---

## Architecture

The system is a **linear synchronous pipeline**. Each stage receives output from the previous and passes results forward. The API exposes the pipeline via a single POST endpoint that runs it end-to-end and returns the completed digest.

```
IMAP → Ingestion → Extraction → Dedup → AI Generation → SQLite → HTTP Response → Frontend
```

The frontend POSTs a request, shows a loading state, and renders the digest when the response arrives.

---

## Key Patterns

### Pipeline
- `digest_builder.py` owns the full pipeline. It is called directly by the API route and returns completed digest JSON.
- Stages are independently testable: `ingestion/` knows nothing about AI; `processing/` knows nothing about IMAP.

### API Routes
- Routes validate input and delegate to `digest_builder`. No business logic in route handlers.
- The pipeline runs synchronously. No background tasks or SSE in MVP.

### Folder / Category
- The backend only knows about **folder names**. It receives a plain string from the request and passes it to the IMAP client.
- Preset shortcut buttons in the frontend are hardcoded HTML/JS convenience — they populate the folder input field. They have no backend representation.
- No `CATEGORIES` env var. No categories API endpoint.

### Deduplication
- Within-run only. Embeddings are computed in memory and discarded after the run.
- Threshold: `0.82` cosine similarity (configurable via `DEDUP_THRESHOLD` in `.env`).
- Model: `all-MiniLM-L6-v2` (22MB, CPU-compatible).

### AI Generation
- Default model: `claude-haiku-4-5`. Override via `CLAUDE_MODEL` in `.env`.
- All story clusters are batched into **one Claude API call** to minimize cost.
- Structured output via Claude tool use (not prompt-level JSON).
- Digest entry format: headline (max 12 words) + summary (2–4 sentences) + significance (1 sentence) + sources.

### Database
- MVP has one table: `digest_runs`. No story embeddings stored. No processed email tracking.
- Only the most recently completed digest is surfaced via `GET /api/digests/latest`.

### Frontend
- No framework, no build step. Edit `index.html`, `style.css`, `app.js` directly.
- Pico.css handles all form and layout styling via semantic HTML — avoid adding classes unless overriding.
- Digest output is rendered via `marked.js`. Do not use raw `innerHTML` for untrusted content.
- `localStorage` persists last-used folder name and date range across page loads.

### Email Ingestion
- Always select folders with `readonly=True` and fetch with `BODY.PEEK[]` — never modify mailbox state.
- Fetch emails in batches of 50.
- HTML-only emails are the default case; `text/plain` is a bonus. Always fall back to HTML.
- Pre-process HTML with BeautifulSoup (strip `<img>`, `<style>`, hidden pre-header text) before passing to `html2text`.

---

## Environment Variables

```bash
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USERNAME=user@example.com
IMAP_PASSWORD=your_app_password_here

ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-haiku-4-5

DATABASE_URL=sqlite+aiosqlite:///./data/digest.db
MAX_EMAILS_PER_RUN=50
DEDUP_THRESHOLD=0.82
HOST=0.0.0.0
PORT=8000
```

All required vars are validated at startup by `config.py`. Missing vars raise a clear error before the server starts.

---

## MVP Scope Boundaries

**Included in MVP:**
- Manual on-demand digest generation only (no scheduling)
- Display in browser only (no email delivery)
- Within-run deduplication only (no cross-run memory)
- Single folder per run
- Simple loading state (no SSE progress streaming)
- Most recent digest only (no history panel)

**Deferred to Phase 2:** SSE streaming, scheduling (APScheduler), email delivery (SMTP), cross-run dedup (persisted embeddings), multiple folders per run, multi-user support, OAuth2.

---

## Key Files

| File | Why it matters |
|---|---|
| `PRD.md` | Full product requirements, scope decisions, and rationale |
| `config.py` | All configuration; start here to understand env vars |
| `processing/digest_builder.py` | Entry point for the pipeline; orchestrates all stages |
| `ai/claude_client.py` | Prompt templates and tool-use schema for digest generation |
| `ingestion/email_parser.py` | HTML newsletter parsing; most likely source of extraction issues |
| `static/app.js` | All frontend behavior |
| `alembic/versions/` | DB migration history |

---

## On-Demand Context

Load these when working on specific areas — do not keep them always in context:

| Topic | Reference |
|---|---|
| Full feature specs and API schema | `PRD.md` §7, §10 |
| DB schema | `PRD.md` §15 (Appendix) |
| Implementation phases and validation criteria | `PRD.md` §12 |
| Risk mitigations (IMAP quirks, parsing, cost) | `PRD.md` §14 |
