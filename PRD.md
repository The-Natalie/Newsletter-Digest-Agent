# Product Requirements Document
# Newsletter Digest Agent

**Version:** 2.0
**Date:** 2026-04-01
**Status:** Draft — Architecture Revised

---

## 1. Executive Summary

Newsletter Digest Agent is a personal productivity tool that reads newsletters from a user-designated email folder, removes redundant stories that appear across multiple sources, and surfaces a single deduplicated list of story items. Instead of reading several newsletters that repeat the same announcements, the user reviews one consolidated list with unique stories only — preserving the original story text, links, and source attribution, sorted from oldest to newest.

The system connects to any standard IMAP email account. The user routes newsletter subscriptions into dedicated folders using their email client's built-in rules — one folder per topic area. In the app, they select which folder to read from, optionally set a date range, and trigger generation. The tool reads that folder, extracts story items, groups near-duplicate coverage across sources into clusters, and surfaces one representative item per story cluster. The result is displayed in the UI and can be downloaded as a PDF.

**MVP Goal:** Deliver a deployable web tool — a FastAPI backend paired with a standalone vanilla HTML/CSS/JS frontend — that a single user can configure once and use to generate on-demand story lists from any of their newsletter folders. The tool should be lightweight, cost-efficient, and suitable for inclusion in a portfolio as a standalone page.

---

## 2. Mission

**Mission Statement:** Reduce the time it takes to stay informed by turning a stack of overlapping newsletters into a single, signal-rich list of unique stories.

### Core Principles

1. **Signal over volume.** One well-sourced story item is more valuable than five slightly different versions of the same announcement.
2. **Extracted, not generated.** Story text is preserved as extracted from the original source — the tool selects and surfaces, it does not rewrite or summarize.
3. **Folder selection is open-ended.** The user specifies which IMAP folder to read at runtime. Preset shortcuts in the UI are a convenience, not a constraint — any folder name the user types is valid.
4. **Short items are preserved.** Legitimate one-sentence stories and roundup items are valid story records. No length filter removes them.
5. **Links and attribution are preserved.** Each story item includes its source newsletter name and link.
6. **Cost-aware AI usage.** The Claude API is used only for a lightweight binary filter pass — not for generation.
7. **Portable and customizable.** The frontend uses standard web technologies so the user can adjust layout, styling, and behavior without a build toolchain.

---

## 3. Target Users

### Primary Persona: The Multi-Newsletter Reader

**Profile:** A professional or enthusiast who subscribes to 5–20 topic-specific newsletters (AI, technology, business, design, etc.). They organize their inbox by routing subscriptions into named folders using their email client's built-in rules — one folder per topic. They want a faster way to get the signal from a folder without opening each newsletter individually.

**Technical comfort:** Comfortable using a web interface and managing their email inbox — creating folders, setting up filters, and routing newsletter subscriptions. No coding, server administration, or configuration file editing is expected. The tool is pre-configured by the developer before the user ever interacts with it.

**Where the user experience begins:** After the tool is deployed and configured, the user opens a web page. From there, their workflow is entirely within the UI: select a folder, optionally set a date range, and trigger a digest. All email access, deduplication, and backend behavior is handled transparently.

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
| Extract story items from HTML newsletter emails | ✅ In Scope |
| Logic filter to remove boilerplate/housekeeping content (not valid short stories) | ✅ In Scope |
| Detect near-duplicate stories across newsletters using body-text embeddings (within-run only) | ✅ In Scope |
| Select one representative story item per cluster | ✅ In Scope |
| LLM binary keep/drop filter on deduplicated items | ✅ In Scope |
| Output deduplicated story items sorted by date (oldest first) | ✅ In Scope |
| Manual on-demand digest generation from the UI | ✅ In Scope |
| Folder selection via preset shortcut buttons (UI convenience only) and free-text input | ✅ In Scope |
| Display story list in the UI | ✅ In Scope |
| Download digest as PDF | ✅ In Scope |
| Simple loading state during digest generation | ✅ In Scope |
| Email access via pre-configured IMAP credentials (internal, not user-facing) | ✅ In Scope |
| Standalone deployable frontend (portfolio-compatible) | ✅ In Scope |

### Out of Scope — Deferred to Phase 2+

| Feature | Status | Notes |
|---|---|---|
| Scheduled automatic digest generation | ❌ Phase 2 | |
| Email delivery of digest | ❌ Phase 2 | |
| Cross-run deduplication | ❌ Phase 2 | Dedup across previous digest runs using persisted embeddings |
| Importance / priority ranking of stories | ❌ Phase 2 | |
| OAuth2 authentication (Gmail, Outlook) | ❌ Phase 2 | Aligned with multi-user support |
| Multiple folder configurations per run | ❌ Phase 2 | |
| Multiple user accounts | ❌ Phase 2 | |
| Runtime configuration via UI | ❌ Phase 2 | |
| Real-time progress streaming via SSE | ❌ Phase 2 | MVP uses a simple loading state instead |
| Digest history — browsing past runs | ❌ Future | |
| Topic-level thematic grouping (beyond story-level dedup) | ❌ Future | |
| Browser extension or email client plugin | ❌ Future | |
| Mobile app | ❌ Future | |
| RSS/Atom feed input (non-email) | ❌ Future | |
| Per-newsletter analytics or statistics | ❌ Future | |

---

## 5. User Stories

### US-01: Manual Digest Generation
**As a newsletter reader, I want to enter a folder name, optionally set a date range, and click "Generate Digest," so that I get a deduplicated list of unique stories without opening each newsletter individually.**

Example: User opens the app, clicks the "AI" shortcut button (which populates the folder input with `AI Newsletters`), sets the date range to the past 3 days, and clicks Generate. The app fetches 12 newsletter emails from that period, deduplicates them, and returns a list of 18 unique story items — each with its original title, body text, link, date, and source newsletter name — sorted oldest to newest.

---

### US-02: Any Folder at Runtime
**As a user, I want to enter any folder name at runtime, so that I can generate a digest for any of my newsletter folders without reconfiguring the app.**

Example: User has folders named "AI Newsletters," "Design Weekly," and "Fintech." They can run a digest on any of these by typing the folder name into the input field — or using a preset shortcut if one matches — then clicking Generate. Switching folders on the next run requires no configuration change.

---

### US-03: Date Range Selection
**As a user returning from a few days away, I want to set a specific date range so that I can see stories from a period I missed.**

Example: User was offline March 10–16. They set the date range to March 10–16 and click Generate. The system processes all newsletter emails from that window, deduplicates within that set, and returns a list of unique stories covering the full period, sorted oldest to newest.

---

### US-04: Deduplication Across Sources
**As a user who subscribes to multiple newsletters on the same topic, I want stories that appear in multiple newsletters to be surfaced only once, so that I don't read the same announcement several times.**

Example: Four newsletters all mention the same product launch. The digest shows one item for that story — selected from whichever newsletter provided the most complete version — with its original text, link, date, and source newsletter name.

---

### US-05: Source Links and Attribution Preserved
**As a user who wants to read the full article, I want each story item to include the original link and source newsletter name, so that I can click through when something catches my attention.**

Example: A story item shows: the original title, body text excerpt, source newsletter "TLDR AI," publication date, and a link to the story.

---

### US-06: Loading Feedback During Generation
**As a user who triggered a digest, I want a clear loading state while it generates, so that I know the system is working and have not accidentally submitted twice.**

Example: After clicking Generate, the button disables and a loading indicator appears. When the digest is ready, the indicator disappears and the story list renders in place.

---

### US-07: PDF Download
**As a user who wants to save or share a digest, I want to download it as a PDF, so that I have a portable copy outside the browser.**

Example: After the story list renders in the UI, user clicks "Download PDF." A formatted PDF opens or downloads with the story items — title, body, date, and source link — laid out cleanly for reading.

---

## 6. Core Architecture & Patterns

### Architecture Overview

The system follows a linear pipeline architecture. Each stage receives data from the previous and passes results forward. The API layer exposes this pipeline to the frontend via a trigger endpoint that runs the pipeline synchronously and returns the completed story list in a single response.

```
Email Inbox (IMAP)
        │
        ▼
 Ingestion Layer         — connect, filter by folder + date range, fetch emails
        │
        ▼
 Extraction Layer        — parse MIME, HTML→text, segment story items, extract links and dates
        │
        ▼
 Logic Filter Layer      — remove boilerplate/housekeeping sections (not short valid stories)
        │
        ▼
 LLM Noise Filter        — Claude pre-cluster structural noise removal (maximally conservative)
        │
        ▼
 Deduplication Layer     — embed body text (threshold=0.55), cluster by semantic similarity (within-run);
                           LLM pairwise refinement within clusters (same_story / related_but_distinct / different);
                           select one representative item per final cluster
        │
        ▼
 LLM Editorial Filter    — Claude binary keep/drop on deduplicated representatives (haiku, low-cost)
        │
        ▼
 Storage Layer           — SQLite stores the most recent digest output
        │
        ▼
 API Layer (FastAPI)     — trigger endpoint (sync response), digest retrieval, PDF export
        │
        ▼
 Frontend (Vanilla JS)   — folder selection, date range, generate button, output view, PDF download
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
│   └── email_parser.py         # MIME parsing, HTML→text, story segmentation, metadata extraction
│
├── processing/
│   ├── __init__.py
│   ├── embedder.py             # sentence-transformers encoding + community_detection clustering
│   ├── deduplicator.py         # Cluster → representative story item selection
│   └── digest_builder.py       # Orchestrates full pipeline; returns story list JSON
│
├── ai/
│   ├── __init__.py
│   └── claude_client.py        # Anthropic SDK — binary keep/drop filter prompt + tool-use schema
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
- **Synchronous pipeline response:** `digest_builder.py` runs the full pipeline and returns the completed story list JSON. The frontend shows a loading state while the request is in flight; the result renders when the response arrives.
- **Folder name is the only input:** The backend receives a single folder name string and reads it directly. Preset shortcuts in the UI are hardcoded in the frontend for convenience; they carry no special meaning to the backend.
- **Stateless within-run dedup:** Embeddings are computed at runtime and held in memory during the pipeline run. Nothing is written to the database for dedup purposes.
- **Extracted, not generated:** Story text comes from the original newsletter. The pipeline selects and filters — it does not rewrite, summarize, or invent content.
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

**Purpose:** Parse raw MIME emails into structured story records suitable for deduplication.

**Operations:**
- Parse multipart MIME with Python `email.message_from_bytes` using `policy.default`
- Prefer `text/plain` parts; fall back to `text/html` (the common case for newsletters)
- Pre-process HTML with BeautifulSoup: strip `<img>`, `<style>`, `<script>`, and hidden pre-header elements
- Convert cleaned HTML to readable text using `html2text` (preserves hyperlinks, removes images)
- Segment the email body into individual story items using structural heuristics (blank line boundaries, horizontal rule tags, repeated heading patterns)
- For each story item, extract: title (first line/heading if present, may be absent), body text, link (first substantive hyperlink in the item, may be absent), newsletter name (from sender), and date (email received date)

**Pitfall handling:**
- HTML-only emails (no `text/plain` part) — handled by HTML fallback, which is the default path
- `quoted-printable` and `base64` encoding — decoded automatically by `policy.default`
- Invisible pre-header text (white-on-white, `display:none`, `font-size:0`) — stripped by BeautifulSoup pre-pass
- Tracking pixel `<img>` tags — removed before html2text conversion

**Story record shape:**
```json
{
  "title": "string or null",
  "body": "string",
  "link": "string or null",
  "newsletter": "string",
  "date": "YYYY-MM-DD"
}
```

Title and link are optional — untitled items and link-free items are valid story records and are not dropped.

---

### Feature 3: Logic Filter

**Purpose:** Remove sections of newsletter emails that are clearly boilerplate or housekeeping content — not story items — before embedding and deduplication.

**What is removed:**
- Unsubscribe footers and legal notices
- "Manage preferences," "View in browser," "Forward this email" sections
- Sponsor call-to-action blocks that contain no substantive content (e.g., "Click here to learn more")
- Repeated newsletter branding headers with no story content

**What is NOT removed:**
- Short valid stories — legitimate items that are only one sentence or a few words plus a link. Story brevity is not a filter criterion.
- Sponsor content that constitutes a genuine story or announcement (descriptive text about a product, report, or event)
- Items that happen to contain link text resembling a CTA if the surrounding body text is substantive

**Implementation approach:** Rule-based heuristics on section structure and anchor text patterns. No minimum body length. When in doubt, preserve the item — false positives (keeping noise) are caught by the downstream LLM filter; false negatives (dropping valid stories) are unrecoverable.

---

### Feature 4: Story-Level Deduplication (Within-Run)

**Purpose:** Identify when multiple newsletters cover the same event and select one representative story item per cluster.

**Scope:** Deduplication operates only across the story items extracted in the current run. No comparison against prior runs. Embeddings are held in memory and discarded after the run completes.

**Deduplication signal:** Body text is the primary signal. Two items describe the same story when their body text is semantically similar — not based on title match or link match, which can differ across newsletters even for identical stories.

**Operations:**
- Encode each story item's body text using `sentence-transformers` (`all-MiniLM-L6-v2`, 22MB, CPU-compatible)
- Run `util.community_detection` at cosine similarity threshold `0.55` (high-recall grouping) to form candidate clusters
- For each cluster containing more than one story, run an LLM pairwise refinement pass (`refine_clusters`): compare all C(n,2) pairs with a three-way classification — `same_story`, `related_but_distinct`, or `different`. Only `same_story` pairs are merged (union-find within the cluster). Fail-open: if the API call fails, the original embedding cluster is kept intact.
- From each final cluster, select one representative item

**Representative selection order** (applied in order; earlier criteria take priority):
1. **Longest body text** — the item with the most complete extracted body
2. **Has title** — if tied on body length, prefer items that have a title over those that do not
3. **Real content URL** — if still tied, prefer items whose link resolves to a content page rather than a tracking redirect

**Cross-date handling:** All items from the full date range are pooled into a single deduplication pass. If the same story appears in newsletters on different dates within the run, the cluster's representative is selected by the criteria above — but the date field on the output item is always the earliest date among all items in that cluster, preserving chronological context.

**What "same story" means:** Two items are merged if they describe the same specific event or announcement (same funding round, same product release, same regulatory ruling). Two different articles about a broad shared theme (e.g., "AI regulation") that address distinct developments remain separate items.

---

### Feature 4a: LLM Noise Filter (Pre-Cluster)

**Purpose:** Remove obvious structural non-article content from parsed story items before embedding — capturing noise that the rule-based logic filter may miss.

**What is removed:** Sponsor blocks, referral/referral-incentive prompts, newsletter intros/outros, polls, standalone CTAs, subscription management text.

**What is NOT removed:** Any item that might be a real story. The filter is maximally conservative — when in doubt, keep. False positives (keeping structural noise) are caught by the downstream editorial filter; false negatives (removing valid stories) are unrecoverable at this stage.

**Model:** `claude-haiku-4-5`. Batch size: 30. Fail-open: if the API call fails, all stories in that batch are kept.

---

### Feature 5: LLM Editorial Filter (Post-Dedup)

**Purpose:** Apply a binary judgment pass using Claude to catch housekeeping noise, navigation sections, and low-signal content that slipped past the earlier filters.

**Model:** `claude-haiku-4-5` (default). Configurable via `CLAUDE_MODEL` in `.env`.

**Input:** Each deduplicated representative story item's body text (and title if present).

**Output:** `KEEP` or `DROP` for each item. No generated text, no rewriting.

**What LLM drops:**
- Items that consist entirely of navigation links, menu structures, or index pages with no story content
- Repeated boilerplate that pattern-based logic missed
- Items with no intelligible content after extraction

**What LLM does NOT drop:**
- Short valid stories (even one-sentence items are kept if they contain genuine story content)
- Sponsor content with substantive descriptions
- Items the LLM finds surprising, niche, or unfamiliar — uncertainty defaults to KEEP

**Development-only behavior:** During development, the LLM may produce verbose reasoning about borderline items. This reasoning is captured in server logs at DEBUG level. No flagging output appears in production API responses — the response contains only the kept story items.

---

### Feature 6: Folder Selection

**Purpose:** Let the user specify which IMAP folder to read for a given digest run.

**How it works:**
- The UI provides a text input for the folder name, which is always the primary control
- Preset shortcut buttons (e.g., "AI," "News," "Tech") are hardcoded in the frontend as a typing convenience — clicking one populates the folder name input with a suggested value that the user can accept or edit
- Presets carry no special meaning to the backend; they are purely a frontend affordance
- The user can change which folder they read on any run without any reconfiguration
- Only one folder is processed per run

**No validation of folder existence before submission** — if the folder does not exist on the server, the generate endpoint returns a clear error that is displayed in the UI.

---

### Feature 7: PDF Export

**Purpose:** Allow the user to download the current digest as a formatted PDF for offline reading or sharing.

**Implementation:** Server-side PDF generation using `weasyprint` (HTML→PDF). The story list JSON is rendered into an HTML template server-side, then converted to PDF. The endpoint streams the PDF bytes with `Content-Type: application/pdf` and `Content-Disposition: attachment`.

**Endpoint:** `GET /api/digests/{digest_id}/pdf`

**PDF content:** All story items in date order — title (if present), body text, source newsletter, date, and link (printed as URL text for accessibility in printed form).

**Alternative if weasyprint has dependency issues:** `reportlab` (pure Python, no system dependencies) as a fallback, generating a simpler but fully portable PDF.

---

### Feature 8: Loading State During Generation

**Purpose:** Keep the user informed that the system is working while the digest generates.

**Mechanism:** The frontend disables the Generate button and shows a loading indicator immediately on form submission. The `POST /api/digests/generate` endpoint runs the full pipeline synchronously and returns the completed story list (or an error) in a single HTTP response. When the response arrives, the loading state clears and the list renders — or an error message is displayed.

**Frontend behavior:**
- Generate button transitions to a disabled "Generating…" state on click
- A loading indicator (`<progress>` element in indeterminate mode, styled by Pico.css) appears below the button
- On success: loading clears, story list renders in the output area
- On error: loading clears, a human-readable error message appears in the output area (e.g., "Folder 'AI Newsletters' was not found. Check your folder name and try again.")

**Note:** Real-time step-by-step progress streaming via SSE is deferred to Phase 2.

---

## 8. Technology Stack

### Backend

| Technology | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Runtime |
| FastAPI | 0.115+ | Web framework, API routing |
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
| anthropic | 0.40+ | Claude API SDK (async client) — binary keep/drop filter only |
| sentence-transformers | 3.x | Semantic embeddings for within-run dedup |
| torch (CPU only) | 2.x | Required by sentence-transformers; CPU install sufficient |

### Frontend

| Technology | Version | Purpose |
|---|---|---|
| Pico.css | 2.x | Semantic classless CSS framework |
| marked.js | 13.x | Markdown rendering (CDN import) |
| Vanilla JS (ES2022) | — | State management, form handling, rendering |
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
MAX_EMAILS_PER_RUN=50
DEDUP_THRESHOLD=0.55
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
Trigger digest generation. Pipeline runs synchronously; returns the completed story list on completion.

**Request:**
```json
{
  "folder": "AI Newsletters",
  "date_start": "2026-03-10",
  "date_end": "2026-03-17"
}
```

**Response (200 OK):**
```json
{
  "id": "a3f2c1d8-...",
  "generated_at": "2026-04-01T09:14:00Z",
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
  "generated_at": "2026-04-01T09:14:00Z",
  "folder": "AI Newsletters",
  "date_start": "2026-03-10",
  "date_end": "2026-03-17",
  "story_count": 18,
  "stories": [
    {
      "title": "OpenAI Releases GPT-5 with Multimodal Reasoning",
      "body": "OpenAI launched GPT-5 on March 14, 2026, introducing native multimodal reasoning across text, images, and audio. The model is available via API immediately...",
      "link": "https://openai.com/blog/gpt-5",
      "newsletter": "TLDR AI",
      "date": "2026-03-14"
    },
    {
      "title": null,
      "body": "Google DeepMind published Gemini 2.0 Ultra benchmarks showing SOTA on MMLU.",
      "link": "https://deepmind.google/research/gemini",
      "newsletter": "Import AI",
      "date": "2026-03-15"
    }
  ]
}
```

**Story item shape:**
| Field | Type | Notes |
|---|---|---|
| `title` | `string \| null` | First heading/line of the item, if present. Untitled items have `null`. |
| `body` | `string` | Extracted body text of the story item. |
| `link` | `string \| null` | First substantive content URL from the item, if present. |
| `newsletter` | `string` | Source newsletter name (from email sender). |
| `date` | `string` | Publication date in `YYYY-MM-DD` format. For cross-source duplicates, this is the earliest date in the cluster. |

Stories are sorted oldest date first.

---

#### `GET /api/digests/{digest_id}/pdf`
Generate and stream a PDF of the specified digest.

**Response:** `Content-Type: application/pdf`, `Content-Disposition: attachment; filename="digest-2026-04-01.pdf"`

---

### Utility Endpoints

#### `GET /api/health`
Returns `{"status": "ok"}`.

---

## 11. Success Criteria

### MVP Success Definition

The MVP is successful when a user can open the web interface, select a newsletter folder, trigger a digest, and receive a deduplicated list of story items that correctly eliminates near-duplicate coverage across newsletters, preserves each item's original text and source link, and is downloadable as a PDF. A loading state is shown while the pipeline runs; the result appears when it completes. Email credentials and backend configuration are set once by the developer and are never part of the user-facing experience.

### Functional Requirements

| Requirement | Status |
|---|---|
| ✅ Connect to any IMAP server with host, port, username, and app password | Required |
| ✅ Read all emails from the specified folder within the selected date range | Required |
| ✅ Extract readable story items from HTML-only newsletter emails | Required |
| ✅ Logic filter removes boilerplate without dropping valid short stories | Required |
| ✅ Detect and merge items covering the same event; retain one representative per cluster | Required |
| ✅ LLM binary filter removes any remaining non-story items without affecting valid short items | Required |
| ✅ Output story list is sorted oldest-date-first with date as a field on each item | Required |
| ✅ Show a loading state (disabled button + progress indicator) while digest generates | Required |
| ✅ Display completed story list in the UI | Required |
| ✅ Allow download of the current digest as a PDF | Required |
| ✅ UI provides a folder name input and optional preset shortcut buttons (hardcoded in the frontend) | Required |
| ✅ UI includes a date range selector (start and end date inputs) | Required |
| ✅ Frontend works as a standalone deployable page | Required |
| ✅ App runs as a single `uvicorn` process with no external services | Required |

### Quality Indicators

- Digest generation for 10 emails completes in under 60 seconds
- Semantic dedup correctly identifies the same story from two different newsletters at least 90% of the time during manual testing
- No valid short story (single sentence, one-liner roundup item) is dropped by the logic filter or LLM filter
- No newsletter in the date range is silently skipped — all failures are surfaced as error responses and displayed in the UI
- The UI is usable on a 1280px viewport without horizontal scrolling

### User Experience Goals

- A user who opens the web interface for the first time can generate a digest without any instructions
- All controls (folder, date range, generate button) are visible without scrolling
- The loading indicator is visible immediately after clicking Generate
- The digest is scannable — a user should be able to assess 18 story items in under 5 minutes

---

## 12. Implementation Phases

### Phase 1: Core Pipeline
**Goal:** A working end-to-end pipeline as a runnable script. No web server, no UI.

**Deliverables:**
- ✅ `config.py` — Pydantic BaseSettings, `.env` loading, startup validation
- ✅ `database.py` — SQLite schema (digest_runs table only), async engine, Alembic baseline
- ✅ `ingestion/imap_client.py` — IMAP connection, read-only folder selection, date range search, batched fetch
- ✅ `ingestion/email_parser.py` — MIME parsing, BeautifulSoup pre-processing, html2text conversion, story segmentation, link and date extraction
- ✅ `processing/embedder.py` — sentence-transformers encoding (in-memory), community_detection clustering
- ✅ `processing/deduplicator.py` — cluster → representative story item selection (longest body → has title → real content URL)
- ✅ `ai/claude_client.py` — three LLM functions: `filter_noise` (pre-cluster noise removal), `refine_clusters` (pairwise three-way dedup refinement), `filter_stories` (editorial binary keep/drop)
- ✅ `processing/digest_builder.py` — 7-stage pipeline: fetch → parse → noise filter → embed/cluster (0.55) → pairwise dedup refinement → select representative → LLM editorial filter → store; returns completed story list JSON
- ✅ CLI entry point: `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-10 --end 2026-03-17`

**Validation:** Run against a real newsletter folder with at least two overlapping newsletters. Confirm at least one pair of near-duplicate items is merged into one. Confirm no valid short story was dropped. Confirm the full story list JSON is printed and written to the database.

---

### Phase 2: API
**Goal:** Wrap the pipeline in FastAPI. Expose it via HTTP with a synchronous request/response pattern.

**Deliverables:**
- ✅ `main.py` — FastAPI app, StaticFiles mount, router registration
- ✅ `api/digests.py` — `POST /api/digests/generate` (runs pipeline, returns completed story list), `GET /api/digests/latest`
- ✅ `api/health.py` — health check
- ✅ Digest result written to `digest_runs` table on completion; status is `complete` or `failed`
- ✅ Error handling: IMAP failures and Claude API failures return structured error JSON with human-readable messages

**Validation:** Use `curl` or HTTPie to trigger a digest. Confirm the response contains the full story list JSON with `title`, `body`, `link`, `newsletter`, `date` fields. Confirm `GET /api/digests/latest` returns the same result. Confirm error cases return a readable error message.

---

### Phase 3: Frontend & PDF Export
**Goal:** A complete, usable tool in a browser. The frontend is portfolio-ready.

**Deliverables:**
- ✅ `static/index.html` — single-page shell with Pico.css, semantic layout
- ✅ `static/app.js` — form state management; `POST` trigger; loading state (disabled button + progress indicator); `marked.js` story list rendering; error display
- ✅ Folder name text input with optional preset shortcut buttons (hardcoded in the frontend); shortcuts populate the input on click
- ✅ Date range inputs (native `<input type="date">` pair with client-side start≤end validation)
- ✅ Generate button (disabled while in progress)
- ✅ Loading indicator shown while request is in flight; clears on success or error
- ✅ Story list rendered as cards — title (or untitled placeholder), body text, source newsletter, date, and link
- ✅ "Download PDF" button — calls `GET /api/digests/{id}/pdf`
- ✅ `api/export.py` — PDF generation via weasyprint from story list JSON
- ✅ `localStorage` persistence for last-used folder selection and date range
- ✅ `Dockerfile` for single-container deployment

**Validation:** Open in browser. Type a real folder name (or click a preset shortcut), set date range, click Generate — confirm the button disables and loading indicator appears. When complete, story list renders with title, body, date, newsletter, and link for each item. Click Download PDF and confirm output. Verify untitled items render without breaking the layout. Test an invalid folder name and confirm a readable error appears. Verify the page loads cleanly at 1280px and 768px.

---

### Phase 4: Polish & Deployment Readiness
**Goal:** Make the tool robust enough for daily personal use and clean enough for portfolio presentation.

**Deliverables:**
- ✅ Error messages in the UI are human-readable (folder not found, API key invalid, no emails in range)
- ✅ Empty state when no digest has been generated yet (clear prompt to generate first digest)
- ✅ `.env.example` with all keys, placeholder values, and inline documentation comments
- ✅ `README.md` with 5-step quick start, `.env` reference, and deployment instructions
- ✅ Frontend reviewed for portfolio quality: consistent spacing, clean typography, no visible rough edges
- ✅ Manual test against at least 3 different newsletter types to validate extraction and dedup quality
- ✅ Tune dedup threshold based on real results from user's actual newsletter folder

---

## 13. Future Considerations

### Phase 2 Additions (Planned)

- **Real-time progress streaming** — Server-Sent Events (SSE) replacing the simple loading state; the frontend receives step-by-step pipeline updates as the digest generates
- **Scheduled digest generation** — APScheduler with a configurable cron expression; runs the pipeline automatically and saves the result
- **Email delivery** — SMTP digest delivery (HTML + plain text fallback)
- **Cross-run deduplication** — persist story embeddings in SQLite across digest runs; detect when a new email covers a story already seen in a prior run
- **Multiple folder configurations per run** — process two or more folders in a single digest run
- **Multiple user accounts** — per-user configuration and digest history; aligned with OAuth2 authentication

### Later Additions

- **Digest history** — browse and re-read past runs from a history panel in the UI
- **Importance ranking** — rank stories by significance within the category and reorder accordingly
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
**Risk:** Newsletter HTML varies across platforms (Substack, Beehiiv, ConvertKit, Mailchimp). Poor extraction means the digest surfaces noise instead of content.

**Mitigation:** `html2text` handles the majority of newsletters well. BeautifulSoup pre-processing removes the most common noise patterns. Log the character count of extracted text per email during the pipeline run — extractions under 200 characters are flagged as suspected parse failures in server logs. Phase 4 includes manual testing against at least 3 different newsletter platforms.

---

### Risk 3: Claude API Cost
**Risk:** The LLM filter step adds API cost per run. A user processing a large backlog could see unexpected costs.

**Mitigation:** Default model is `claude-haiku-4-5` (significantly cheaper than Sonnet). The filter call is lightweight — binary keep/drop judgments only, no generation. Add a configurable `MAX_EMAILS_PER_RUN` in `.env` (default: 50) that caps a single digest run. Log token usage per run in `digest_runs` so the user can monitor costs.

---

### Risk 4: Deduplication False Positives
**Risk:** The embedding clustering threshold (0.55) may group stories that are actually distinct. The LLM pairwise refinement step provides a second check, but a poorly tuned threshold increases LLM cost and the chance of a false same_story classification.

**Mitigation:** Threshold is configurable via `DEDUP_THRESHOLD=0.55` in `.env`. The LLM pairwise refinement layer (`refine_clusters`) catches false groupings at the cluster level: `related_but_distinct` and `different` pairs are not merged, even if the embedding clustered them together. Log cluster sizes — clusters with more than 5 members are logged as warnings for manual inspection. Phase 4 includes threshold tuning based on real results from the user's actual newsletters.

---

### Risk 5: Logic Filter Over-Aggressiveness
**Risk:** The logic filter might inadvertently remove valid short stories or roundup items that pattern-match boilerplate signals.

**Mitigation:** The filter operates on section structure and explicit boilerplate patterns — not on body length or word count. Short items are never a filter criterion. When uncertain, the filter preserves the item. LLM filter is the safety net for genuine noise. Phase 1 validation explicitly checks that no valid short story was dropped.

---

### Risk 6: weasyprint System Dependencies
**Risk:** weasyprint requires system-level libraries (Pango, Cairo, GLib) that may not be available on all deployment targets.

**Mitigation:** Use the official weasyprint Docker base image or install system dependencies in the Dockerfile explicitly. If system dependency installation proves problematic, fall back to `reportlab` for pure-Python PDF generation.

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
    output_json   TEXT                     -- Full story list as JSON string
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
| `anthropic` | Claude API SDK (binary filter) |
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
| 2 | Body-text embeddings are a reliable deduplication signal across newsletters covering the same story | High | Validate against real newsletter pairs in Phase 1 |
| 3 | `claude-haiku-4-5` binary keep/drop judgment is accurate enough for MVP filtering without missing valid short stories | Medium | Test with short roundup items in Phase 1 |
| 4 | The user's newsletter folders contain only newsletters (email rules route them reliably) | High | User confirmed |
| 5 | Blank-line and horizontal-rule heuristics are sufficient for story segmentation within typical newsletter emails | Medium | Test against real newsletters in Phase 1; refine if needed |
| 6 | Embedding threshold of 0.55 + LLM pairwise refinement produces accurate dedup results for the user's newsletter mix | Medium | Tune threshold in Phase 4 based on actual results; adjust LLM prompt if same_story precision is low |
| 7 | weasyprint can be installed cleanly on the target deployment environment | Medium | Validate during Phase 3 Dockerfile build; fall back to reportlab if not |
