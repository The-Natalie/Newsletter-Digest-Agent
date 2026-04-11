# Feature: phase2-loop3-frontend

The following plan should be complete, but it's important that you validate documentation and codebase patterns and task sanity before you start implementing.

Pay special attention to CDN URLs, DOM element IDs, and API field names — they must match exactly between index.html, app.js, and the backend JSON.

## Feature Description

Implement the complete single-page browser UI for the Newsletter Digest Agent. Three static files replace/create the frontend: `static/index.html` (complete rewrite of the placeholder), `static/style.css` (new), and `static/app.js` (new). The UI allows the user to enter an IMAP folder name, choose a date range, trigger digest generation, see a loading indicator during the synchronous pipeline run, and view the deduplicated story list rendered as styled cards. A Download PDF button calls the existing export endpoint. localStorage persists the last-used folder and date range across page loads. On page load the UI attempts to restore the previous digest via GET /api/digests/latest.

## User Story

As a newsletter reader
I want to open a browser, type my folder name and date range, click Generate, and see a clean list of deduplicated stories
So that I can quickly catch up on what matters without reading every newsletter individually

## Problem Statement

The backend pipeline and all API endpoints are fully implemented. The `static/` directory contains only a placeholder HTML file. There is no user interface.

## Scope

- In scope: `static/index.html`, `static/style.css`, `static/app.js` — complete frontend implementation
- Out of scope: backend changes, new API routes, Dockerfile (Phase 4), SSE streaming (Phase 4), digest history (deferred), multi-user (deferred)

## Solution Statement

Write three static files (no build step) using Pico.css v2 for layout and form styling, marked.js for markdown-to-HTML story body rendering, and vanilla JS for all state management, fetch calls, and DOM updates. The Generate button triggers `POST /api/digests/generate`; on success the story list renders as `<article>` cards. A PDF link is updated with the returned digest ID for direct download. localStorage keys persist form values across sessions.

## Feature Metadata

**Feature Type**: New Capability
**Estimated Complexity**: Medium
**Primary Systems Affected**: `static/index.html`, `static/style.css`, `static/app.js`
**Dependencies**: Pico.css v2 (CDN), marked.js (CDN) — no npm, no build step
**Assumptions**:
- All API endpoints (`POST /api/digests/generate`, `GET /api/digests/latest`, `GET /api/digests/{id}/pdf`) are working (verified in Phase 2 Loops 1–2)
- `main.py` already mounts `StaticFiles(directory="static", html=True)` as the last route — no changes needed
- Story `body` text has already been normalized by `_normalize_body` in the pipeline — rendering via `marked.parse()` is appropriate
- `title` and `link` in story items may be `null` — must render gracefully

---

## CONTEXT REFERENCES

### Relevant Codebase Files — MUST READ BEFORE IMPLEMENTING

- `static/index.html` — Why: Current placeholder; overwrite entirely
- `main.py` — Why: Confirms StaticFiles mount is last; no backend changes needed. `html=True` means GET / serves `index.html`.
- `api/digests.py` — Why: Exact request schema (`folder`, `date_start`, `date_end`) and response shape; `source_count` is present in response
- `api/export.py` (lines 254–279) — Why: PDF endpoint URL pattern `GET /api/digests/{digest_id}/pdf` and response headers
- `processing/digest_builder.py` (lines 207–228) — Why: Response dict has `id`, `generated_at`, `folder`, `date_start`, `date_end`, `story_count`, `stories[]` with keys `title`, `body`, `link`, `links`, `newsletter`, `date`, `source_count`
- `tests/test_api.py` — Why: Confirms API validation rules (empty folder → 422, reversed dates → 422, pipeline error → 500) that the frontend must handle gracefully
- `tests/test_export.py` — Why: Confirms PDF endpoint returns 200 with `content-type: application/pdf` and `content-disposition: attachment`

### New Files to Create

- `static/index.html` — Complete rewrite of placeholder; single-page shell
- `static/style.css` — New; Pico.css overrides for story cards, meta text, error state, presets bar, PDF button placement
- `static/app.js` — New; all UI logic — init, localStorage, form submit, fetch, loading state, story rendering, PDF link, error display

### No New Test Files Required

`tests/test_api.py` and `tests/test_export.py` already cover all backend routes used by the frontend. Frontend-only JS logic is validated manually (see Manual Validation section). No pytest tests needed for static files.

### Relevant Documentation

- Pico.css v2 docs: https://picocss.com/docs/
  - Sections: Container, Grid, Forms, Button, Article, Progress, classless
  - Why: Semantic HTML elements map directly to styled components; need to know which tags to use for cards, loading, grid layout
- Pico.css v2 Forms: https://picocss.com/docs/forms.html
  - Why: `<label>` wrapping `<input>` produces styled form fields; `role="group"` groups buttons
- marked.js docs: https://marked.js.org/
  - Why: `marked.parse(text)` API; default renderer is safe for markdown from trusted server output
- MDN localStorage: https://developer.mozilla.org/en-US/docs/Web/API/Window/localStorage
  - Why: `getItem`/`setItem` pattern; keys are strings; values are strings

---

## Patterns to Follow

### API Response Error Handling

Two error formats exist (from `api/digests.py` and FastAPI validation):

```javascript
// Pydantic validation error (422):
// { "detail": [{"msg": "...", "loc": [...], "type": "..."}] }

// Application error (500):
// { "error": "IMAP failed" }

// Both must be handled:
const data = await response.json();
const msg = data.error || (Array.isArray(data.detail) ? data.detail[0].msg : data.detail) || 'Unknown error.';
```

### Null Story Fields (from CLAUDE.md)

`title` and `link` are nullable — untitled items and link-free items are valid and must not cause rendering errors:

```javascript
const title = story.title || '(untitled)';
// Conditional link:
story.link ? `<a href="${escapeHtml(story.link)}">Read more →</a>` : ''
```

### marked.js Usage (from CLAUDE.md)

Story body is rendered via `marked.parse()`. Do **not** use raw `innerHTML` for title or link — those must be escaped. Body goes through `marked.parse()` which is the intended use pattern per CLAUDE.md:

```javascript
// CORRECT — body via marked.parse
bodyEl.innerHTML = marked.parse(story.body || '');

// CORRECT — title via text content or escapeHtml in innerHTML template
titleEl.textContent = story.title || '(untitled)';
```

### localStorage Keys

Use consistent keys across init and save:

```javascript
const LS_FOLDER = 'digest_folder';
const LS_DATE_START = 'digest_date_start';
const LS_DATE_END = 'digest_date_end';
```

### Pico.css v2 Semantic Patterns

- Cards: `<article>` with `<header>`, body content, optional `<footer>`
- Loading: `<progress>` with no `value` attribute = indeterminate (Pico styles automatically)
- Error text: `<p class="error">` or Pico's built-in `aria-invalid` attribute on inputs
- Grid: `<div class="grid">` — equal-width columns at desktop, stacks on mobile
- Container: `<main class="container">` — centered, max-width, padding
- Button group: `<div role="group">` — renders buttons flush with no gap

### Fetch Pattern (from test_api.py patterns)

```javascript
const resp = await fetch('/api/digests/generate', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ folder, date_start: start, date_end: end }),
});
```

---

## IMPLEMENTATION PLAN

### Phase 1: HTML Shell

Build the complete semantic HTML structure. All interactive elements need IDs that `app.js` will reference. No JS in this phase.

**Tasks:**
- Write `static/index.html` with Pico.css v2 CDN link, marked.js CDN script, and `app.js` script
- Include all form fields, preset buttons, loading indicator, results section, error element

### Phase 2: CSS Overrides

Pico.css handles almost everything. Only override what Pico doesn't provide: story card spacing, meta text size/colour, preset buttons row, results header layout.

**Tasks:**
- Write `static/style.css` with focused overrides (< 60 lines)

### Phase 3: JavaScript Logic

All UI behaviour. Init → localStorage → page-load fetch → form submit → loading → render → error.

**Tasks:**
- Write `static/app.js` with init, event listeners, fetch handlers, render functions, localStorage save/restore

---

## STEP-BY-STEP TASKS

### TASK 1: CREATE static/index.html

**IMPLEMENT**: Complete rewrite of the placeholder. Full semantic HTML with Pico.css v2 via CDN.

**HTML structure** (implement exactly as specified):

```html
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Newsletter Digest</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <main class="container">
    <header>
      <h1>Newsletter Digest</h1>
      <p class="subtitle">Generate a deduplicated digest from your newsletters.</p>
    </header>

    <section id="form-section">
      <form id="digest-form">
        <label for="folder">
          Folder
          <input type="text" id="folder" name="folder" placeholder="AI Newsletters" autocomplete="off" required>
        </label>

        <div id="presets" role="group">
          <button type="button" class="outline secondary" data-folder="AI Newsletters">AI Newsletters</button>
          <button type="button" class="outline secondary" data-folder="Tech">Tech</button>
          <button type="button" class="outline secondary" data-folder="Finance">Finance</button>
        </div>

        <div class="grid">
          <label for="date-start">
            From
            <input type="date" id="date-start" name="date_start" required>
          </label>
          <label for="date-end">
            To
            <input type="date" id="date-end" name="date_end" required>
          </label>
        </div>

        <p id="form-error" class="form-error" aria-live="polite" hidden></p>

        <button type="submit" id="generate-btn">Generate Digest</button>
      </form>
    </section>

    <progress id="loading" aria-label="Generating digest…" hidden></progress>

    <section id="results" hidden>
      <div id="results-header">
        <hgroup>
          <h2 id="results-title"></h2>
          <p id="results-meta" class="results-meta"></p>
        </hgroup>
        <a id="pdf-link" href="#" role="button" class="outline secondary" target="_blank">
          Download PDF
        </a>
      </div>
      <div id="story-list"></div>
    </section>
  </main>

  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <script src="app.js"></script>
</body>
</html>
```

**GOTCHA**: `<progress>` with no `value` attribute is Pico's indeterminate state — do NOT add a `value` attribute.
**GOTCHA**: `StaticFiles(html=True)` in main.py serves index.html for GET / — no routing changes needed.
**GOTCHA**: Script tags at end of body — `app.js` must come AFTER marked.js CDN tag so `marked` global is available.
**GOTCHA**: `data-theme="light"` on `<html>` locks Pico to light mode; remove if dark mode support is desired later.

**VALIDATE**: `python -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('static/index.html').read()); print('HTML parses OK')"` (run from project root)

---

### TASK 2: CREATE static/style.css

**IMPLEMENT**: Minimal Pico.css overrides. Pico handles layout, forms, buttons, articles, and progress automatically. Only add what Pico doesn't provide.

```css
/* Presets button row */
#presets {
  margin-bottom: var(--pico-spacing);
}

#presets button {
  font-size: 0.85rem;
  padding: 0.25rem 0.75rem;
}

/* Form error */
.form-error {
  color: var(--pico-color-red-550);
  font-size: 0.9rem;
  margin-top: calc(var(--pico-spacing) * -0.5);
}

/* Results header: title+meta left, PDF button right */
#results-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  margin-bottom: var(--pico-spacing);
  flex-wrap: wrap;
}

#results-header hgroup {
  margin: 0;
}

#results-header hgroup h2 {
  margin: 0;
}

.results-meta {
  color: var(--pico-muted-color);
  font-size: 0.9rem;
  margin: 0.25rem 0 0;
}

/* Story cards — Pico styles <article> automatically */
/* Add only spacing and meta colour tweaks */
#story-list article {
  margin-bottom: 0;
}

#story-list article header {
  margin-bottom: 0.5rem;
  padding-bottom: 0;
  border-bottom: none;
}

#story-list article header h3 {
  margin: 0 0 0.2rem;
  font-size: 1.1rem;
}

.story-meta {
  color: var(--pico-muted-color);
  font-size: 0.85rem;
  margin: 0;
}

.story-body {
  font-size: 0.95rem;
  line-height: 1.6;
}

/* Remove extra top margin from first paragraph in body */
.story-body > p:first-child {
  margin-top: 0;
}

/* Progress bar spacing */
#loading {
  margin: var(--pico-spacing) 0;
}

/* Subtitle */
header .subtitle {
  color: var(--pico-muted-color);
}
```

**GOTCHA**: Pico.css v2 uses CSS custom properties (`--pico-spacing`, `--pico-muted-color`, etc.) — use these for consistency, not hardcoded values.
**GOTCHA**: Pico v2 styles `<article>` as a card automatically — do NOT add custom `.card` classes.
**GOTCHA**: `<hgroup>` in Pico v2 renders h2 and p together as a group — use this for results title + meta.

**VALIDATE**: `python -c "import os; assert os.path.exists('static/style.css'), 'missing'; print('style.css exists')"` (run from project root)

---

### TASK 3: CREATE static/app.js

**IMPLEMENT**: All UI logic. Implement the full file as specified below.

```javascript
'use strict';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LS_FOLDER = 'digest_folder';
const LS_DATE_START = 'digest_date_start';
const LS_DATE_END = 'digest_date_end';

// ---------------------------------------------------------------------------
// DOM references — all IDs defined in index.html
// ---------------------------------------------------------------------------

const form = document.getElementById('digest-form');
const folderInput = document.getElementById('folder');
const dateStartInput = document.getElementById('date-start');
const dateEndInput = document.getElementById('date-end');
const generateBtn = document.getElementById('generate-btn');
const loadingEl = document.getElementById('loading');
const resultsEl = document.getElementById('results');
const resultsTitleEl = document.getElementById('results-title');
const resultsMetaEl = document.getElementById('results-meta');
const storyListEl = document.getElementById('story-list');
const pdfLinkEl = document.getElementById('pdf-link');
const formErrorEl = document.getElementById('form-error');

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

/**
 * Escape a string for safe insertion into HTML attribute values or text nodes.
 * Used for title, link href, newsletter name — NOT for story body (that goes
 * through marked.parse which handles its own escaping).
 */
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Get today's date as YYYY-MM-DD string in local time.
 */
function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/**
 * Get a date N days before today as YYYY-MM-DD string in local time.
 */
function daysAgoStr(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// ---------------------------------------------------------------------------
// Error display
// ---------------------------------------------------------------------------

function showError(msg) {
  formErrorEl.textContent = msg;
  formErrorEl.hidden = false;
}

function clearError() {
  formErrorEl.textContent = '';
  formErrorEl.hidden = true;
}

// ---------------------------------------------------------------------------
// Loading state
// ---------------------------------------------------------------------------

function setLoading(on) {
  generateBtn.disabled = on;
  generateBtn.setAttribute('aria-busy', on ? 'true' : 'false');
  generateBtn.textContent = on ? 'Generating…' : 'Generate Digest';
  loadingEl.hidden = !on;
  if (on) {
    resultsEl.hidden = true;
  }
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

/**
 * Render a single story item as an <article> element.
 * - title: nullable — show "(untitled)" placeholder
 * - body: rendered via marked.parse (markdown-aware)
 * - link: nullable — omit footer if absent
 * - newsletter + date: shown as meta line
 */
function renderStory(story) {
  const article = document.createElement('article');

  const titleText = escapeHtml(story.title || '(untitled)');
  const metaText = `${escapeHtml(story.newsletter || '')} &middot; ${escapeHtml(story.date || '')}`;
  const bodyHtml = marked.parse(story.body || '');

  let footerHtml = '';
  if (story.link) {
    footerHtml = `<footer>
      <a href="${escapeHtml(story.link)}" target="_blank" rel="noopener noreferrer">Read more →</a>
    </footer>`;
  }

  article.innerHTML = `
    <header>
      <h3>${titleText}</h3>
      <p class="story-meta">${metaText}</p>
    </header>
    <div class="story-body">${bodyHtml}</div>
    ${footerHtml}
  `;

  return article;
}

/**
 * Render a complete digest response into the results section.
 */
function renderDigest(data) {
  resultsTitleEl.textContent = `${data.folder || 'Digest'}`;
  resultsMetaEl.textContent =
    `${data.date_start} to ${data.date_end} · ${data.story_count} ${data.story_count === 1 ? 'story' : 'stories'}`;

  pdfLinkEl.href = `/api/digests/${encodeURIComponent(data.id)}/pdf`;

  storyListEl.innerHTML = '';

  if (!data.stories || data.stories.length === 0) {
    storyListEl.innerHTML = '<p>No stories found for this period.</p>';
  } else {
    data.stories.forEach(story => {
      storyListEl.appendChild(renderStory(story));
    });
  }

  resultsEl.hidden = false;
}

// ---------------------------------------------------------------------------
// Form submit handler
// ---------------------------------------------------------------------------

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  clearError();

  const folder = folderInput.value.trim();
  const dateStart = dateStartInput.value;
  const dateEnd = dateEndInput.value;

  // Client-side date order validation (mirrors server-side)
  if (dateStart > dateEnd) {
    showError('Start date must be on or before end date.');
    return;
  }

  // Persist to localStorage before the request
  localStorage.setItem(LS_FOLDER, folder);
  localStorage.setItem(LS_DATE_START, dateStart);
  localStorage.setItem(LS_DATE_END, dateEnd);

  setLoading(true);

  try {
    const resp = await fetch('/api/digests/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder, date_start: dateStart, date_end: dateEnd }),
    });

    const data = await resp.json();

    if (!resp.ok) {
      // Handle both {"error": "..."} and FastAPI {"detail": [...]} shapes
      let msg = data.error;
      if (!msg && data.detail) {
        msg = Array.isArray(data.detail) ? data.detail[0].msg : String(data.detail);
      }
      showError(msg || `Server error (${resp.status}).`);
      return;
    }

    renderDigest(data);
  } catch (err) {
    showError('Network error — is the server running?');
  } finally {
    setLoading(false);
  }
});

// ---------------------------------------------------------------------------
// Preset buttons
// ---------------------------------------------------------------------------

document.querySelectorAll('#presets [data-folder]').forEach(btn => {
  btn.addEventListener('click', () => {
    folderInput.value = btn.dataset.folder;
    folderInput.focus();
  });
});

// ---------------------------------------------------------------------------
// Init: localStorage restore + load latest digest
// ---------------------------------------------------------------------------

function init() {
  // Restore last-used folder and date range from localStorage
  const savedFolder = localStorage.getItem(LS_FOLDER);
  const savedStart = localStorage.getItem(LS_DATE_START);
  const savedEnd = localStorage.getItem(LS_DATE_END);

  folderInput.value = savedFolder || '';
  dateStartInput.value = savedStart || daysAgoStr(7);
  dateEndInput.value = savedEnd || todayStr();

  // Attempt to restore previous digest from database
  loadLatestDigest();
}

async function loadLatestDigest() {
  try {
    const resp = await fetch('/api/digests/latest');
    if (resp.ok) {
      const data = await resp.json();
      renderDigest(data);
    }
    // 404 = no prior digest — expected on first run, silently skip
  } catch {
    // Server unreachable during local dev — silently skip
  }
}

// Boot
init();
```

**GOTCHA**: `escapeHtml` is applied to `title`, `newsletter`, `date`, and `link` (in href) — these go into `innerHTML` via template literals and must be escaped. Story `body` goes through `marked.parse()` only.
**GOTCHA**: Use local-time date math (`d.setDate(...)`) not UTC — `toISOString()` returns UTC midnight which can produce yesterday's date in negative-offset timezones.
**GOTCHA**: `encodeURIComponent(data.id)` in the PDF href — digest IDs are UUIDs (safe), but defensive encoding prevents breakage if an unusual ID appears.
**GOTCHA**: `loadLatestDigest()` failure (404 or network error) must be swallowed silently — the page must be functional on first run.
**GOTCHA**: `setLoading(false)` is in `finally` — it must run even when `showError` is called after a non-OK response.
**GOTCHA**: `generateBtn.setAttribute('aria-busy', ...)` is Pico's pattern for showing a spinner inside the button — it requires the button to have `aria-busy="true"` not just `disabled`.

**VALIDATE**: `python -c "import os; assert os.path.exists('static/app.js'), 'missing'; print('app.js exists')"` (run from project root)

---

## TESTING STRATEGY

### No New Automated Tests for Frontend

The frontend is pure static HTML/CSS/JS with no server-side logic. All existing backend tests remain the validation authority for the API surface the frontend calls.

Existing test coverage that validates the frontend's API contract:
- `tests/test_api.py` — 8 tests covering POST /generate (valid, missing field, invalid dates, empty folder, pipeline error) and GET /latest (no data, returns stored digest)
- `tests/test_export.py` — 7 tests covering GET /{id}/pdf (200, 404, 500, fallback)
- `tests/test_normalize_body.py` — 31 tests ensuring story body text normalisation

### Manual Validation (see checklist below)

Browser-based testing covers: form UX, loading state, story rendering, untitled/linkless items, PDF download, error display, localStorage persistence, responsive layout.

---

## VALIDATION COMMANDS

### Level 1: Syntax Checks

```bash
# Verify all three files exist
python -c "
import os
for f in ['static/index.html', 'static/style.css', 'static/app.js']:
    assert os.path.exists(f), f'MISSING: {f}'
    print(f'OK: {f}')
"

# Verify index.html contains expected structural IDs
python -c "
html = open('static/index.html').read()
ids = ['digest-form', 'folder', 'date-start', 'date-end', 'generate-btn',
       'loading', 'results', 'results-title', 'results-meta', 'story-list',
       'pdf-link', 'form-error', 'presets']
for id in ids:
    assert f'id=\"{id}\"' in html, f'MISSING id: {id}'
    print(f'Found: #{id}')
"

# Verify app.js references all expected IDs
python -c "
js = open('static/app.js').read()
ids = ['digest-form', 'folder', 'date-start', 'date-end', 'generate-btn',
       'loading', 'results', 'results-title', 'results-meta', 'story-list',
       'pdf-link', 'form-error']
for id in ids:
    assert f\"'{id}'\" in js or f'\"{id}\"' in js, f'MISSING in app.js: {id}'
    print(f'Found in JS: {id}')
"
```

### Level 2: Full Test Suite (no regressions)

```bash
python -m pytest tests/ -q
```

Expected: all tests pass (no regressions from frontend changes — backend untouched).

### Level 3: Server Boots and Serves Static Files

```bash
# Verify server starts cleanly (exits immediately — just checks import)
python -c "from main import app; print('main.py imports OK')"

# Verify static files are reachable via TestClient
python -c "
import sys, os
sys.path.insert(0, '.')
from fastapi.testclient import TestClient
from main import app
client = TestClient(app)
r = client.get('/')
assert r.status_code == 200, f'Expected 200, got {r.status_code}'
assert 'text/html' in r.headers.get('content-type', ''), 'Expected HTML'
assert 'Newsletter Digest' in r.text, 'Title not found in index.html'
print('GET / → 200 OK, HTML, title present')
"
```

### Level 4: Manual Browser Validation

Start the server:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Then complete the manual verification checklist below.

---

## MANUAL VERIFICATION CHECKLIST

- [ ] Page loads at http://localhost:8000 — shows header, form, no story list (unless prior digest exists)
- [ ] Preset buttons ("AI Newsletters", "Tech", "Finance") populate the folder input on click
- [ ] localStorage restores last-used folder and date range after page refresh
- [ ] Client-side validation: start date after end date shows error message without submitting
- [ ] Generate button disables + shows "Generating…" during request
- [ ] Indeterminate `<progress>` bar is visible during request
- [ ] After successful generation: stories render as cards with title, meta line (newsletter · date), body text, and optional "Read more →" link
- [ ] Untitled story (null title) shows "(untitled)" placeholder without layout breakage
- [ ] Story without link (null link) shows no footer/link without layout breakage
- [ ] Markdown in story body (bullets, bold, headings) renders as formatted HTML, not raw `**text**`
- [ ] "Download PDF" button link points to `/api/digests/{id}/pdf` and triggers browser PDF download
- [ ] API error (e.g. invalid folder that doesn't exist on IMAP) displays a readable error message below the form
- [ ] Page loads and shows previous digest immediately on refresh (GET /api/digests/latest)
- [ ] Layout is readable at 1280px viewport width
- [ ] Layout is readable at 768px viewport width (single-column on mobile)

---

## ROLLBACK CONSIDERATIONS

- All changes are limited to `static/` — no backend, no database, no migrations
- Rollback: restore `static/index.html` to placeholder, delete `static/style.css` and `static/app.js`
- No data migrations required

## ACCEPTANCE CRITERIA

- [ ] `static/index.html`, `static/style.css`, `static/app.js` all exist and contain full implementations
- [ ] All existing tests pass (`python -m pytest tests/ -q`)
- [ ] Server boots (`python -c "from main import app"`)
- [ ] `GET /` returns 200 HTML containing "Newsletter Digest"
- [ ] All 15 manual verification checklist items confirmed
- [ ] Story body markdown renders correctly (not raw markers)
- [ ] Null title renders as "(untitled)" — does not break layout
- [ ] Null link story renders without footer — does not break layout
- [ ] Error response (500) from pipeline displays human-readable message
- [ ] localStorage persists folder and date range across page refresh

---

## COMPLETION CHECKLIST

- [ ] All tasks completed in order
- [ ] Level 1–3 validation commands pass
- [ ] Full test suite passes with no regressions
- [ ] Manual browser testing confirms all checklist items
- [ ] Acceptance criteria all met

---

## NOTES

### Pico.css v2 vs v1

This plan uses Pico v2 (`@picocss/pico@2`). Key v2 differences from v1:
- `data-theme` attribute replaces `prefers-color-scheme` toggle
- `hgroup` renders h2+p as a unit
- CSS custom properties are `--pico-*` (not `--color`)
- `role="group"` on a div wrapping buttons renders them flush

### marked.js Security Note

Story body is content extracted by the server pipeline from newsletters the user controls (their own inbox). `marked.parse()` is used per CLAUDE.md: "Story list output is rendered via marked.js. Do not use raw innerHTML for untrusted content." Title, newsletter, date, and link fields are escaped via `escapeHtml()` before being interpolated into innerHTML template strings. Body goes only through `marked.parse()`. If future requirements include user-generated content, add DOMPurify: `DOMPurify.sanitize(marked.parse(text))`.

### Preset Buttons

The three presets ("AI Newsletters", "Tech", "Finance") are hardcoded convenience shortcuts. They have no backend representation — they only populate the folder text input. Users customize them by editing `index.html` directly (per CLAUDE.md: "Preset shortcut buttons in the frontend are hardcoded HTML/JS convenience").

### PDF Download

`<a id="pdf-link" href="..." target="_blank">` is the simplest reliable approach. The browser handles the download via the `Content-Disposition: attachment` header the server returns. No JS blob fetch needed.

### source_count Field

The story response includes `source_count` (number of deduplicated sources). This plan does not render it to keep the card clean for MVP. It can be added as a small badge (e.g., "2 sources") in Phase 4 polish.

### Date Defaults

If no localStorage values exist, the form defaults to the past 7 days. Date math uses local time (not UTC `toISOString()`) to avoid off-by-one errors in negative UTC-offset timezones.

---

## VALIDATION OUTPUT REFERENCE

### Level 1: File existence check

- Item to check:
  `python -c "import os\nfor f in ['static/index.html', 'static/style.css', 'static/app.js']:\n    assert os.path.exists(f), f'MISSING: {f}'\n    print(f'OK: {f}')"`
  Expected output or result:
  ```
  OK: static/index.html
  OK: static/style.css
  OK: static/app.js
  ```

- Item to check:
  ID presence check in index.html (full command in Level 1 block above)
  Expected output or result:
  13 lines of `Found: #<id>` with no AssertionError

- Item to check:
  ID presence check in app.js (full command in Level 1 block above)
  Expected output or result:
  13 lines of `Found in JS: <id>` with no AssertionError

### Level 2: Test suite

- Item to check:
  `python -m pytest tests/ -q`
  Expected output or result:
  All tests passing — output ends with `X passed` (no failures, no errors). Count should be ≥ 160 (all pre-existing tests).

### Level 3: Server static serving

- Item to check:
  `python -c "from main import app; print('main.py imports OK')"`
  Expected output or result:
  ```
  main.py imports OK
  ```

- Item to check:
  TestClient GET / check (full command in Level 3 block above)
  Expected output or result:
  ```
  GET / → 200 OK, HTML, title present
  ```

### Manual Verification Items

- Item to check:
  Page loads at http://localhost:8000 — shows header, form, no story list (unless prior digest exists)
  Expected output or result:
  Browser shows "Newsletter Digest" heading and form with folder input, date inputs, preset buttons, Generate button visible.

- Item to check:
  Preset buttons populate the folder input on click
  Expected output or result:
  Clicking "AI Newsletters" fills the folder text input with "AI Newsletters".

- Item to check:
  localStorage restores last-used folder and date range after page refresh
  Expected output or result:
  After submitting a form, refreshing the page shows the previously entered folder name and dates pre-filled.

- Item to check:
  Client-side validation: start date after end date shows error
  Expected output or result:
  Setting start = 2026-04-10, end = 2026-04-01 and clicking Generate shows a red error message "Start date must be on or before end date." — no network request made.

- Item to check:
  Generate button state during request
  Expected output or result:
  Button shows "Generating…" and is disabled; indeterminate progress bar is visible below the form.

- Item to check:
  Stories render as cards after successful generation
  Expected output or result:
  Each story appears as a Pico card with: story title (or "(untitled)"), newsletter name · date in muted text, formatted body text, optional "Read more →" link.

- Item to check:
  Untitled story (null title) renders without layout breakage
  Expected output or result:
  Card shows "(untitled)" in place of h3 title — no empty heading, no JS error.

- Item to check:
  Story without link renders without footer
  Expected output or result:
  Card shows no "Read more" footer section — no empty link, no JS error.

- Item to check:
  Markdown in story body renders as formatted HTML
  Expected output or result:
  Bullet points appear as `<ul><li>` elements, bold text renders as `<strong>`, not as raw `**text**`.

- Item to check:
  "Download PDF" button triggers PDF download
  Expected output or result:
  Clicking the link opens a PDF file download in the browser (or opens a new tab with PDF content) with filename `digest-YYYY-MM-DD.pdf`.

- Item to check:
  API error displays readable message
  Expected output or result:
  Submitting a non-existent folder (after pipeline fails) shows a human-readable error message below the form, not a raw JSON blob.

- Item to check:
  Previous digest restored on page refresh
  Expected output or result:
  After generating a digest and refreshing, the story list appears immediately without needing to regenerate.

- Item to check:
  Layout at 1280px viewport
  Expected output or result:
  Form fields and story cards display in a readable layout, no horizontal overflow.

- Item to check:
  Layout at 768px viewport
  Expected output or result:
  Date range inputs stack vertically (single column), story cards remain readable, no horizontal overflow.
