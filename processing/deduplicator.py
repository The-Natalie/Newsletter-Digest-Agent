from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urlparse

from processing.embedder import StoryChunk

logger = logging.getLogger(__name__)


@dataclass
class StoryGroup:
    chunks: list[StoryChunk]                # all story excerpts (for AI prompt)
    sources: list[dict] = field(default_factory=list)
    # sources shape: [{"newsletter": str, "url": str, "anchor_text": str}]


def _score_source(source: dict) -> tuple[int, int]:
    """Score a source link for quality selection. Higher tuple = better source.

    Scoring dimensions (both higher-is-better):
    - path_depth: number of non-empty path segments in the URL.
      Deeper paths indicate specific article/content pages vs. homepages.
      e.g. /blog/2026/gpt-5-release → depth 3; https://openai.com/ → depth 0
    - anchor_length: character length of the anchor text.
      Among already-filtered (non-boilerplate) anchors, longer is more descriptive.

    On URL parse error, path_depth defaults to 0 (anchor_length still used as tiebreaker).
    """
    url = source.get("url", "")
    anchor = source.get("anchor_text", "")
    try:
        path = urlparse(url).path.rstrip("/")
        path_depth = len([s for s in path.split("/") if s])
    except Exception:
        path_depth = 0
    return (path_depth, len(anchor))


def _build_sources(cluster: list[StoryChunk]) -> list[dict]:
    """Collect all source links from a cluster and return the single best one.

    Candidates are deduplicated by URL (since Loop 2 already normalises URLs,
    exact-match dedup here is sufficient). The best candidate is selected by
    _score_source(): prefer deeper URL paths (article-specific > homepage),
    then longer anchor text (more descriptive > generic).

    Returns a single-element list to preserve the list[dict] return type and
    downstream API shape. Returns [] if no valid links exist (sourceless cluster).
    """
    candidates: list[dict] = []
    seen_urls: set[str] = set()

    for chunk in cluster:
        for link in chunk.links:
            url = link.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                candidates.append({
                    "newsletter": chunk.sender,
                    "url": url,
                    "anchor_text": link.get("anchor_text", ""),
                })

    if not candidates:
        return []

    best = max(candidates, key=_score_source)
    return [best]


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
