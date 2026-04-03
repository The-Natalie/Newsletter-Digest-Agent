from __future__ import annotations

import dataclasses
import logging

from ingestion.email_parser import StoryRecord

logger = logging.getLogger(__name__)


def select_representative(cluster: list[StoryRecord]) -> StoryRecord:
    """Select the representative story item from a cluster of duplicates.

    Selection priority (higher is better, applied left-to-right as a tuple key):
    1. Longest body — maximises content richness; body text is the dedup signal
    2. Has title — structured items preferred over untitled ones as tiebreaker
    3. Has link — items with a real content URL are preferable as tiebreaker

    After selection, the representative's date is replaced with the earliest
    date across all items in the cluster. This ensures that when the same story
    appears across multiple newsletter issues, the pipeline keeps the first-seen
    date rather than the date of whichever item happened to have the longest body.

    Args:
        cluster: Non-empty list of StoryRecord objects from one semantic cluster.

    Returns:
        A new StoryRecord (via dataclasses.replace) with the representative's
        fields and the earliest date from the cluster.
    """
    representative = max(
        cluster,
        key=lambda r: (len(r.body), r.title is not None, r.link is not None),
    )
    earliest_date = min(
        (r.date for r in cluster if r.date),
        default=representative.date,
    )
    return dataclasses.replace(representative, date=earliest_date)


def deduplicate(clusters: list[list[StoryRecord]]) -> list[StoryRecord]:
    """Select one representative StoryRecord per cluster.

    Converts the list of clusters produced by embed_and_cluster() into a flat
    list of story items ready for the LLM filter. Each cluster yields exactly
    one representative item via select_representative().

    Args:
        clusters: List of story clusters from embed_and_cluster(). Each cluster
                  is a list of StoryRecords covering the same story event.

    Returns:
        Flat list of representative StoryRecord objects, one per non-empty cluster.
        Empty clusters are skipped. Order matches the cluster order from the embedder.
    """
    if not clusters:
        return []

    representatives: list[StoryRecord] = []
    for cluster in clusters:
        if not cluster:
            continue
        if len(cluster) > 5:
            newsletters = [r.newsletter for r in cluster]
            logger.warning(
                "Large cluster (%d items from %s) — possible false positive merge",
                len(cluster),
                newsletters,
            )
        representatives.append(select_representative(cluster))

    logger.info(
        "Deduplicated %d cluster(s) into %d representative story item(s)",
        len(clusters),
        len(representatives),
    )
    return representatives
