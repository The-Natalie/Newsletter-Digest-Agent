from __future__ import annotations

import email
import email.utils
import logging
from dataclasses import dataclass, field
from datetime import datetime
from email import policy

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


def _is_boilerplate_link(url: str, anchor_text: str) -> bool:
    """Return True if this link is a boilerplate footer/navigation link, not a story link."""
    url_lower = url.lower()
    anchor_lower = anchor_text.lower().strip()
    if any(fragment in url_lower for fragment in _BOILERPLATE_URL_FRAGMENTS):
        return True
    if anchor_lower in _BOILERPLATE_ANCHORS:
        return True
    return False


@dataclass
class ParsedEmail:
    subject: str
    sender: str           # Display name from From header, or email address if no display name
    date: datetime | None # Parsed from Date header; None if missing or unparseable
    body: str             # Cleaned plain text; empty string if extraction failed
    links: list[dict] = field(default_factory=list)  # [{"url": "...", "anchor_text": "..."}]


def _get_body_parts(msg) -> tuple[str | None, str | None]:
    """Return (plain_text, html_text) from an EmailMessage. Either may be None."""
    plain_part = msg.get_body(preferencelist=("plain",))
    html_part = msg.get_body(preferencelist=("html",))
    plain_text = plain_part.get_content() if plain_part is not None else None
    html_text = html_part.get_content() if html_part is not None else None
    return plain_text, html_text


def _extract_links(soup: BeautifulSoup) -> list[dict]:
    """Extract all non-mailto hyperlinks with non-empty anchor text from a BeautifulSoup tree."""
    links = []
    for a in soup.find_all("a", href=True):
        url = a["href"].strip()
        if not url or url.startswith("mailto:"):
            continue
        anchor_text = a.get_text(strip=True)
        if anchor_text and not _is_boilerplate_link(url, anchor_text):
            links.append({"url": url, "anchor_text": anchor_text})
    return links


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


def parse_emails(raw_messages: list[bytes]) -> list[ParsedEmail]:
    """Parse raw MIME email bytes into structured ParsedEmail objects.

    Args:
        raw_messages: List of raw MIME email byte strings, as returned by fetch_emails().

    Returns:
        List of ParsedEmail instances. Emails with no extractable body are silently skipped.
    """
    results: list[ParsedEmail] = []

    for raw in raw_messages:
        msg = email.message_from_bytes(raw, policy=policy.default)

        # Subject — policy.default decodes RFC 2047 encoded headers automatically
        subject = msg.get("Subject", "") or ""

        # Sender — prefer display name, fall back to email address
        display_name, addr = email.utils.parseaddr(msg.get("From", ""))
        sender = display_name.strip() if display_name.strip() else addr

        # Date — gracefully handle missing or malformed Date headers
        date_parsed: datetime | None = None
        date_str = msg.get("Date")
        if date_str:
            try:
                date_parsed = email.utils.parsedate_to_datetime(date_str)
            except (TypeError, ValueError):
                pass

        # Body extraction
        plain_text, html_text = _get_body_parts(msg)

        links: list[dict] = []

        if plain_text is not None:
            body = plain_text
            # Still extract links from HTML part if it exists alongside plain text
            if html_text is not None:
                try:
                    html_soup = BeautifulSoup(html_text, "lxml")
                    links = _extract_links(html_soup)
                except Exception:
                    pass
        elif html_text is not None:
            soup = BeautifulSoup(html_text, "lxml")
            links = _extract_links(soup)   # extract BEFORE stripping
            _strip_noise(soup)
            body = _html_to_text(str(soup))
        else:
            body = ""

        body = body.strip()

        if not body:
            continue

        if len(body) < 200:
            logger.warning(
                "Short extraction (%d chars) for email from %s — possible parse failure",
                len(body),
                sender,
            )

        results.append(
            ParsedEmail(
                subject=subject,
                sender=sender,
                date=date_parsed,
                body=body,
                links=links,
            )
        )

    return results
