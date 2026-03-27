from __future__ import annotations

import logging
from dataclasses import dataclass, field

from processing.embedder import StoryChunk

logger = logging.getLogger(__name__)


@dataclass
class StoryGroup:
    chunks: list[StoryChunk]                # all story excerpts (for AI prompt)
    sources: list[dict] = field(default_factory=list)
    # sources shape: [{"newsletter": str, "url": str, "anchor_text": str}]


def _build_sources(cluster: list[StoryChunk]) -> list[dict]:
    """Build deduplicated source list from all chunks in a cluster."""
    sources = []
    seen_urls: set[str] = set()

    for chunk in cluster:
        for link in chunk.links:
            url = link.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                sources.append({
                    "newsletter": chunk.sender,
                    "url": url,
                    "anchor_text": link.get("anchor_text", ""),
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
    for cluster in clusters:
        if len(cluster) > 5:
            senders = [c.sender for c in cluster]
            logger.warning(
                "Large cluster (%d chunks from %s) — possible false positive merge",
                len(cluster),
                senders,
            )
        sources = _build_sources(cluster)
        groups.append(StoryGroup(chunks=cluster, sources=sources))

    logger.info("Deduplicated %d cluster(s) into %d story group(s)", len(clusters), len(groups))
    return groups
