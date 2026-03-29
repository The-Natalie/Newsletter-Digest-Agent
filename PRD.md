# Product Requirements Document
# Newsletter Digest Agent

**Version:** 1.1
**Date:** 2026-03-17
**Status:** Draft — Scope Confirmed

---

## 1. Executive Summary

Newsletter Digest Agent is a personal productivity tool that reads newsletters from a user-designated email folder, removes redundant stories that appear across multiple sources, and produces a single consolidated digest. Instead of reading several newsletters that repeat the same announcements, the user reviews one concise summary that preserves links, surfaces unique insights, and groups overlapping stories into a single entry.

The system connects to any standard IMAP email account. The user routes newsletter subscriptions into dedicated folders using their email client's built-in rules — one folder per topic area. In the app, they select which folder to read from (presented as a category label), optionally set a date range, and trigger generation. The tool reads that folder, extracts story content, detects near-duplicate coverage across sources, and generates a digest through the Claude AI API. The result is displayed in the UI and can be downloaded as a PDF.

**MVP Goal:** Deliver a deployable web tool — a FastAPI backend paired with a standalone vanilla HTML/CSS/JS frontend — that a single user can configure once and use to generate on-demand digests from any of their newsletter folders. The tool should be lightweight, cost-efficient with the Claude API, and suitable for inclusion in a portfolio as a standalone page.

---

## 2. Mission

**Mission Statement:** Reduce the time it takes to stay informed by turning a stack of overlapping newsletters into a single, signal-rich digest.

### Core Principles

1. **Signal over volume.** One well-structured entry per story is more valuable than five slightly different versions of the same announcement.
2. **Folder selection is open-ended.** The user specifies which IMAP folder to read at runtime. Preset shortcuts in the UI are a convenience, not a constraint — any folder name the user types is valid.
3. **Links are preserved.** The digest surfaces sources. If three newsletters covered the same story, all three source links appear on the merged entry.
4. **Cost-aware AI usage.** Given the low daily volume (2–10 emails), the system should prefer cost-efficient model choices and avoid unnecessary API calls.
5. **Portable and customizable.** The frontend uses standard web technologies so the user can adjust layout, styling, and behavior without a build toolchain.

---

## 3. Target Users

### Primary Persona: The Multi-Newsletter Reader

**Profile:** A professional or enthusiast who subscribes to 5–20 topic-specific newsletters (AI, technology, business, design, etc.). They organize their inbox by routing subscriptions into named folders using their email client's built-in rules — one folder per topic. They want a faster way to get the signal from a folder without opening each newsletter individually.

**Technical comfort:** Comfortable using a web interface and managing their email inbox — creating folders, setting up filters, and routing newsletter subscriptions. No coding, server administration, or configuration file editing is expected. The tool is pre-configured by the developer before the user ever interacts with it.

**Where the user experience begins:** After the tool is deployed and configured, the user opens a web page. From there, their workflow is entirely within the UI: select a folder, optionally set a date range, and trigger a digest. All email access, API integration, and backend behavior is handled transparently.

**Key pain points:**
- Spending 30–60 minutes reading newsletters where 40–60% of the content is repeated across sources
- Missing unique insights buried under repeated coverage
- Falling behind when newsletters accumulate over a few days and catching up feels overwhelming
- No single view that covers a topic area with all sources in one place

**Key needs:**
- One place to go instead of five newsletter tabs
- Confidence that unique stories from any source are not dropped
- Ability to catch up on a specific date range when they've been away
- A simple interface that requires no technical knowledge to operate

---

## 4. MVP Scope

### Core Functionality

| Feature | Status |
|---|---|
| Read emails from a user-specified IMAP folder | ✅ In Scope |
| Filter emails by date range | ✅ In Scope |
| Extract story content from HTML newsletter emails | ✅ In Scope |
| Detect near-duplicate stories across newsletters (story-level dedup, within current run only) | ✅ In Scope |
| Merge duplicate stories into one digest entry with all source links | ✅ In Scope |
| Generate digest via Claude API | ✅ In Scope |
| Manual on-demand digest generation from the UI | ✅ In Scope |
| Folder selection via preset shortcut buttons (UI convenience only) and free-text input | ✅ In Scope |
| Display digest in the UI | ✅ In Scope |
| Download digest as PDF | ✅ In Scope |
| Simple loading state during digest generation | ✅ In Scope |
| Email access via pre-configured IMAP credentials (internal, not user-facing) | ✅ In Scope |
| Standalone deployable frontend (portfolio-compatible) | ✅ In Scope |

### Out of Scope — Deferred to Phase 2+

| Feature | Status | Notes |
|---|---|---|
| Scheduled automatic digest generation | ❌ Phase 2 | |
| Email delivery of digest | ❌ Phase 2 | |
| Cross-run deduplication | ❌ Phase 2 | Dedup across previous digest runs using persisted story embeddings; unrelated to multiple folder support |
| Importance / priority ranking of stories | ❌ Phase 2 | |
| OAuth2 authentication (Gmail, Outlook) | ❌ Phase 2 | Aligned with multi-user support |
| Multiple folder configurations per run | ❌ Phase 2 | |
| Multiple user accounts | ❌ Phase 2 | |
| Runtime configuration via UI | ❌ Phase 2 | Depends on scheduling and delivery features being present |
| Real-time progress streaming via SSE | ❌ Phase 2 | MVP uses a simple loading state instead |
| Batched digest generation (multiple Claude calls per run) | ❌ Phase 2 | MVP uses a single call with a 50-group cap; Phase 2 removes the cap and batches in groups of 15–25 |
| Digest history — browsing past runs | ❌ Future | |
| Topic-level thematic grouping (beyond story-level dedup) | ❌ Future | |
| Browser extension or email client plugin | ❌ Future | |
| Mobile app | ❌ Future | |
| RSS/Atom feed input (non-email) | ❌ Future | |
| Per-newsletter analytics or statistics | ❌ Future | |

---

## 5. User Stories

### US-01: Manual Digest Generation
**As a newsletter reader, I want to enter a folder name, optionally set a date range, and click "Generate Digest," so that I get a consolidated summary without opening each newsletter individually.**

Example: User opens the app, clicks the "AI" shortcut button (which populates the folder input with `AI Newsletters`), sets the date range to the past 3 days, and clicks Generate. The app fetches 12 newsletter emails from that period, deduplicates them, and returns a digest of 8 merged story entries — each with a headline, 2–4 sentence summary, and source links.

---

### US-02: Any Folder at Runtime
**As a user, I want to enter any folder name at runtime, so that I can generate a digest for any of my newsletter folders without reconfiguring the app.**

Example: User has folders named "AI Newsletters," "Design Weekly," and "Fintech." They can run a digest on any of these by typing the folder name into the input field — or using a preset shortcut if one matches — then clicking Generate. Switching folders on the next run requires no configuration change.

---

### US-03: Date Range Selection
**As a user returning from a few days away, I want to set a specific date range so that I can summarize newsletters from a period I missed.**

Example: User was offline March 10–16. They set the date range to March 10–16 and click Generate. The system processes all newsletter emails from that window, deduplicates within that set, and returns a single digest covering the full period.

---

### US-04: Deduplication Across Sources
**As a user who subscribes to multiple newsletters on the same topic, I want stories that appear in multiple newsletters to be merged into one entry, so that I don't read the same announcement several times.**

Example: Four newsletters all mention the same product launch. The digest shows one entry: a combined headline, a 2–4 sentence summary drawn from all four versions, and four source links — one per newsletter.

---

### US-05: Source Links Preserved
**As a user who wants to read the full article, I want each digest entry to include the original source links, so that I can click through when something catches my attention.**

Example: A merged story entry shows: headline, summary, and three links labeled "TLDR AI," "The Rundown," and "Import AI" — each linking to where that newsletter covered the story.

---

### US-06: Loading Feedback During Generation
**As a user who triggered a digest, I want a clear loading state while it generates, so that I know the system is working and have not accidentally submitted twice.**

Example: After clicking Generate, the button disables and a loading indicator appears. When the digest is ready, the indicator disappears and the digest renders in place.

---

### US-07: PDF Download
**As a user who wants to save or share a digest, I want to download it as a PDF, so that I have a portable copy outside the browser.**

Example: After the digest renders in the UI, user clicks "Download PDF." A formatted PDF opens or downloads with the digest content — headlines, summaries, and source links — laid out cleanly for reading.

---

## 6. Core Architecture & Patterns

### Architecture Overview

The system follows a linear pipeline architecture. Each stage receives data from the previous and passes results forward. The API layer exposes this pipeline to the frontend via a trigger endpoint that runs the pipeline synchronously and returns the completed digest in a single response.

```
Email Inbox (IMAP)
        │
        ▼
 Ingestion Layer         — connect, filter by folder + date range, fetch emails
        │
        ▼
 Extraction Layer        — parse MIME, HTML→text, extract stories and links
        │
        ▼
 Deduplication Layer     — embed stories, cluster by semantic similarity (within-run)
        │
        ▼
 AI Review Layer         — Claude classifies each story group as KEEP or DROP (haiku, pre-generation filter)
        │
        ▼
 AI Generation Layer     — Claude API generates one summary per story group (batched single call, MVP cap: 50)
        │
        ▼
 Storage Layer           — SQLite stores the most recent digest output
        │
        ▼
 API Layer (FastAPI)     — trigger endpoint (sync response), digest retrieval, PDF export
        │
        ▼
 Frontend (Vanilla JS)   — category/folder selection, date range, generate button, output view, PDF download
```

### Project Directory Structure

```
newsletter-digest/
├── main.py                     # FastAPI app factory, mounts routers, serves static files
├── config.py                   # Pydantic BaseSettings — reads from .env, validates at startup
├── database.py                 # SQLAlchemy async engine, session factory, table metadata
│
├── ingestion/
│   ├── __init__.py
│   ├── imap_client.py          # IMAPClient wrapper — connect, folder select, UID search, fetch
│   └── email_parser.py         # MIME parsing, HTML→text, metadata extraction
│
├── processing/
│   ├── __init__.py
│   ├── embedder.py             # sentence-transformers encoding + community_detection clustering
│   ├── deduplicator.py         # Cluster → merged story groups with combined source links
│   └── digest_builder.py       # Orchestrates full pipeline; emits progress events
│
├── ai/
│   ├── __init__.py
│   ├── story_reviewer.py       # Pre-generation KEEP/DROP classifier (haiku, tool-use schema)
│   └── claude_client.py        # Anthropic SDK, prompt templates, tool-use schema
│
├── api/
│   ├── __init__.py
│   ├── digests.py              # POST /api/digests/generate, GET /api/digests/latest
│   ├── export.py               # GET /api/digests/{digest_id}/pdf
│   └── health.py               # GET /api/health
│
├── static/
│   ├── index.html              # Single-page frontend shell
│   ├── style.css               # Custom overrides on Pico.css
│   └── app.js                  # All frontend logic (state, form handling, rendering)
│
├── data/
│   └── digest.db               # SQLite database (gitignored)
│
├── .env                        # IMAP credentials and API key (gitignored)
├── .env.example                # All keys with placeholder values and comments
├── requirements.txt
└── alembic/
    └── versions/
```

### Key Design Patterns

- **Thin API routes:** Routes validate input, call into the pipeline, and return the result. No pipeline logic in route handlers.
- **Synchronous pipeline response:** `digest_builder.py` runs the full pipeline and returns the completed digest JSON. The frontend shows a loading state while the request is in flight; the digest renders when the response arrives.
- **Folder name is the only input:** The backend receives a single folder name string and reads it directly. Preset shortcuts in the UI are hardcoded in the frontend for convenience; they carry no special meaning to the backend. The pipeline has no concept of categories — it only knows about folder names.
- **Stateless within-run dedup:** Embeddings are computed at runtime and held in memory during the pipeline run. Nothing is written to the database for dedup purposes. This keeps the MVP schema simple.
- **Single active digest:** The database stores only the most recently completed digest. The frontend retrieves and displays this on load, or replaces it when a new one is generated.

---

## 7. Features

### Feature 1: Email Ingestion

**Purpose:** Connect to the user's IMAP server, select the specified folder, and retrieve emails filtered by date range.

**Operations:**
- Establish SSL connection using configured IMAP host, port, username, and app password
- Select the folder in read-only mode (`readonly=True`) — no flags are modified
- Search by date range using IMAP `SINCE` / `BEFORE` criteria
- Fetch message bodies using `BODY.PEEK[]` (preserves unread status)
- Batch fetch in groups of 50 to stay within server response limits

**Key behaviors:**
- Folder name comes directly from the UI as a plain string — whether the user clicked a preset shortcut or typed a custom name
- If the folder does not exist, returns a clear error in the API response that the frontend surfaces to the user

---

### Feature 2: Content Extraction

**Purpose:** Parse raw MIME emails into structured story content suitable for embedding and summarization.

**Operations:**
- Parse multipart MIME with Python `email.message_from_bytes` using `policy.default`
- Prefer `text/plain` parts; fall back to `text/html` (the common case for newsletters)
- Pre-process HTML with BeautifulSoup: strip `<img>`, `<style>`, `<script>`, and hidden pre-header elements
- Convert cleaned HTML to readable text using `html2text` (preserves hyperlinks, removes images)
- Extract per-email: subject, sender name/domain, received date, body text, and all hyperlinks with anchor text

**Pitfall handling:**
- HTML-only emails (no `text/plain` part) — handled by HTML fallback, which is the default path
- `quoted-printable` and `base64` encoding — decoded automatically by `policy.default`
- Invisible pre-header text (white-on-white, `display:none`, `font-size:0`) — stripped by BeautifulSoup pre-pass
- Tracking pixel `<img>` tags — removed before html2text conversion

---

### Feature 3: Story-Level Deduplication (Within-Run)

**Purpose:** Identify when multiple newsletters in the current run cover the same event and group them into a single story cluster.

**Scope:** Deduplication operates only across the emails fetched in the current run. No comparison against prior runs. Embeddings are held in memory and discarded after the run completes.

**Operations:**
- Split each email body into story candidates using structural heuristics (blank line boundaries, horizontal rule tags, repeated heading patterns)
- Encode story titles + first 2–3 sentences using `sentence-transformers` (`all-MiniLM-L6-v2`, 22MB, CPU-compatible)
- Run `util.community_detection` at cosine similarity threshold 0.78 to form clusters
- Each cluster → one digest entry; all contributing newsletters and their source links are recorded for that entry

**What "same story" means:** Two stories are merged if they describe the same specific event or announcement (same funding round, same product release, same regulatory ruling). Two different articles about a broad shared theme (e.g., "AI regulation") that address distinct developments remain separate entries.

---

### Feature 4: AI Digest Generation

**Purpose:** Use the Claude API to generate a human-readable digest entry for each deduplicated story group that has passed the AI review step.

**Architecture note:** The generation pipeline is intentionally hybrid. Deterministic rules (HTML extraction, link filtering, semantic clustering) do the heavy lifting. An AI review step (`story_reviewer.py`) handles ambiguous filtering before generation, removing non-story groups that deterministic rules cannot reliably catch. Only story groups that pass review reach the generation step.

**Model:** `claude-haiku-4-5` (default). Configurable via `CLAUDE_MODEL` in `.env` if the user wants to upgrade to `claude-sonnet-4-6`.

**Prompt structure per cluster:**
```
You are generating a newsletter digest entry focused on {category}.

The following {N} excerpts are different newsletters covering the same story:

<source newsletter="{name}">
{extracted text}
</source>
...

Write a digest entry with:
- Headline: Clear and direct, max 12 words
- Summary: 2–4 sentences capturing the most complete picture across all versions, prioritizing clarity over completeness
- Significance: One sentence on why this matters for someone following {category}
```

**Structured output via Claude tool use:**
```json
{
  "headline": "string",
  "summary": "string",
  "significance": "string",
  "sources": [
    { "newsletter": "string", "url": "string", "anchor_text": "string" }
  ]
}
```

**Batching:** All reviewed story groups are passed to Claude in a single API call using a multi-cluster prompt structure. This minimizes API calls and cost regardless of how many unique stories the run produces.

**MVP cap:** A temporary limit of 50 story groups per generation call is applied in `digest_builder.py` after the AI review step. This constraint exists to stay within output token limits during the MVP phase and is not a permanent design decision — it will be replaced by batched generation in Phase 2.

---

### Feature 5: Folder Selection

**Purpose:** Let the user specify which IMAP folder to read for a given digest run.

**How it works:**
- The UI provides a text input for the folder name, which is always the primary control
- Preset shortcut buttons (e.g., "AI," "News," "Tech") are hardcoded in the frontend as a typing convenience — clicking one populates the folder name input with a suggested value that the user can accept or edit
- Presets carry no special meaning to the backend; they are purely a frontend affordance
- The user can change which folder they read on any run without any reconfiguration
- Only one folder is processed per run

**Example:** The UI shows shortcut buttons for "AI," "News," and "Tech." Clicking "AI" populates the input with `AI Newsletters`. The user can edit this to `AI Weekly` before submitting. Alternatively, they ignore the shortcuts and type any folder name directly.

**No validation of folder existence before submission** — if the folder does not exist on the server, the generate endpoint returns a clear error that is displayed in the UI.

---

### Feature 6: PDF Export

**Purpose:** Allow the user to download the current digest as a formatted PDF for offline reading or sharing.

**Implementation:** Server-side PDF generation using `weasyprint` (HTML→PDF). The digest JSON is rendered into an HTML template server-side, then converted to PDF. The endpoint streams the PDF bytes with `Content-Type: application/pdf` and `Content-Disposition: attachment`.

**Endpoint:** `GET /api/digests/{digest_id}/pdf`

**PDF content:** All digest entries in order — headline, summary, significance, and source links (URLs printed as text for accessibility in printed form).

**Alternative if weasyprint has dependency issues on the deployment target:** `reportlab` (pure Python, no system dependencies) as a fallback, generating a simpler but fully portable PDF.

---

### Feature 7: Loading State During Generation

**Purpose:** Keep the user informed that the system is working while the digest generates.

**Mechanism:** The frontend disables the Generate button and shows a loading indicator immediately on form submission. The `POST /api/digests/generate` endpoint runs the full pipeline synchronously and returns the completed digest (or an error) in a single HTTP response. When the response arrives, the loading state clears and the digest renders — or an error message is displayed.

**Frontend behavior:**
- Generate button transitions to a disabled "Generating…" state on click
- A loading indicator (`<progress>` element in indeterminate mode, styled by Pico.css) appears below the button
- On success: loading clears, digest renders in the output area
- On error: loading clears, a human-readable error message appears in the output area (e.g., "Folder 'AI Newsletters' was not found. Check your folder name and try again.")

**Note:** Real-time step-by-step progress streaming via SSE is deferred to Phase 2.

---

## 8. Technology Stack

### Backend

| Technology | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Runtime |
| FastAPI | 0.115+ | Web framework, API routing, BackgroundTasks |
| Uvicorn | 0.30+ | ASGI server |
| SQLAlchemy Core | 2.0+ | Database schema, async queries |
| aiosqlite | 0.20+ | Async SQLite driver |
| Alembic | 1.13+ | Database migrations |
| Pydantic / pydantic-settings | 2.x | Config validation, request/response models |
| python-dotenv | 1.x | `.env` file loading |

### Email

| Technology | Version | Purpose |
|---|---|---|
| IMAPClient | 3.x | IMAP folder access, UID-based email fetching |
| html2text | 2024.x | HTML newsletter body → readable plain text |
| BeautifulSoup4 | 4.12+ | HTML pre-processing, noise removal |
| lxml | 5.x | Fast HTML parser backend for BeautifulSoup |

### AI & NLP

| Technology | Version | Purpose |
|---|---|---|
| anthropic | 0.40+ | Claude API SDK (async client) |
| sentence-transformers | 3.x | Semantic embeddings for within-run dedup |
| torch (CPU only) | 2.x | Required by sentence-transformers; CPU install sufficient |

### Frontend

| Technology | Version | Purpose |
|---|---|---|
| Pico.css | 2.x | Semantic classless CSS framework |
| marked.js | 13.x | Markdown rendering (CDN import) |
| Vanilla JS (ES2022) | — | State management, SSE, form handling, rendering |
| Native `<input type="date">` | — | Date range inputs (no additional dependency) |

### PDF Export

| Technology | Version | Purpose |
|---|---|---|
| weasyprint | 62.x | HTML→PDF generation (primary) |
| reportlab | 4.x | Pure Python PDF fallback if weasyprint has system dep issues |

### Phase 2 / Optional (Not in MVP)

| Technology | Purpose |
|---|---|
| APScheduler | Scheduled digest generation |
| smtplib (stdlib) | Email delivery of digest |
| google-auth-oauthlib | Gmail OAuth2 |
| msal | Outlook OAuth2 |

---

## 9. Security & Configuration

### Authentication Approach

- **IMAP:** App Password. Credentials stored in `.env`, excluded from version control.
- **Claude API:** API key stored in `.env`.
- **Web app:** No authentication in MVP. Intended for personal/single-user deployment. Assume deployment is either local or behind a private network / IP restriction.

### Environment Variables

```bash
# IMAP Configuration
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USERNAME=user@example.com
IMAP_PASSWORD=your_app_password_here

# Claude API
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-haiku-4-5

# App Settings
DATABASE_URL=sqlite+aiosqlite:///./data/digest.db
HOST=0.0.0.0
PORT=8000
```

### Security Scope

**In scope:**
- `.env` excluded from version control via `.gitignore`
- IMAP connection over SSL (port 993)
- Read-only IMAP folder access (`readonly=True`, `BODY.PEEK[]`)
- Digest output rendered via `marked.js` (not raw `innerHTML` of arbitrary HTML)

**Out of scope (MVP):**
- Web app authentication / login
- HTTPS termination (assumed to be handled by a reverse proxy if deployed publicly)
- Rate limiting on API endpoints
- OAuth2 for any email provider

### Deployment

Single process: `uvicorn main:app --host 0.0.0.0 --port 8000`. The `static/` directory is served by FastAPI's `StaticFiles` mount — no separate static host needed. SQLite database lives in `data/digest.db`. A `Dockerfile` will be provided in Phase 3 for containerized deployment.

---

## 10. API Specification

### Digest Endpoints

#### `POST /api/digests/generate`
Trigger digest generation. Returns a job ID immediately; pipeline runs as a background task.

**Request:**
```json
{
  "folder": "AI Newsletters",
  "date_start": "2026-03-10",
  "date_end": "2026-03-17"
}
```

**Response (200 OK) — pipeline runs synchronously, full digest returned on completion:**
```json
{
  "id": "a3f2c1d8-...",
  "generated_at": "2026-03-17T09:14:00Z",
  "folder": "AI Newsletters",
  "date_start": "2026-03-10",
  "date_end": "2026-03-17",
  "story_count": 18,
  "stories": [ ... ]
}
```

**Error response (400 / 500):**
```json
{
  "error": "Folder 'AI Newsletters' was not found on the IMAP server."
}
```

---

#### `GET /api/digests/latest`
Retrieve the most recently completed digest.

**Response:**
```json
{
  "id": "b7e1...",
  "generated_at": "2026-03-17T09:14:00Z",
  "folder": "AI Newsletters",
  "date_start": "2026-03-10",
  "date_end": "2026-03-17",
  "story_count": 18,
  "stories": [
    {
      "headline": "OpenAI Releases GPT-5 with Multimodal Reasoning",
      "summary": "OpenAI launched GPT-5 on March 14, 2026...",
      "significance": "Developers building AI pipelines will need to re-evaluate context management as multimodal inputs change token costs significantly.",
      "sources": [
        { "newsletter": "TLDR AI", "url": "https://...", "anchor_text": "OpenAI GPT-5 launch" },
        { "newsletter": "The Rundown", "url": "https://...", "anchor_text": "GPT-5 is here" }
      ]
    }
  ]
}
```

---

#### `GET /api/digests/{digest_id}/pdf`
Generate and stream a PDF of the specified digest.

**Response:** `Content-Type: application/pdf`, `Content-Disposition: attachment; filename="digest-2026-03-17.pdf"`

---

### Utility Endpoints

#### `GET /api/health`
Returns `{"status": "ok"}`.

---

## 11. Success Criteria

### MVP Success Definition

The MVP is successful when a user can open the web interface, select a newsletter folder, trigger a digest, and receive a formatted digest that correctly merges overlapping stories, preserves source links, and is downloadable as a PDF. A loading state is shown while the pipeline runs; the result appears when it completes. Email credentials and backend configuration are set once by the developer and are never part of the user-facing experience.

### Functional Requirements

| Requirement | Status |
|---|---|
| ✅ Connect to any IMAP server with host, port, username, and app password | Required |
| ✅ Read all emails from the specified folder within the selected date range | Required |
| ✅ Extract readable text from HTML-only newsletter emails | Required |
| ✅ Detect and merge stories covering the same event across newsletters in the current run | Required |
| ✅ Generate one digest entry per unique story with headline, summary, significance, and source links | Required |
| ✅ Show a loading state (disabled button + progress indicator) while digest generates | Required |
| ✅ Display completed digest in the UI rendered from structured JSON | Required |
| ✅ Allow download of the current digest as a PDF | Required |
| ✅ UI provides a folder name input and optional preset shortcut buttons (hardcoded in the frontend) | Required |
| ✅ UI includes a date range selector (start and end date inputs) | Required |
| ✅ Frontend works as a standalone deployable page | Required |
| ✅ App runs as a single `uvicorn` process with no external services (no Redis, no broker) | Required |

### Quality Indicators

- Digest generation for 10 emails completes in under 60 seconds
- Semantic dedup correctly identifies the same story from two different newsletters at least 90% of the time during manual testing
- No newsletter in the date range is silently skipped — all failures are surfaced as error responses and displayed in the UI
- The UI is usable on a 1280px viewport without horizontal scrolling

### User Experience Goals

- A user who opens the web interface for the first time can generate a digest without any instructions
- All controls (category, date range, generate button) are visible without scrolling
- The loading indicator is visible immediately after clicking Generate, so the user knows the request is in flight
- The digest is scannable — a user should be able to assess 18 stories in under 5 minutes

---

## 12. Implementation Phases

### Phase 1: Core Pipeline
**Goal:** A working end-to-end pipeline as a runnable script. No web server, no UI.

**Deliverables:**
- ✅ `config.py` — Pydantic BaseSettings, `.env` loading, startup validation, category parsing
- ✅ `database.py` — SQLite schema (digest_runs table only), async engine, Alembic baseline
- ✅ `ingestion/imap_client.py` — IMAP connection, read-only folder selection, date range search, batched fetch
- ✅ `ingestion/email_parser.py` — MIME parsing, BeautifulSoup pre-processing, html2text conversion, link extraction
- ✅ `processing/embedder.py` — sentence-transformers encoding (in-memory), community_detection clustering
- ✅ `processing/deduplicator.py` — cluster → merged story groups with combined source links
- ✅ `ai/story_reviewer.py` — pre-generation KEEP/DROP classifier; Claude haiku call; filters non-story groups before generation
- ✅ `ai/claude_client.py` — Anthropic SDK async client, batched multi-cluster prompt, tool-use schema
- ✅ `processing/digest_builder.py` — pipeline function; runs all stages end-to-end (ingestion → extraction → cluster → review → generate → store) and returns completed digest JSON
- ✅ CLI entry point: `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-10 --end 2026-03-17`

**Validation:** Run against a real newsletter folder with at least two overlapping newsletters. Confirm at least one merged story entry. Confirm the full digest JSON is printed and written to the database.

---

### Phase 2: API
**Goal:** Wrap the pipeline in FastAPI. Expose it via HTTP with a synchronous request/response pattern.

**Deliverables:**
- ✅ `main.py` — FastAPI app, StaticFiles mount, router registration
- ✅ `api/digests.py` — `POST /api/digests/generate` (runs pipeline, returns completed digest), `GET /api/digests/latest`
- ✅ `api/health.py` — health check
- ✅ Digest result written to `digest_runs` table on completion; status is `complete` or `failed`
- ✅ Error handling: IMAP failures and Claude API failures return structured error JSON with human-readable messages

**Validation:** Use `curl` or HTTPie to trigger a digest. Confirm the response contains the full digest JSON. Confirm `GET /api/digests/latest` returns the same result. Confirm error cases return a readable error message.

---

### Phase 3: Frontend & PDF Export
**Goal:** A complete, usable tool in a browser. The frontend is portfolio-ready.

**Deliverables:**
- ✅ `static/index.html` — single-page shell with Pico.css, semantic layout
- ✅ `static/app.js` — form state management; `POST` trigger; loading state (disabled button + progress indicator); `marked.js` digest rendering; error display
- ✅ Folder name text input with optional preset shortcut buttons (hardcoded in the frontend); shortcuts populate the input on click
- ✅ Date range inputs (native `<input type="date">` pair with client-side start≤end validation)
- ✅ Generate button (disabled while in progress)
- ✅ Loading indicator shown while request is in flight; clears on success or error
- ✅ Digest rendered in an `<article>` card with headlines, summaries, significance lines, and source links
- ✅ "Download PDF" button — calls `GET /api/digests/{id}/pdf`
- ✅ `api/export.py` — PDF generation via weasyprint from digest JSON
- ✅ `localStorage` persistence for last-used folder selection and date range
- ✅ `Dockerfile` for single-container deployment

**Validation:** Open in browser. Type a real folder name (or click a preset shortcut), set date range, click Generate — confirm the button disables and loading indicator appears. When complete, digest renders. Click Download PDF and confirm output. Run again with a different folder name to confirm folder selection is free-form across runs. Test an invalid folder name and confirm a readable error appears. Verify the page loads cleanly at 1280px and 768px.

---

### Phase 4: Polish & Deployment Readiness
**Goal:** Make the tool robust enough for daily personal use and clean enough for portfolio presentation.

**Deliverables:**
- ✅ Error messages in the UI are human-readable (folder not found, API key invalid, no emails in range)
- ✅ Empty state when no digest has been generated yet (clear prompt to generate first digest)
- ✅ `.env.example` with all keys, placeholder values, and inline documentation comments
- ✅ `README.md` with 5-step quick start, `.env` reference, and deployment instructions
- ✅ Frontend reviewed for portfolio quality: consistent spacing, clean typography, no visible rough edges
- ✅ Manual test against at least 3 different newsletter types to validate HTML extraction quality
- ✅ Tune dedup threshold based on real results from user's actual newsletter folder

---

## 13. Future Considerations

### Phase 2 Additions (Planned)

- **Real-time progress streaming** — Server-Sent Events (SSE) replacing the simple loading state; the frontend receives step-by-step pipeline updates as the digest generates
- **Batched digest generation** — Remove the MVP 50-group cap and replace it with batched generation (15–25 story groups per Claude call); results are aggregated into a single digest response. The AI review step runs before batching so only valid story groups are batched.
- **Scheduled digest generation** — APScheduler with a configurable cron expression; runs the pipeline automatically and saves the result
- **Email delivery** — SMTP digest delivery (HTML + plain text fallback); user chooses "in browser," "email only," or "both"
- **Runtime configuration via UI** — settings panel for schedule interval and delivery preferences; depends on scheduling and delivery features being present
- **Cross-run deduplication** — persist story embeddings in SQLite across digest runs; detect when a new email covers a story already summarized in a prior run and flag it as a follow-up rather than a new entry
- **Multiple folder configurations per run** — process two or more folders in a single digest run (e.g., "AI Newsletters" + "Startup Newsletters")
- **Multiple user accounts** — per-user configuration and digest history; aligned with OAuth2 authentication
- **OAuth2 authentication** — for Gmail (Google Cloud Console) and Outlook (MSAL); required for multi-user support

### Later Additions

- **Digest history** — browse and re-read past runs from a history panel in the UI
- **Importance ranking** — ask Claude to rank stories by significance within the category and reorder the digest accordingly
- **Notion / Obsidian export** — write each digest as a page in the user's knowledge base
- **Slack / Discord webhook delivery**
- **Per-newsletter analytics** — which sources contribute the most unique stories vs. mostly duplicate coverage

---

## 14. Risks & Mitigations

### Risk 1: IMAP Provider Compatibility
**Risk:** IMAP folder naming varies across providers. Gmail maps labels to folder paths in non-standard ways. A user who types their folder name incorrectly gets a confusing error.

**Mitigation:** Provide a `GET /api/imap/folders` endpoint (debug/setup utility) that lists all folders on the server — helpful during initial configuration. Surface clear error messages ("Folder 'AI Newsletters' not found. Available folders: AI, Technology, ...") in the API error response and display them in the UI output area. Document Gmail-specific folder naming in the README.

---

### Risk 2: HTML Email Parsing Quality
**Risk:** Newsletter HTML varies across platforms (Substack, Beehiiv, ConvertKit, Mailchimp). Poor extraction means the digest summarizes noise instead of content.

**Mitigation:** `html2text` handles the majority of newsletters well. BeautifulSoup pre-processing removes the most common noise patterns. Log the character count of extracted text per email during the pipeline run — extractions under 200 characters are flagged as suspected parse failures in server logs. Phase 4 includes manual testing against at least 3 different newsletter platforms.

---

### Risk 3: Claude API Cost on Large Catch-Up Runs
**Risk:** A user processing a large backlog (e.g., 3 weeks of emails = 150+ messages) could generate a surprisingly large Claude API bill.

**Mitigation:** Default model is `claude-haiku-4-5` (significantly cheaper than Sonnet). All story clusters are batched into a single API call. Add a configurable `MAX_EMAILS_PER_RUN` in `.env` (default: 50) that caps a single digest run. Log token usage per run in `digest_runs` so the user can monitor costs.

---

### Risk 4: Deduplication False Positives
**Risk:** The 0.82 cosine similarity threshold may merge stories that are actually distinct — two different funding rounds in the same sector, for example.

**Mitigation:** Make the threshold configurable in `.env` (`DEDUP_THRESHOLD=0.78`). Log cluster sizes in the pipeline output — clusters with more than 5 members are logged as warnings for manual inspection. Phase 4 includes threshold tuning based on real results from the user's actual newsletters.

---

### Risk 5: weasyprint System Dependencies
**Risk:** weasyprint requires system-level libraries (Pango, Cairo, GLib) that may not be available on all deployment targets. This can make Docker builds unexpectedly complex.

**Mitigation:** Use the official weasyprint Docker base image or install system dependencies in the Dockerfile explicitly. If system dependency installation proves problematic, fall back to `reportlab` for pure-Python PDF generation, with a note in the README that the PDF output will be simpler in style.

---

## 15. Appendix

### Database Schema (MVP)

The MVP schema is intentionally minimal — no persistent story storage, no processed email tracking, no cross-run state.

```sql
-- One row per digest generation run (MVP only retains the most recent)
CREATE TABLE digest_runs (
    id            TEXT PRIMARY KEY,        -- UUID
    run_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    folder        TEXT NOT NULL,           -- IMAP folder name used for this run
    date_start    DATE,
    date_end      DATE,
    story_count   INTEGER DEFAULT 0,
    status        TEXT DEFAULT 'pending',  -- pending | in_progress | complete | failed
    error_message TEXT,
    output_json   TEXT                     -- Full digest as JSON string
);
```

Cross-run dedup, story embeddings, and processed email tracking are deferred to Phase 2 and will require an Alembic migration to add the necessary tables.

### Key Dependencies

| Package | Purpose |
|---|---|
| `fastapi` + `uvicorn` | Web framework and ASGI server |
| `imapclient` | IMAP folder access |
| `html2text` | HTML → readable plain text |
| `beautifulsoup4` + `lxml` | HTML pre-processing |
| `sentence-transformers` | Semantic embeddings for dedup |
| `anthropic` | Claude API SDK |
| `sqlalchemy` + `aiosqlite` | Async SQLite |
| `alembic` | Database migrations |
| `pydantic-settings` | Config from `.env` |
| `weasyprint` | HTML → PDF export |
| Pico.css | Frontend CSS framework |
| marked.js | Markdown rendering in browser |

### Assumption Log

| # | Assumption | Confidence | How to Validate |
|---|---|---|---|
| 1 | `all-MiniLM-L6-v2` encoding for 10 emails' worth of story chunks completes in well under 5 seconds on a modern CPU | High | Benchmark during Phase 1 |
| 2 | `claude-haiku-4-5` produces digest quality acceptable to the user for daily use | Medium | Generate and compare sample digests from haiku vs sonnet during Phase 1 |
| 3 | Batching all clusters into a single Claude API call stays within the model's context window for typical runs (2–10 emails) | High | Verify at Phase 1; add chunking if context limit is hit |
| 4 | The user's newsletter folders contain only newsletters (email rules route them reliably) | High | User confirmed |
| 5 | Blank-line and horizontal-rule heuristics are sufficient for story segmentation within typical newsletter emails | Medium | Test against real newsletters in Phase 1; refine if needed |
| 6 | Dedup threshold of 0.78 is appropriate for the user's newsletter mix | Medium | Tune in Phase 4 based on actual results |
| 7 | weasyprint can be installed cleanly on the target deployment environment | Medium | Validate during Phase 3 Dockerfile build; fall back to reportlab if not |
