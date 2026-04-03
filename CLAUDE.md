# CLAUDE.md

## Project Overview

**Newsletter Digest Agent** — a personal web tool that reads newsletters from a user-designated IMAP folder, removes duplicate stories that appear across multiple sources, and surfaces a deduplicated list of story items. The user interacts entirely through a browser UI; all email credentials and backend configuration are set once by the developer.

Full requirements: `PRD.md`

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Database | SQLite via SQLAlchemy Core (async) + aiosqlite + Alembic |
| Email | IMAPClient, html2text, BeautifulSoup4 + lxml |
| AI / NLP | Anthropic SDK (`claude-haiku-4-5` default, binary filter only), sentence-transformers (`all-MiniLM-L6-v2`) |
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
│   └── email_parser.py  # MIME parsing, HTML→text, story segmentation, link + date extraction
│
├── processing/
│   ├── embedder.py      # sentence-transformers encoding + community_detection clustering
│   ├── deduplicator.py  # Cluster → representative story item selection
│   └── digest_builder.py # Orchestrates full pipeline end-to-end; returns story list JSON
│
├── ai/
│   └── claude_client.py # Anthropic SDK — binary keep/drop filter (not generation)
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

The system is a **linear synchronous pipeline**. Each stage receives output from the previous and passes results forward. The API exposes the pipeline via a single POST endpoint that runs it end-to-end and returns the completed story list.

```
IMAP → Ingestion → Extraction → Logic Filter → Embed/Cluster → Select Representative → LLM Filter → SQLite → HTTP Response → Frontend
```

The frontend POSTs a request, shows a loading state, and renders the story list when the response arrives.

---

## Key Patterns

### Pipeline
- `digest_builder.py` owns the full pipeline. It is called directly by the API route and returns completed story list JSON.
- Stages are independently testable: `ingestion/` knows nothing about AI; `processing/` knows nothing about IMAP.
- The pipeline **selects and filters** — it does not rewrite, summarize, or generate content. All story text comes from the original newsletter.

### API Routes
- Routes validate input and delegate to `digest_builder`. No business logic in route handlers.
- The pipeline runs synchronously. No background tasks or SSE in MVP.

### Folder / Category
- The backend only knows about **folder names**. It receives a plain string from the request and passes it to the IMAP client.
- Preset shortcut buttons in the frontend are hardcoded HTML/JS convenience — they populate the folder input field. They have no backend representation.
- No `CATEGORIES` env var. No categories API endpoint.

### Story Record Shape
Each extracted story item is a plain dict:
```python
{
    "title": str | None,      # first heading/line, may be absent
    "body": str,              # extracted body text
    "link": str | None,       # first substantive URL, may be absent
    "newsletter": str,        # sender name
    "date": str,              # YYYY-MM-DD (email received date)
}
```
Title and link are optional — untitled and link-free items are valid and must not be dropped.

### Logic Filter
- Removes obvious boilerplate/housekeeping sections (unsubscribe footers, navigation blocks, pure CTA sections).
- **Never filters by body length.** Short items (one sentence, a few words plus a link) are valid stories and must be preserved.
- When in doubt, preserve the item. False positives are caught by the LLM filter; false negatives are unrecoverable.

### Deduplication
- Within-run only. Embeddings are computed in memory and discarded after the run.
- **Dedup signal: body text** — not title, not link. Two items describe the same story when their body text is semantically similar.
- Threshold: `0.78` cosine similarity (configurable via `DEDUP_THRESHOLD` in `.env`).
- Model: `all-MiniLM-L6-v2` (22MB, CPU-compatible).
- All items from the full date range are pooled into one pass. Same story on different dates within a run → keep earliest date.
- **Representative selection** (in priority order): longest body → has title → real content URL.

### LLM Filter
- Default model: `claude-haiku-4-5`. Override via `CLAUDE_MODEL` in `.env`.
- Binary **keep/drop** judgment only — no generation, no rewriting.
- Drops navigation sections, housekeeping noise, and content-free items the logic filter missed.
- Never drops short valid stories. Uncertainty defaults to KEEP.

**Development-only flagging (no effect on production output or user-facing behavior):**
- Any item the LLM marks as `"borderline"` confidence is written to `data/flags_latest.jsonl` (overwritten each run).
- Each line is one JSON object: `{"decision": "KEEP"|"DROP", "confidence": "borderline", "llm_reasoning": "...", "item": {title, body, link, newsletter, date}}`.
- At end of each run, `digest_builder.py` prints a one-line summary to stdout: `Pipeline complete: N kept, N dropped, N flagged as borderline. Flagged records written to data/flags_latest.jsonl`.
- The flags file is never included in API responses and has no effect on the story list returned to the frontend.
- Review workflow: `cat data/flags_latest.jsonl | python -m json.tool` after a run. Borderline cases feed back into development by: (1) adjusting the filter prompt, (2) tightening the logic filter rules, or (3) adding the item as a test case in `tests/test_llm_filter.py`.

### Database
- MVP has one table: `digest_runs`. No story embeddings stored. No processed email tracking.
- Only the most recently completed digest is surfaced via `GET /api/digests/latest`.

### Frontend
- No framework, no build step. Edit `index.html`, `style.css`, `app.js` directly.
- Pico.css handles all form and layout styling via semantic HTML — avoid adding classes unless overriding.
- Story list output is rendered via `marked.js`. Do not use raw `innerHTML` for untrusted content.
- `localStorage` persists last-used folder name and date range across page loads.
- Story items render with: title (or untitled placeholder), body text, source newsletter, date, and link.

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
DEDUP_THRESHOLD=0.78
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
- Extracted story text only — no AI-generated summaries, headlines, or significance lines

**Deferred to Phase 2:** SSE streaming, scheduling (APScheduler), email delivery (SMTP), cross-run dedup (persisted embeddings), multiple folders per run, multi-user support, OAuth2.

---

## Key Files

| File | Why it matters |
|---|---|
| `PRD.md` | Full product requirements, scope decisions, and rationale |
| `config.py` | All configuration; start here to understand env vars |
| `processing/digest_builder.py` | Entry point for the pipeline; orchestrates all stages |
| `ai/claude_client.py` | Binary keep/drop filter — Claude API call and tool-use schema |
| `ingestion/email_parser.py` | HTML newsletter parsing and story segmentation; most likely source of extraction issues |
| `static/app.js` | All frontend behavior |
| `alembic/versions/` | DB migration history |
| `data/flags_latest.jsonl` | Development artifact — borderline LLM filter decisions from the most recent run; overwritten each run; not versioned |

---

## On-Demand Context

Load these when working on specific areas — do not keep them always in context:

| Topic | Reference |
|---|---|
| Full feature specs and API schema | `PRD.md` §7, §10 |
| Story item output shape | `PRD.md` §10 (stories array) |
| DB schema | `PRD.md` §15 (Appendix) |
| Implementation phases and validation criteria | `PRD.md` §12 |
| Risk mitigations (IMAP quirks, parsing, cost) | `PRD.md` §14 |
