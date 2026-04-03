# Prime Summary — Newsletter Digest Agent

**Generated:** 2026-04-01
**State:** Architecture redesign complete. PRD and CLAUDE.md updated. Significant code exists but reflects the old generation-based architecture and must be rewritten.

---

## Project Overview

- **What it is:** A personal web tool that reads newsletters from a designated IMAP email folder, deduplicates overlapping stories across sources, and surfaces a deduplicated list of story items — preserving the original extracted text, not generating summaries.
- **User interaction:** Entirely through a browser UI — enter a folder name, set a date range, click Generate, view story list, download PDF.
- **Email credentials** are set once by the developer in `.env`; never exposed to the user.
- **Type:** Full-stack web app — Python/FastAPI backend + vanilla HTML/CSS/JS frontend.
- **Deployment target:** Single process (`uvicorn`), deployable to a VPS or locally. Docker support planned in Phase 3.
- **Audience:** Portfolio-presentable personal productivity tool.

---

## Architecture

**Pattern:** Linear synchronous pipeline. One HTTP request triggers the full pipeline and returns the completed story list.

```
IMAP → Ingestion → Extraction → Logic Filter → Embed/Cluster → Select Representative → LLM Filter → SQLite → HTTP Response → Frontend
```

**Key distinctions from prior architecture:**
- **No AI generation.** The pipeline extracts and selects — it does not rewrite, summarize, or produce headline/summary/significance fields.
- **No `story_reviewer.py`.** Pre-generation KEEP/DROP classification is gone. The LLM filter now runs *after* deduplication, on the final representative items, as a lightweight binary pass.
- **Dedup signal is body text**, not title + first sentences. Semantic similarity on extracted body content drives clustering.
- **Representative selection** replaces merged source attribution: from each cluster, one item is chosen — longest body → has title → real content URL.
- **Output is one item per cluster**: `{title, body, link, newsletter, date}`. Title and link are nullable. No generated content.
- **LLM Filter** is a binary keep/drop pass on deduplicated items using `claude-haiku-4-5`. It runs after representative selection and removes navigation sections, housekeeping noise, or content-free items that the logic filter missed. Never drops short valid stories. Uncertainty defaults to KEEP.

No background tasks, no SSE, no task queues in MVP.
The backend receives only a folder name string — no category concept exists in the backend.
Preset shortcut buttons in the frontend are hardcoded HTML/JS; they populate the folder input and have no backend representation.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Database | SQLite + SQLAlchemy Core (async) + aiosqlite + Alembic |
| Email | IMAPClient, html2text, BeautifulSoup4 + lxml |
| AI / NLP | Anthropic SDK (`claude-haiku-4-5`, binary filter only), sentence-transformers (`all-MiniLM-L6-v2`) |
| PDF | weasyprint (primary), reportlab (fallback) |
| Frontend | Vanilla HTML/CSS/JS, Pico.css, marked.js — no build step |
| Config | pydantic-settings, python-dotenv |

---

## Directory Structure

```
newsletter-digest/
├── main.py                  # FastAPI app factory
├── config.py                # Pydantic BaseSettings, all env vars
├── database.py              # SQLAlchemy async engine
├── ingestion/
│   ├── imap_client.py       # IMAP connect, folder select, fetch  ✅ no changes needed
│   └── email_parser.py      # MIME parse, HTML→text, story segmentation, link + date extract  ⚠️ needs story segmentation + date
├── processing/
│   ├── embedder.py          # sentence-transformers + community_detection  ✅ no changes needed
│   ├── deduplicator.py      # clusters → representative story item selection  ⚠️ needs rewrite (old: merged groups + source attribution)
│   └── digest_builder.py    # pipeline orchestrator (main entry point)  ⚠️ needs rewrite (new stages)
├── ai/
│   ├── story_reviewer.py    # ❌ DELETE — no longer part of architecture
│   └── claude_client.py     # Binary keep/drop filter  ⚠️ needs rewrite (old: generation + batching)
├── api/
│   ├── digests.py           # POST /api/digests/generate, GET /api/digests/latest
│   ├── export.py            # GET /api/digests/{id}/pdf
│   └── health.py            # GET /api/health
├── static/
│   ├── index.html           # Single-page shell
│   ├── style.css            # Pico.css overrides
│   └── app.js               # All UI logic  ⚠️ needs update (new story item shape)
├── tests/
│   ├── test_deduplicator.py # ⚠️ needs update (some tests still valid, representative selection tests needed)
│   ├── test_claude_client.py # ⚠️ needs rewrite (old tests cover generation, not filter)
│   ├── test_story_reviewer.py # ❌ DELETE — story_reviewer.py is removed
│   └── test_email_parser.py # ⚠️ needs additions (story segmentation, date extraction)
├── scripts/
│   └── inspect_clusters.py  # Diagnostic — runs pipeline through dedup, shows cluster details
├── data/digest.db           # SQLite (gitignored)
├── data/flags_latest.jsonl  # Dev artifact — borderline LLM filter decisions, overwritten each run (gitignored)
└── alembic/                 # Migrations  ✅ no changes needed
```

---

## Key Patterns to Preserve

- **Thin routes:** No business logic in API handlers — delegate to `digest_builder`.
- **Synchronous pipeline:** `digest_builder.py` returns completed JSON; no async streaming in MVP.
- **Folder name only:** Backend has no category concept. The `folder` param is passed through unchanged.
- **Within-run dedup only:** Embeddings are in-memory per run, discarded after. No DB persistence of embeddings.
- **Single active digest:** DB stores only the most recently completed digest.
- **Read-only IMAP:** Always `readonly=True` + `BODY.PEEK[]`. Never modify mailbox state.
- **Logic filter — never drop by length:** Short items (one sentence, a few words plus a link) are valid stories. Preserve when uncertain; downstream LLM filter is the safety net.
- **Representative selection order:** Longest body → has title → real content URL. Cross-date: keep earliest date in cluster.
- **LLM filter — binary only:** No generation. Uncertainty defaults to KEEP. Never drops short valid stories.
- **Dev flagging:** Borderline LLM decisions written to `data/flags_latest.jsonl` (overwritten each run). End-of-run console summary: `Pipeline complete: N kept, N dropped, N flagged as borderline.` No effect on API response or user-facing output.

---

## Story Record Shape

Each pipeline stage passes story items as plain dicts:

```python
{
    "title": str | None,   # first heading/line, may be absent — untitled items are valid
    "body": str,           # extracted body text — primary dedup signal
    "link": str | None,    # first substantive URL, may be absent
    "newsletter": str,     # sender name
    "date": str,           # YYYY-MM-DD; for deduplicated clusters, earliest date in cluster
}
```

---

## MVP Scope Boundary

**In:** Manual on-demand generation · Single folder per run · Within-run dedup (body-text signal) · Logic filter (no length filtering) · Representative selection · LLM binary filter · Dev flagging to `flags_latest.jsonl` · Browser display · PDF download · Simple loading state

**Out (Phase 2):** SSE progress streaming · Scheduling · Email delivery · Cross-run dedup · Multiple folders per run · Multi-user · OAuth2 · Digest history

---

## Current File State

| File | Status |
|---|---|
| `PRD.md` | ✅ Updated to v2.0 — source of truth for new architecture |
| `CLAUDE.md` | ✅ Updated — reflects new pipeline, patterns, and dev flagging |
| `.env.example` | ✅ Complete |
| `config.py` | ✅ No changes needed |
| `database.py` | ✅ No changes needed |
| `alembic/` | ✅ No changes needed |
| `ingestion/imap_client.py` | ✅ No changes needed |
| `ingestion/email_parser.py` | ⚠️ Needs story segmentation and date extraction added |
| `processing/embedder.py` | ✅ No changes needed (clustering logic is unchanged) |
| `processing/deduplicator.py` | ⚠️ Needs rewrite — old logic: merged groups + source attribution; new: representative selection |
| `processing/digest_builder.py` | ⚠️ Needs rewrite — new pipeline stages, new output shape |
| `ai/claude_client.py` | ⚠️ Needs rewrite — old: batched generation + tool schema; new: binary keep/drop filter |
| `ai/story_reviewer.py` | ❌ Delete — no longer part of architecture |
| `tests/test_deduplicator.py` | ⚠️ Needs update — CTA and scoring tests still valid; representative selection tests needed |
| `tests/test_claude_client.py` | ⚠️ Needs rewrite — old tests cover generation; new tests cover binary filter |
| `tests/test_story_reviewer.py` | ❌ Delete — story_reviewer.py is removed |
| `tests/test_email_parser.py` | ⚠️ Needs additions for story segmentation and date extraction |
| `api/` (all routes) | ⚠️ Needs update — response schema changes (new story item shape) |
| `static/app.js` | ⚠️ Needs update — render new story item shape (title/body/link/date/newsletter) |

---

## Environment Variables

```
IMAP_HOST, IMAP_PORT, IMAP_USERNAME, IMAP_PASSWORD
ANTHROPIC_API_KEY, CLAUDE_MODEL (claude-haiku-4-5)
MAX_EMAILS_PER_RUN (50), DEDUP_THRESHOLD (0.78)
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
    output_json   TEXT                     -- full story list as JSON string
);
```

No story embeddings stored. No processed email tracking. Cross-run state deferred to Phase 2.

---

## Implementation Phases

| Phase | Goal | Status |
|---|---|---|
| 1 | Core pipeline as CLI script — `digest_builder.py` runnable end-to-end with new architecture | **Next** |
| 2 | Wrap pipeline in FastAPI — `POST /api/digests/generate` returns story list JSON | Pending |
| 3 | Frontend + PDF export — render new story item shape, Pico.css, marked.js, weasyprint | Pending |
| 4 | Polish + deployment — error states, empty states, README, Dockerfile | Pending |

---

## Recommended Rewrite Order (Phase 1)

Build and validate in this order. Earlier steps have no dependency on later steps.

1. `ingestion/email_parser.py` — add story segmentation (blank-line / HR heuristics) and date extraction; output `{title, body, link, newsletter, date}` records
2. `processing/deduplicator.py` — rewrite for representative selection from clusters; keep existing CTA/scoring logic where still useful for link selection
3. `ai/claude_client.py` — rewrite as binary keep/drop filter with dev flagging to `data/flags_latest.jsonl`
4. `processing/digest_builder.py` — rewrite pipeline to: ingest → extract → logic filter → embed/cluster → select representative → LLM filter → sort by date → store
5. Delete `ai/story_reviewer.py` and `tests/test_story_reviewer.py`
6. Update tests to match new behavior

**Validation gate:** Run against a real newsletter folder. Confirm: (1) at least one near-duplicate pair is merged into one item, (2) no valid short story is dropped, (3) output items have `title/body/link/newsletter/date` shape, sorted oldest-first.

---

## Files to Consult Before Implementation

| Topic | File |
|---|---|
| All feature specs | `PRD.md` §7 |
| Story item output shape | `PRD.md` §10 (stories array) |
| DB schema | `PRD.md` §15 (Appendix) |
| Phase deliverables + validation | `PRD.md` §12 |
| Risk mitigations | `PRD.md` §14 |
| Key patterns, story record shape, dev flagging | `CLAUDE.md` |
