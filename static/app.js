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
  generateBtn.textContent = on ? 'Generating\u2026' : 'Generate Digest';
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
 * - links: all links shown as "Resources: Link 1 / Link 2 / …" (up to 5)
 * - newsletter + date: shown as meta line
 */
function renderStory(story) {
  const article = document.createElement('article');

  const titleText = escapeHtml(story.title || '(untitled)');
  const metaText = `${escapeHtml(story.newsletter || '')} &middot; ${escapeHtml(story.date || '')}`;
  const bodyHtml = marked.parse(story.body || '');

  // Build deduplicated link list — mirrors api/export.py logic
  const links = Array.isArray(story.links) ? [...story.links] : [];
  if (story.link && !links.includes(story.link)) {
    links.unshift(story.link);
  }

  let footerHtml = '';
  if (links.length > 0) {
    const items = links.map((url, i) =>
      `<li><a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">Link ${i + 1}</a></li>`
    ).join('');
    footerHtml = `<footer>
      <p class="resources-label">Resources:</p>
      <ul class="resources">${items}</ul>
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
  resultsTitleEl.textContent = data.folder || 'Digest';
  resultsMetaEl.textContent =
    `${data.date_start} to ${data.date_end} \u00b7 ${data.story_count} ${data.story_count === 1 ? 'story' : 'stories'}`;

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
    showError('Network error \u2014 is the server running?');
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
