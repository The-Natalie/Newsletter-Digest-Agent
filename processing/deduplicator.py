from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urlparse

from processing.embedder import StoryChunk

logger = logging.getLogger(__name__)

# Anchor text substrings that indicate a CTA/boilerplate link rather than a story link.
# Matched case-insensitively. Used to prefer genuine story links within a single chunk.
_CTA_ANCHOR_SIGNALS: tuple[str, ...] = (
    # Demo / trial CTAs
    "try a demo",
    "try demo",
    "request a demo",
    "book a demo",
    "get a demo",
    "see it in action",
    # Watch/view CTAs — "watch now" was confirmed missing (Deep View §15 Slack sponsor)
    "watch our",
    "watch the",
    "watch now",
    # Registration / sign-up CTAs
    "register free",
    "register now",
    "sign up free",
    "sign up now",
    "start free",
    "start for free",
    "start free trial",
    # Lead-gen / download CTAs (same family as existing entries)
    "get the report",
    "download the report",
    "get the guide",
    "get the whitepaper",
    # Generic action CTAs
    "learn more",
    "read more",
    "find out more",
    "click here",
    # Feedback / social / admin
    "share your thoughts",
    "terms of service",
    "privacy policy",
    "unsubscribe",
    "manage preferences",
    "advertise with us",
    "sponsor",
)


def _is_cta_link(source: dict) -> bool:
    """Return True if anchor text matches a known CTA/boilerplate signal.

    Only applies to anchor-text signals. Does not filter by URL pattern, so
    legitimate sponsor articles (which have descriptive anchors) are not dropped.
    """
    anchor = source.get("anchor_text", "").lower()
    return any(signal in anchor for signal in _CTA_ANCHOR_SIGNALS)


@dataclass
class StoryGroup:
    chunks: list[StoryChunk]                # all story excerpts (for AI prompt)
    sources: list[dict] = field(default_factory=list)
    # sources shape: [{"newsletter": str, "url": str, "anchor_text": str}]


_ANCHOR_IDEAL_MAX_WORDS = 7
# Anchors with more words than this are treated as in-text prose references, not headlines.
# They score 0 on the anchor-quality dimension; path_depth alone determines selection.
# Within the headline range (≤7 words), more words = more descriptive = higher score.
#
# Confirmed scoring failures this threshold fixes:
#   "small robots that looked like they came straight out of WALL-E" (11w) was beating
#   "told reporters" (2w) at equal path_depth=7.
#   "manage all of these features from one central hub" (9w) was beating "Airia" (1w)
#   at equal path_depth=7. Both were in-text prose references, not headline links.


def _score_source(source: dict) -> tuple[int, int]:
    """Score a source link for quality selection. Higher tuple = better source.

    Scoring dimensions (both higher-is-better):
    - path_depth: number of non-empty path segments in the URL.
      Deeper paths indicate specific article/content pages vs. homepages.
      e.g. /blog/2026/gpt-5-release → depth 3; https://openai.com/ → depth 0
    - anchor_score: word count of anchor text, capped at _ANCHOR_IDEAL_MAX_WORDS.
      Anchors above the cap score 0 — they are prose-length in-text references,
      not headlines. Within the cap, more words = more descriptive = higher score.

    On URL parse error, path_depth defaults to 0 (anchor_score still used as tiebreaker).
    """
    url = source.get("url", "")
    anchor = source.get("anchor_text", "")
    try:
        path = urlparse(url).path.rstrip("/")
        path_depth = len([s for s in path.split("/") if s])
    except Exception:
        path_depth = 0
    word_count = len(anchor.split())
    anchor_score = word_count if word_count <= _ANCHOR_IDEAL_MAX_WORDS else 0
    return (path_depth, anchor_score)


def _build_sources(cluster: list[StoryChunk]) -> list[dict]:
    """Collect sources from a cluster, one per chunk using that chunk's own best link.

    For each chunk in the cluster, independently selects the best link from that chunk's
    own links using _score_source(). This preserves the chunk-to-link relationship:
    a sponsor chunk's link is never attributed to a story chunk, and vice versa.

    Sources are deduplicated by URL across chunks (a URL appearing in two chunks is
    included only once, attributed to the first chunk that contributes it).

    Returns a list with one entry per unique-URL contributing chunk. Returns [] if no
    chunk has any valid links (sourceless cluster, dropped by deduplicate()).
    """
    sources: list[dict] = []
    seen_urls: set[str] = set()

    for chunk in cluster:
        if not chunk.links:
            continue
        # Prefer non-CTA links within this chunk; fall back to all links if every one is a CTA
        candidate_links = [l for l in chunk.links if not _is_cta_link({"anchor_text": l.get("anchor_text", "")})]
        if not candidate_links:
            candidate_links = chunk.links
        best_link = max(
            candidate_links,
            key=lambda l: _score_source({"url": l.get("url", ""), "anchor_text": l.get("anchor_text", "")}),
        )
        url = best_link.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            sources.append({
                "newsletter": chunk.sender,
                "url": url,
                "anchor_text": best_link.get("anchor_text", ""),
            })

    return sources


def deduplicate(clusters: list[list[StoryChunk]]) -> list[StoryGroup]:
    """Convert story clusters into StoryGroup objects with combined source attribution.

    Args:
        clusters: List of story clusters from embed_and_cluster(). Each cluster is
                  a list of StoryChunks that cover the same story event.

    Returns:
        List of StoryGroup objects, one per cluster. Each group contains all
        contributing story excerpts and a deduplicated list of source links.
    """
    if not clusters:
        return []

    groups = []
    sourceless_count = 0
    for cluster in clusters:
        if len(cluster) > 5:
            senders = [c.sender for c in cluster]
            logger.warning(
                "Large cluster (%d chunks from %s) — possible false positive merge",
                len(cluster),
                senders,
            )
        sources = _build_sources(cluster)
        if not sources:
            sourceless_count += 1
            continue
        groups.append(StoryGroup(chunks=cluster, sources=sources))

    if sourceless_count:
        logger.info("Dropped %d sourceless story group(s) (no valid links)", sourceless_count)

    logger.info("Deduplicated %d cluster(s) into %d story group(s)", len(clusters), len(groups))
    return groups
