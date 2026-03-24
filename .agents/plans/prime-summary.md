# Prime Summary — Newsletter Digest Agent

**Generated:** 2026-03-20
**State:** Pre-implementation. Planning and configuration complete. No source code written yet.

---

## Project Overview

- **What it is:** A personal web tool that reads newsletters from a designated IMAP email folder, deduplicates overlapping stories across sources, and produces a consolidated digest via the Claude API.
- **User interaction:** Entirely through a browser UI — enter a folder name, set a date range, click Generate, view digest, download PDF.
- **Email credentials** are set once by the developer in `.env`; never exposed to the user.
- **Type:** Full-stack web app — Python/FastAPI backend + vanilla HTML/CSS/JS frontend.
- **Deployment target:** Single process (`uvicorn`), deployable to a VPS or locally. Docker support planned in Phase 3.
- **Audience:** Portfolio-presentable personal productivity tool.

---

## Architecture

**Pattern:** Linear synchronous pipeline. One HTTP request triggers the full pipeline and returns the completed digest.

```
IMAP → Ingestion → Extraction → Dedup → AI Generation → SQLite → HTTP Response → Frontend
```

- No background tasks, no SSE, no task queues in MVP.
- Frontend shows a loading state while the synchronous request is in flight.
- The backend receives only a folder name string — no category concept exists in the backend.
- Preset shortcut buttons in the frontend are hardcoded HTML/JS; they populate the folder input and have no backend representation.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Database | SQLite + SQLAlchemy Core (async) + aiosqlite + Alembic |
| Email | IMAPClient, html2text, BeautifulSoup4 + lxml |
| AI / NLP | Anthropic SDK (`claude-haiku-4-5`), sentence-transformers (`all-MiniLM-L6-v2`) |
| PDF | weasyprint (primary), reportlab (fallback) |
| Frontend | Vanilla HTML/CSS/JS, Pico.css, marked.js — no build step |
| Config | pydantic-settings, python-dotenv |

---

## Planned Directory Structure

```
newsletter-digest/
├── main.py                  # FastAPI app factory
├── config.py                # Pydantic BaseSettings, all env vars
├── database.py              # SQLAlchemy async engine
├── ingestion/
│   ├── imap_client.py       # IMAP connect, folder select, fetch
│   └── email_parser.py      # MIME parse, HTML→text, link extract
├── processing/
│   ├── embedder.py          # sentence-transformers + community_detection
│   ├── deduplicator.py      # clusters → merged story groups
│   └── digest_builder.py    # pipeline orchestrator (main entry point)
├── ai/
│   └── claude_client.py     # Anthropic SDK, prompts, tool-use schema
├── api/
│   ├── digests.py           # POST /api/digests/generate, GET /api/digests/latest
│   ├── export.py            # GET /api/digests/{id}/pdf
│   └── health.py            # GET /api/health
├── static/
│   ├── index.html           # Single-page shell
│   ├── style.css            # Pico.css overrides
│   └── app.js               # All UI logic
├── data/digest.db           # SQLite (gitignored)
└── alembic/                 # Migrations
```

---

## Key Patterns to Preserve

- **Thin routes:** No business logic in API handlers — delegate to `digest_builder`.
- **Synchronous pipeline:** `digest_builder.py` returns completed JSON; no async streaming in MVP.
- **Folder name only:** Backend has no category concept. The `folder` param is passed through unchanged.
- **Within-run dedup only:** Embeddings are in-memory per run, discarded after. No DB persistence of embeddings.
- **Single active digest:** DB stores only the most recently completed digest.
- **Read-only IMAP:** Always `readonly=True` + `BODY.PEEK[]`. Never modify mailbox state.
- **Batch to one API call:** All story clusters go to Claude in a single call to minimize cost.
- **Claude tool use:** Structured output via function calling, not prompt-level JSON.

---

## MVP Scope Boundary

**In:** Manual on-demand generation · Single folder per run · Within-run dedup · Browser display · PDF download · Simple loading state

**Out (Phase 2):** SSE progress streaming · Scheduling · Email delivery · Cross-run dedup · Multiple folders per run · Multi-user · OAuth2 · Digest history

---

## Current File State

| File | Status |
|---|---|
| `PRD.md` | Complete — source of truth for all product decisions |
| `CLAUDE.md` | Complete — project rules and key patterns |
| `.env.example` | Complete — all vars with placeholder values and comments |
| `.env` | Created — identical to `.env.example`; needs real credentials filled in |
| `.gitignore` | Complete — covers `.env`, `data/`, Python bytecode |
| All source code | **Not yet written** |

---

## Environment Variables

```
IMAP_HOST, IMAP_PORT, IMAP_USERNAME, IMAP_PASSWORD
ANTHROPIC_API_KEY, CLAUDE_MODEL (claude-haiku-4-5)
MAX_EMAILS_PER_RUN (50), DEDUP_THRESHOLD (0.82)
DATABASE_URL, HOST, PORT
```

All validated at startup by `config.py` (Pydantic BaseSettings).

---

## Database Schema (MVP — one table only)

```sql
CREATE TABLE digest_runs (
    id            TEXT PRIMARY KEY,
    run_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    folder        TEXT NOT NULL,
    date_start    DATE,
    date_end      DATE,
    story_count   INTEGER DEFAULT 0,
    status        TEXT DEFAULT 'pending',  -- pending|in_progress|complete|failed
    error_message TEXT,
    output_json   TEXT
);
```

No story embeddings stored. No processed email tracking. Cross-run state deferred to Phase 2.

---

## Implementation Phases

| Phase | Goal | Status |
|---|---|---|
| 1 | Core pipeline as CLI script — `digest_builder.py` runnable end-to-end | **Next** |
| 2 | Wrap pipeline in FastAPI — `POST /api/digests/generate` returns digest JSON | Pending |
| 3 | Frontend + PDF export — browser UI, Pico.css, marked.js, weasyprint | Pending |
| 4 | Polish + deployment — error states, empty states, README, Dockerfile | Pending |

---

## Recommended Starting Point

**Begin with Phase 1: Core Pipeline**

Build and validate in this order:
1. `config.py` — Pydantic BaseSettings, env loading
2. `database.py` + Alembic baseline migration (`digest_runs` table)
3. `ingestion/imap_client.py` — IMAP connect, folder select, date search, batched fetch
4. `ingestion/email_parser.py` — MIME parse, BeautifulSoup pre-process, html2text
5. `processing/embedder.py` — sentence-transformers encode + `community_detection`
6. `processing/deduplicator.py` — clusters → merged groups with source links
7. `ai/claude_client.py` — batched multi-cluster prompt, tool-use schema
8. `processing/digest_builder.py` — pipeline orchestrator, CLI entry point

**Validation gate:** Run against a real newsletter folder. Confirm at least one merged story entry with source links from two different newsletters.

---

## Files to Consult Before Implementation

| Topic | File |
|---|---|
| All feature specs | `PRD.md` §7 |
| API request/response schema | `PRD.md` §10 |
| DB schema | `PRD.md` §15 (Appendix) |
| Phase deliverables + validation | `PRD.md` §12 |
| Risk mitigations (IMAP quirks, parsing, cost) | `PRD.md` §14 |
| Key patterns and env vars | `CLAUDE.md` |
