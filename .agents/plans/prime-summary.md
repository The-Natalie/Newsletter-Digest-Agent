# Prime Summary — Newsletter Digest Agent

**Generated:** 2026-04-07
**State:** Phase 1 pipeline complete and passing (114/114 tests). Three-stage LLM pipeline: pre-cluster noise filter, pairwise dedup refinement, editorial filter. All core files implemented.

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
IMAP → Ingestion → Extraction → LLM Noise Filter → Embed/Cluster → LLM Pairwise Dedup Refinement → Select Representative → LLM Editorial Filter → SQLite → HTTP Response → Frontend
```

**Key distinctions from prior architecture:**
- **No AI generation.** The pipeline extracts and selects — it does not rewrite, summarize, or produce headline/summary/significance fields.
- **No `story_reviewer.py`.** Pre-generation KEEP/DROP classification is gone. Three separate LLM passes now serve distinct roles (see below).
- **Dedup signal is body text**, not title + first sentences. Semantic similarity on extracted body content drives clustering.
- **Representative selection** replaces merged source attribution: from each cluster, one item is chosen — longest body → has title → real content URL.
- **Output is one item per cluster**: `{title, body, link, newsletter, date}`. Title and link are nullable. No generated content.
- **Three LLM passes** (all `claude-haiku-4-5`, all fail-open, all in `ai/claude_client.py`):
  1. `filter_noise` — pre-cluster; removes structural non-article content (sponsor blocks, CTAs, intros/outros). Maximally conservative.
  2. `refine_clusters` — within embedding clusters; pairwise three-way classification (`same_story` / `related_but_distinct` / `different`); union-find merging.
  3. `filter_stories` — post-representative-selection; binary keep/drop editorial quality pass.

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
| AI / NLP | Anthropic SDK (`claude-haiku-4-5`, three LLM passes: noise filter + pairwise dedup refinement + editorial filter), sentence-transformers (`all-MiniLM-L6-v2`) |
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
│   ├── imap_client.py       # IMAP connect, folder select, fetch  ✅ complete
│   └── email_parser.py      # MIME parse, HTML→text, story segmentation, link + date extract  ✅ complete
├── processing/
│   ├── embedder.py          # sentence-transformers + community_detection (threshold=0.55)  ✅ complete
│   ├── deduplicator.py      # clusters → representative story item selection  ✅ complete
│   └── digest_builder.py    # pipeline orchestrator — 7-stage pipeline  ✅ complete
├── ai/
│   └── claude_client.py     # filter_noise + refine_clusters + filter_stories  ✅ complete
├── api/
│   ├── digests.py           # POST /api/digests/generate, GET /api/digests/latest
│   ├── export.py            # GET /api/digests/{id}/pdf
│   └── health.py            # GET /api/health
├── static/
│   ├── index.html           # Single-page shell
│   ├── style.css            # Pico.css overrides
│   └── app.js               # All UI logic  ⚠️ needs update (new story item shape)
├── tests/
│   ├── test_deduplicator.py # ✅ complete
│   ├── test_claude_client.py # ✅ complete (22 tests: filter, noise, refine constants + message builders)
│   ├── test_embedder.py     # ✅ complete (6 embed_and_cluster smoke tests)
│   └── test_email_parser.py # ✅ complete
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
- **Logic filter — never drop by length:** Short items (one sentence, a few words plus a link) are valid stories. Preserve when uncertain; downstream LLM filters are the safety net.
- **LLM noise filter (pre-cluster):** `filter_noise` removes structural non-article content only. Maximally conservative — bias toward keeping. Runs before embedding.
- **Dedup — two stages:** Embedding clustering at threshold=0.55 (high recall), then `refine_clusters` pairwise LLM within each multi-story cluster. Three-way: `same_story` merges (union-find), `related_but_distinct` / `different` stay separate.
- **Representative selection order:** Longest body → has title → real content URL. Cross-date: keep earliest date in cluster.
- **LLM editorial filter — binary only:** `filter_stories` runs post-dedup on representatives. No generation. Uncertainty defaults to KEEP. Never drops short valid stories.
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
| `PRD.md` | ✅ Source of truth — needs targeted updates for new pipeline stages |
| `CLAUDE.md` | ✅ Updated — reflects 7-stage pipeline, LLM noise filter, pairwise dedup |
| `.env.example` | ✅ Complete (DEDUP_THRESHOLD=0.55, no DEDUP_CANDIDATE_MIN) |
| `config.py` | ✅ Complete (dedup_threshold=0.55, dedup_candidate_min removed) |
| `database.py` | ✅ No changes needed |
| `alembic/` | ✅ No changes needed |
| `ingestion/imap_client.py` | ✅ Complete |
| `ingestion/email_parser.py` | ✅ Complete — story segmentation and date extraction implemented |
| `processing/embedder.py` | ✅ Complete — embed_and_cluster with 0.55 threshold; find_candidate_cluster_pairs removed |
| `processing/deduplicator.py` | ✅ Complete — representative selection; merge_confirmed_clusters retained |
| `processing/digest_builder.py` | ✅ Complete — 7-stage pipeline |
| `ai/claude_client.py` | ✅ Complete — filter_noise + refine_clusters + filter_stories |
| `tests/test_deduplicator.py` | ✅ Complete |
| `tests/test_claude_client.py` | ✅ Complete (22 tests) |
| `tests/test_embedder.py` | ✅ Complete (6 smoke tests) |
| `tests/test_email_parser.py` | ✅ Complete |
| `api/` (all routes) | ⚠️ Phase 2 — not yet implemented |
| `static/app.js` | ⚠️ Phase 3 — not yet updated for new story item shape |

---

## Environment Variables

```
IMAP_HOST, IMAP_PORT, IMAP_USERNAME, IMAP_PASSWORD
ANTHROPIC_API_KEY, CLAUDE_MODEL (claude-haiku-4-5)
MAX_EMAILS_PER_RUN (50), DEDUP_THRESHOLD (0.55)
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
| 1 | Core pipeline as CLI script — `digest_builder.py` runnable end-to-end with new architecture | **Complete** |
| 2 | Wrap pipeline in FastAPI — `POST /api/digests/generate` returns story list JSON | Pending |
| 3 | Frontend + PDF export — render new story item shape, Pico.css, marked.js, weasyprint | Pending |
| 4 | Polish + deployment — error states, empty states, README, Dockerfile | Pending |

---

## Phase 1 — Complete

All pipeline stages implemented and tested (114/114 passing). Pipeline is runnable end-to-end via CLI:

```bash
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-04-01 --end 2026-04-07
```

The 7-stage pipeline: fetch → parse → `filter_noise` → `embed_and_cluster` (0.55) → `refine_clusters` → `deduplicate` → `filter_stories`.

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
