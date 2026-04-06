from __future__ import annotations

import email
import re
import email.utils
import logging
from dataclasses import dataclass, field
from datetime import datetime
from email import policy
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs

import html2text
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_NOISE_TAGS = {"img", "style", "script", "head"}
_HIDDEN_STYLE_PATTERNS = (
    "display:none",
    "display: none",
    "visibility:hidden",
    "visibility: hidden",
    "font-size:0",
    "font-size: 0",
    "color:#fff",
    "color:#ffffff",
    "color:white",
)
_HIDDEN_CLASS_KEYWORDS = ("preheader", "preview-text", "preview")

_BOILERPLATE_URL_FRAGMENTS = frozenset({
    "unsubscribe", "optout", "opt-out", "manage-subscription",
    "email-preference", "email-prefs", "email-settings",
})

# Exact-match anchor texts (normalised to lowercase) that indicate non-story links.
# Includes generic CTAs that are too ambiguous to assign to a specific story chunk.
_BOILERPLATE_ANCHORS = frozenset({
    # Unsubscribe / preferences
    "unsubscribe", "opt out", "opt-out",
    "manage preferences", "update preferences", "email preferences",
    # View / browser
    "view online", "view in browser", "view as web page", "view this email",
    "read online", "read in browser",
    # Legal / policy
    "privacy policy", "privacy notice",
    "terms of service", "terms of use", "terms & conditions",
    "all rights reserved",
    # Contact / admin
    "contact us", "forward to a friend",
    # Advertising
    "advertise", "advertise with us",
    "sponsored", "sponsor", "advertisement", "ad", "advertorial",
    "presented by", "powered by", "brought to you by",
    # Social platforms (icon links)
    "facebook", "twitter", "linkedin", "instagram", "youtube",
    "tweet this", "share on twitter", "share on facebook",
    "share", "tweet", "retweet", "pin", "pin it",
    # Navigation
    "subscribe", "home", "about", "archive", "archives", "blog", "newsletter",
    "back", "back to top", "next", "previous",
    # Generic CTAs — too ambiguous to assign to a specific story
    "read more", "learn more", "click here", "here", "more", "see more",
    "find out more", "get started", "sign up", "try now", "try for free",
    "try it free", "try it now", "buy now", "shop now", "download now",
})


# Substring patterns for anchor text that can't be enumerated exactly.
# Checked with `in` against lowercased anchor text. Keep entries specific enough
# to avoid false positives — each should unambiguously indicate a footer/admin link.
_BOILERPLATE_ANCHOR_SUBSTRINGS = (
    "your preferences",
    "your subscription",
    "your email preferences",
    "manage your email",
    "manage your subscriptions",
)

_SECTION_SPLIT_PATTERN = re.compile(r'\n{2,}|^\s*[-*_]{3,}\s*$', re.MULTILINE)
_MIN_SECTION_CHARS = 20     # low floor: skip only empty/whitespace sections; short valid story
                             # items must not be dropped here — the LLM filter handles noise
_MIN_LIST_ITEM_CHARS = 30   # lower threshold for individual bullet items (job listings etc.)
_MD_LINK_RE = re.compile(r'\[([^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*)\]\((https?://[^\)]+)\)')
_LIST_ITEM_START = re.compile(r'^\s*[\*\-]\s+', re.MULTILINE)

# Tracking/analytics query parameters stripped during URL normalization.
# utm_* prefix is handled separately (prefix match). Entries here are exact param names.
_TRACKING_PARAMS = frozenset({
    # Click IDs
    "fbclid", "gclid", "msclkid", "yclid", "twclid", "igshid",
    # Email platform tracking
    "mc_cid", "mc_eid",          # Mailchimp
    "_hsenc", "_hsmi",           # HubSpot
    "mkt_tok",                   # Marketo
    # Social / referral
    "li_fat_id",                 # LinkedIn
    "ref",                       # generic referral
})

# Base domains for social platform links — used by _is_boilerplate_url().
# Links to these domains within sections are structural (share buttons, profile icons),
# not story destinations. Stored as bare domains (no www. prefix).
_SOCIAL_DOMAINS = frozenset({
    "twitter.com", "x.com", "t.co",
    "facebook.com", "fb.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com", "youtu.be",
    "tiktok.com",
})

# Substrings that identify newsletter infrastructure segments — checked against lowercase text.
# These are sections whose sole purpose is managing the subscription system, referral
# growth, legal/footer boilerplate, or email navigation. They contain no content value
# for the reader and are not story candidates.
#
# Deliberately excluded: sponsor labels ("together with", "brought to you by"), sign-offs
# ("thanks for reading"), interactive sections ("before you go", "a quick poll"), and all
# other content-adjacent signals. Those are content-level judgments — the LLM filter
# decides keep/drop for them. This list is restricted to structural/infrastructure signals
# that are never story content under any circumstances.
_BOILERPLATE_SEGMENT_SIGNALS = (
    # Subscription management / preferences
    "manage your subscriptions",
    "manage your email",
    "update your email preferences",
    "email preferences or unsubscribe",
    "don't unsubscribe",
    "free subscriber to",
    "currently a free subscriber",
    "support this newsletter",
    "all rights reserved",
    # Referral / audience growth systems
    "referral link",
    # Navigation / sharing infrastructure
    "forward this email",
    "share this newsletter",
    "recommend this newsletter",
    # Newsletter intro / table-of-contents headers
    "in today's issue",
    "in this issue",
    "what's inside",
    "today's top stories",
    # Newsletter intro — contains ToC signals; structural navigation not story content
    "in today's newsletter",
)


def _normalize_url(url: str) -> str:
    """Strip tracking parameters and normalize URL for deduplication.

    - Removes utm_* parameters and known tracking params (_TRACKING_PARAMS).
    - Lowercases scheme and host.
    - Strips trailing slash from path (preserves bare '/').
    - Drops the fragment (#section) — two links to the same page with different
      anchors are treated as the same destination.

    Returns the original url unchanged on any parse error.
    """
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=False)
        filtered = {
            k: v for k, v in params.items()
            if not k.startswith("utm_") and k not in _TRACKING_PARAMS
        }
        clean_query = urlencode(filtered, doseq=True)
        path = parsed.path.rstrip("/") or "/"
        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.params,
            clean_query,
            "",  # strip fragment
        ))
    except Exception:
        return url


def _is_boilerplate_url(url: str) -> bool:
    """Return True if this URL points to a navigation/infrastructure destination.

    Used within content sections where anchor text is not a reliable signal —
    inline story links often have generic anchor text ('read more', 'here') and
    must not be filtered. Only URL structure and destination domain are checked.

    Checks:
    - Email management URL fragments (unsubscribe, preferences, etc.)
    - Social platform domains (share buttons, profile icons)
    """
    url_lower = url.lower()
    if any(fragment in url_lower for fragment in _BOILERPLATE_URL_FRAGMENTS):
        return True
    try:
        netloc = urlparse(url).netloc.lower()
        bare = netloc[4:] if netloc.startswith("www.") else netloc
        if bare in _SOCIAL_DOMAINS:
            return True
    except Exception:
        pass
    return False


def _is_boilerplate_link(url: str, anchor_text: str) -> bool:
    """Return True if this link is a boilerplate footer/navigation link, not a story link."""
    url_lower = url.lower()
    anchor_lower = anchor_text.lower().strip()
    if any(fragment in url_lower for fragment in _BOILERPLATE_URL_FRAGMENTS):
        return True
    if anchor_lower in _BOILERPLATE_ANCHORS:
        return True
    if any(sub in anchor_lower for sub in _BOILERPLATE_ANCHOR_SUBSTRINGS):
        return True
    return False


@dataclass
class StoryRecord:
    title: str | None    # first #-heading or **bold** title; None if absent
    body: str            # section text without the title line; primary dedup signal
    links: list[str]     # all non-boilerplate URLs from the section; empty list if none
    newsletter: str      # sender display name or email address
    date: str            # YYYY-MM-DD; empty string if email Date header missing/unparseable
    source_count: int = field(default=1)
    # source_count: set to 1 by parse_emails(); updated to len(cluster) by deduplicate().
    # A value > 1 means this record was selected as representative from N duplicate story items.


def _is_boilerplate_segment(text: str) -> bool:
    """Return True if this text segment is sponsor or shell content, not a news story."""
    # Normalize Unicode smart apostrophes/quotes → ASCII before signal matching.
    # TDV and other newsletters use U+2019 RIGHT SINGLE QUOTATION MARK in phrases
    # like "IN TODAY'S NEWSLETTER" which would otherwise not match the ASCII signal.
    text_lower = (
        text
        .replace('\u2018', "'")   # LEFT SINGLE QUOTATION MARK
        .replace('\u2019', "'")   # RIGHT SINGLE QUOTATION MARK
        .replace('\u201c', '"')   # LEFT DOUBLE QUOTATION MARK
        .replace('\u201d', '"')   # RIGHT DOUBLE QUOTATION MARK
        .lower()
    )
    return any(signal in text_lower for signal in _BOILERPLATE_SEGMENT_SIGNALS)


def _is_table_artifact(clean_text: str) -> bool:
    """Return True if text is a formatting artifact rather than story content.

    Detects email template table rows where pipe characters dominate — e.g.
    '| | | | March 17, 2026 | Read online'. These are layout elements that
    survive the _MIN_SECTION_CHARS floor but contain no story content.

    Threshold: pipe chars > 15% of all non-whitespace characters.
    """
    non_ws = re.sub(r'\s', '', clean_text)
    if not non_ws:
        return True
    return non_ws.count('|') / len(non_ws) > 0.15


_SPARSE_LINK_STRIP_RE = re.compile(r'\[([^\]]*)\]\([^\)]+\)|[\d\.\-\*\#\:\s]')


def _is_sparse_link_section(raw_sec: str, links: list[dict]) -> bool:
    """Return True if this section is a link list (ToC, preview) with minimal prose.

    Detects sections where the text outside link syntax consists only of list
    markers and whitespace — i.e. the section IS the links, with no prose around
    them. Requires at least 3 links to avoid false-positives on short story items
    that happen to have minimal surrounding text.

    Does not affect story sections with inline links — those always have
    substantial prose outside the link anchors.
    """
    if len(links) < 3:
        return False
    # Strip all link syntax (including empty anchors) and list markers/whitespace
    bare = _SPARSE_LINK_STRIP_RE.sub('', raw_sec)
    return len(bare) < 30


_LEADING_PIPE_RE = re.compile(r'^\|\s*')


def _strip_leading_pipe(text: str) -> str:
    """Strip a leading table-cell '|' artifact from section text.

    Newsletter email HTML uses table-based layout. When html2text converts
    a table cell, it may emit '|  ' at the start of the cell's content.
    This strips that prefix so downstream filters and title detection work
    on the actual content text.

    Only strips if the text starts with '|' followed by optional spaces.
    A line that is ONLY '|' (with no content) is left for _is_table_artifact()
    to handle.
    """
    stripped = _LEADING_PIPE_RE.sub('', text, count=1)
    return stripped if stripped.strip() else text


def _is_story_heading(text: str) -> bool:
    """Return True if the section contains a story-level heading within its first two
    non-empty lines.

    Checks the FIRST non-empty line, then the SECOND non-empty line if the first is
    not a heading. The two-line check handles the category-label-then-heading pattern
    used in TDV-style newsletters, where html2text trailing-space artifacts (`  \\n  \\n`)
    fuse a sponsor/category label line and the following `# heading` into one section.

    A story-level heading is a bare '#'-prefixed line (not bold-wrapped).

    - '# Nvidia builds the tech stack for the robotics era' → True
    - '# Nvidia builds...\\n\\n| [](image-url)' → True (first line is story heading)
    - 'GTC COVERAGE BROUGHT TO YOU BY IREN\\n\\n# Unleashing NVIDIA...' → True
    - '# **Headlines & Launches**' → False (bold-wrapped category label)
    - '# **TLDR AI 2026-03-11**' → False (bold-wrapped newsletter title)
    - 'Paragraph text without a heading' → False
    """
    lines = [l for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return False

    def _is_bare_heading(line: str) -> bool:
        if not line.startswith('#'):
            return False
        heading_text = line.lstrip('#').strip()
        return not (heading_text.startswith('**') and heading_text.endswith('**') and len(heading_text) > 4)

    # Primary: first non-empty line is a # heading
    if _is_bare_heading(lines[0]):
        return True
    # Secondary: second non-empty line is a # heading (category-label-then-heading pattern)
    if len(lines) >= 2 and _is_bare_heading(lines[1]):
        return True
    return False


def _is_heading_only(text: str) -> bool:
    """Return True if text contains only markdown headings (lines starting with #).

    This is used to merge heading-only sections with the following body section,
    keeping headline + body + links together. Short non-heading lines (e.g. the
    '* * *' HR separators that html2text emits) are intentionally NOT treated as
    headings — they will be filtered out by _MIN_SECTION_CHARS instead.
    """
    lines = [l for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return True
    return all(l.startswith('#') for l in lines)


def _extract_title(text: str) -> tuple[str | None, str]:
    """Extract a heading title from section text.

    Detects two title formats on the first non-empty line:
    1. Markdown heading: line starts with '#'
    2. Bold title: entire line is '**title text**'

    If neither format is found on the first non-empty line, also checks the
    immediate next non-empty line for a '#' heading. This handles the
    category-label-then-heading pattern (e.g. TDV sponsor sections where
    "SPONSOR LABEL\\n\\n# Story Title" is fused into one section by html2text
    trailing-space artifacts). Pre-heading text is included at the start of
    the body.

    Returns (title_text, body_without_title).
    Returns (None, original_text) if no title is found.
    """
    lines = text.split("\n")
    first_content_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Format 1: markdown heading on first non-empty line
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            body = "\n".join(lines[i + 1:]).lstrip("\n").strip()
            return title or None, body
        # Format 2: bold title on first non-empty line
        if stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4:
            title = stripped[2:-2].strip()
            body = "\n".join(lines[i + 1:]).lstrip("\n").strip()
            return title or None, body
        # First non-empty line is not a heading — check the next non-empty line.
        first_content_idx = i
        break

    # Secondary scan: look for a # heading on the immediate next non-empty line
    # (category-label-then-heading pattern).
    if first_content_idx is not None:
        for j in range(first_content_idx + 1, len(lines)):
            stripped_j = lines[j].strip()
            if not stripped_j:
                continue
            if stripped_j.startswith("#"):
                heading_text = stripped_j.lstrip("#").strip()
                if not (heading_text.startswith("**") and heading_text.endswith("**") and len(heading_text) > 4):
                    pre_body = "\n".join(lines[:j]).strip()
                    post_body = "\n".join(lines[j + 1:]).lstrip("\n").strip()
                    body = (pre_body + "\n\n" + post_body).strip() if pre_body else post_body
                    return heading_text or None, body
            break  # Only check the immediate next non-empty line

    return None, text


def _collect_links(links: list[dict]) -> list[str]:
    """Return all normalized URLs from a section's filtered links list.

    The links list is already boilerplate-filtered by _extract_sections() — every
    entry is a non-boilerplate, non-social URL. All URLs are returned as a list.
    Returns an empty list if no links are present.
    """
    return [entry["url"] for entry in links]


def _split_list_section(sec: str) -> list[dict] | None:
    """Split a bullet-list section into per-item sub-sections with local links.

    Returns a list of per-item dicts (each with "text" and "links") when the section
    contains 2+ list items that each have their own distinct non-boilerplate link.
    Returns None otherwise — caller processes the section as a single unit.

    This prevents aggregator sections (quick links, product updates, job listings)
    from creating one chunk that carries links from multiple unrelated items. Each
    item becomes its own section so the correct link is always associated with the
    correct story text.

    Single-story sections — including sponsor articles with multiple links to the
    same destination — are unaffected because their items either share a URL or
    fewer than 2 items have their own link.
    """
    item_matches = list(_LIST_ITEM_START.finditer(sec))
    if len(item_matches) < 2:
        return None

    # Slice raw markdown for each item (from bullet marker end to next bullet start)
    items_raw: list[str] = []
    for idx, match in enumerate(item_matches):
        start = match.end()
        end = item_matches[idx + 1].start() if idx + 1 < len(item_matches) else len(sec)
        items_raw.append(sec[start:end].strip())

    # Build per-item dicts. Track linked_count separately so link-free items with
    # sufficient text are also included (e.g. a bullet with no hyperlink but valid prose).
    # The split is only returned when at least 2 items carry distinct links — this preserves
    # the invariant that splitting only occurs for genuine aggregator sections.
    result: list[dict] = []
    linked_count = 0
    for raw in items_raw:
        best_by_norm: dict[str, dict] = {}
        for anchor, url in _MD_LINK_RE.findall(raw):
            if _is_boilerplate_url(url):
                continue
            norm = _normalize_url(url)
            if not anchor:
                # Empty-anchor image link: collect URL if no named link already holds it.
                if norm not in best_by_norm:
                    best_by_norm[norm] = {"url": norm, "anchor_text": ""}
                continue
            if norm not in best_by_norm:
                best_by_norm[norm] = {"url": norm, "anchor_text": anchor}
            elif len(anchor) > len(best_by_norm[norm]["anchor_text"]):
                best_by_norm[norm]["anchor_text"] = anchor
        item_links = list(best_by_norm.values())
        clean_text = _MD_LINK_RE.sub(r'\1', raw).strip()
        if len(clean_text) >= _MIN_LIST_ITEM_CHARS:
            result.append({"text": clean_text, "links": item_links})
            if item_links:
                linked_count += 1

    return result if linked_count >= 2 else None


def _extract_sections(html_text: str) -> list[dict]:
    """Convert HTML to per-section dicts with clean prose text and local links.

    Uses html2text with ignore_links=False to produce markdown with inline
    [anchor](url) syntax. Splits at blank-line/HR boundaries, merges heading-only
    sections with the following section, extracts per-section links, strips link
    syntax from prose, and applies boilerplate filters.

    Returns:
        List of dicts: {"text": str (clean prose), "links": list[dict]}
        Only sections that pass boilerplate and length filters are included.
    """
    h = html2text.HTML2Text()
    h.ignore_links = False   # keep [anchor](url) inline so links stay with their section
    h.ignore_images = True
    h.body_width = 0
    h.unicode_snob = True
    md_text = h.handle(html_text)

    raw_sections = _SECTION_SPLIT_PATTERN.split(md_text)

    # Story reassembly: merge story headings with all following paragraph sections
    # until the next story heading, category heading, or boilerplate boundary.
    merged: list[str] = []
    i = 0
    while i < len(raw_sections):
        sec = raw_sections[i].strip()
        if not sec:
            i += 1
            continue

        if _is_story_heading(sec):
            # Collect this heading and all following non-heading, non-boilerplate sections
            story_parts = [sec]
            i += 1
            while i < len(raw_sections):
                next_sec = raw_sections[i].strip()
                if not next_sec:
                    i += 1
                    continue
                # Stop collecting at any heading (new story or category label).
                # _is_heading_only catches pure '#' sections and bold-wrapped category
                # headings. _is_story_heading catches TDV-style headings that include
                # an image link in the same section (# Heading\n\n| [](image-url)).
                if _is_heading_only(next_sec) or _is_story_heading(next_sec):
                    break
                # Stop collecting at structural noise only (table artifacts, short labels).
                # Content-judgment signals (sponsor labels, sign-offs) are intentionally NOT
                # break conditions — the LLM filter handles content keep/drop decisions.
                clean_next = _MD_LINK_RE.sub(r'\1', next_sec).strip()
                # Special case: section consists entirely of empty-anchor links — e.g.
                # [](article-url) from an <a href="url"><img ...></a> in TDV-style newsletters.
                # It carries no prose but holds the article image link URL. Include it in
                # story_parts so its URL is captured by the second-pass link extraction,
                # then keep collecting body paragraphs.
                if not clean_next and _MD_LINK_RE.search(next_sec):
                    story_parts.append(next_sec)
                    i += 1
                    continue
                if _is_table_artifact(clean_next):
                    break
                # Stop collecting at short structural labels (e.g. '| HARDWARE', '| ENTERPRISE').
                # These are theme/category labels that appear between sections and are below the
                # minimum section length. They fall through to the outer else branch and are then
                # dropped by the _MIN_SECTION_CHARS check in the second loop.
                if len(clean_next) < _MIN_SECTION_CHARS:
                    break
                story_parts.append(next_sec)
                i += 1
            merged.append("\n\n".join(story_parts))

        elif _is_heading_only(sec):
            # Category heading (bold-wrapped, e.g. '# **Headlines & Launches**') — drop it.
            # TLDR-style newsletters use these as section dividers; the following stories
            # each carry their own bold title and don't need the category context.
            # Pure '#'-heading sections that are story titles are caught by _is_story_heading()
            # before reaching this branch.
            i += 1

        else:
            merged.append(sec)
            i += 1

    sections: list[dict] = []
    for sec in merged:
        sec = sec.strip()
        if not sec:
            continue
        sec = _strip_leading_pipe(sec)        # strip table cell artifact prefix

        # Bullet-list aggregator detection: if the section contains 2+ list items
        # that each carry their own distinct link (product updates, job listings,
        # quick-links roundups), split into per-item sub-sections so each item's
        # link stays with only that item's text.
        list_items = _split_list_section(sec)
        if list_items is not None:
            for item in list_items:
                if not _is_boilerplate_segment(item["text"]):
                    sections.append(item)
            continue

        # Extract links from inline markdown syntax.
        # Normalize URLs before deduplication: strip tracking params, lowercase scheme/host.
        # When multiple links share the same normalized destination, keep the longest anchor text.
        # Empty-anchor links ([](url)) are image links — TDV article images are wrapped in
        # <a href="article-url"><img ...> which html2text renders as [](article-url). Collect
        # these so the article URL is not lost; a named link to the same URL takes priority.
        best_by_norm: dict[str, dict] = {}
        for anchor, url in _MD_LINK_RE.findall(sec):
            if _is_boilerplate_url(url):
                continue
            norm = _normalize_url(url)
            if not anchor:
                # Empty-anchor image link: only add if no entry already holds this URL.
                if norm not in best_by_norm:
                    best_by_norm[norm] = {"url": norm, "anchor_text": ""}
                continue
            if norm not in best_by_norm:
                best_by_norm[norm] = {"url": norm, "anchor_text": anchor}
            elif len(anchor) > len(best_by_norm[norm]["anchor_text"]):
                best_by_norm[norm]["anchor_text"] = anchor
        links = list(best_by_norm.values())

        if _is_sparse_link_section(sec, links):
            continue

        # Strip markdown link syntax to get clean prose
        clean_text = _MD_LINK_RE.sub(r'\1', sec).strip()

        if len(clean_text) < _MIN_SECTION_CHARS:
            continue
        if _is_table_artifact(clean_text):
            continue
        if _is_boilerplate_segment(clean_text):
            continue

        sections.append({"text": clean_text, "links": links})

    return sections


def _get_body_parts(msg) -> tuple[str | None, str | None]:
    """Return (plain_text, html_text) from an EmailMessage. Either may be None."""
    plain_part = msg.get_body(preferencelist=("plain",))
    html_part = msg.get_body(preferencelist=("html",))
    plain_text = plain_part.get_content() if plain_part is not None else None
    html_text = html_part.get_content() if html_part is not None else None
    return plain_text, html_text



def _strip_noise(soup: BeautifulSoup) -> None:
    """Remove noise elements from a BeautifulSoup tree in-place."""
    # Remove structural noise tags
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()

    # Collect hidden elements before decomposing (avoid modifying tree during iteration)
    to_remove = []
    for tag in soup.find_all(True):
        style = tag.get("style", "").lower().replace(" ", "")
        classes = " ".join(tag.get("class", [])).lower()
        if any(p.replace(" ", "") in style for p in _HIDDEN_STYLE_PATTERNS):
            to_remove.append(tag)
        elif any(k in classes for k in _HIDDEN_CLASS_KEYWORDS):
            to_remove.append(tag)
    for tag in to_remove:
        tag.decompose()


def _html_to_text(html_str: str) -> str:
    """Convert cleaned HTML to plain text using html2text."""
    h = html2text.HTML2Text()
    h.ignore_links = True    # links already extracted separately as structured data
    h.ignore_images = True   # images already stripped by BeautifulSoup
    h.body_width = 0         # no line wrapping (wrapping degrades embedding quality)
    h.unicode_snob = True    # use unicode characters, not ASCII approximations
    return h.handle(html_str)


def parse_emails(raw_messages: list[bytes]) -> list[StoryRecord]:
    """Parse raw MIME email bytes into a flat list of StoryRecord objects.

    Each record represents one story section extracted from one email. Sections are
    produced by _extract_sections() which handles HTML conversion, boilerplate filtering,
    and bullet-list splitting internally.

    Args:
        raw_messages: List of raw MIME email byte strings, as returned by fetch_emails().

    Returns:
        Flat list of StoryRecord instances. Emails with no extractable body or no
        sections are silently skipped. The list is ordered: all sections from the
        first email, then all sections from the second, etc.
    """
    results: list[StoryRecord] = []

    for raw in raw_messages:
        msg = email.message_from_bytes(raw, policy=policy.default)

        # Sender — prefer display name, fall back to email address
        display_name, addr = email.utils.parseaddr(msg.get("From", ""))
        newsletter = display_name.strip() if display_name.strip() else addr

        # Date — format as YYYY-MM-DD; empty string if header missing or unparseable
        date_formatted = ""
        date_str = msg.get("Date")
        if date_str:
            try:
                date_formatted = email.utils.parsedate_to_datetime(date_str).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                pass

        # Body extraction
        plain_text, html_text = _get_body_parts(msg)

        sections: list[dict] = []

        if plain_text is not None:
            # Extract sections from HTML part if available alongside plain text
            if html_text is not None:
                try:
                    sections = _extract_sections(html_text)
                except Exception:
                    sections = []
            # Plain-text-only emails produce no sections — skipped silently
        elif html_text is not None:
            soup = BeautifulSoup(html_text, "lxml")
            _strip_noise(soup)
            raw_body = _html_to_text(str(soup)).strip()
            if not raw_body:
                continue
            if len(raw_body) < 200:
                logger.warning(
                    "Short extraction (%d chars) for email from %s — possible parse failure",
                    len(raw_body),
                    newsletter,
                )
            try:
                sections = _extract_sections(html_text)
            except Exception:
                sections = []
        else:
            continue  # no body at all

        for section in sections:
            section_text = section.get("text", "").strip()
            if not section_text:
                continue
            section_text = section_text.replace('\xa0', ' ')   # normalize non-breaking spaces
            title, body = _extract_title(section_text)
            if not body.strip():
                body = section_text  # fallback: use full text if title stripped everything
            if _is_table_artifact(body):           # skip if title extraction left only structural noise
                continue
            # Strip leading and trailing table-artifact '|' lines from body text
            body = _strip_leading_pipe(body)
            # Strip '****' markdown artifacts: html2text renders empty <strong></strong> as '****'.
            # Four or more consecutive asterisks never appear in valid markdown (valid: **, *, ***).
            body = re.sub(r'\*{4,}', '', body)
            body = re.sub(r'(\s*\|)+\s*$', '', body).strip()
            # Strip trailing lines that are table artifacts (e.g. '| |  SUBSCRIBE') or
            # match the structural cell pattern '| |  TEXT' (pipe-ratio may be diluted in
            # full-body check but is clearly structural when isolated as the final line).
            body_lines = body.split('\n')
            while body_lines:
                last = body_lines[-1].strip()
                if last and (
                    _is_table_artifact(last)
                    or re.match(r'^\|[\s\|]+\S', last) is not None
                ):
                    body_lines.pop()
                else:
                    break
            body = '\n'.join(body_lines).strip()
            # Strip trailing whitespace from each line: html2text appends '  ' (two spaces)
            # before '\n' in table-cell content, producing '   \n' artifacts in body text.
            body = '\n'.join(line.rstrip() for line in body.split('\n'))
            if not body:                                         # skip if body is now empty
                continue
            links = _collect_links(section.get("links", []))
            results.append(StoryRecord(
                title=title,
                body=body,
                links=links,
                newsletter=newsletter,
                date=date_formatted,
            ))

    return results
