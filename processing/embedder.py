from __future__ import annotations

import logging

from sentence_transformers import SentenceTransformer
from sentence_transformers import util as st_util

from config import settings
from ingestion.email_parser import StoryRecord

logger = logging.getLogger(__name__)

_MODEL_NAME = "all-MiniLM-L6-v2"
_MAX_ENCODING_CHARS = 400   # max chars fed to the encoder per record


_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    """Lazy-load and cache the sentence-transformers model."""
    global _model
    if _model is None:
        logger.info("Loading sentence-transformers model: %s", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _encoding_text(record: StoryRecord) -> str:
    """Return the text used for semantic encoding (body text, truncated)."""
    return record.body[:_MAX_ENCODING_CHARS]


def embed_and_cluster(story_records: list[StoryRecord]) -> list[list[StoryRecord]]:
    """Encode story records and cluster by semantic similarity.

    Args:
        story_records: Flat list of StoryRecord objects from parse_emails().
                       Body text is used as the dedup signal.

    Returns:
        List of story clusters. Each cluster is a list of StoryRecords that
        cover the same story. Singletons (unique stories) are returned as
        single-element clusters. Every record is in exactly one cluster.
    """
    if not story_records:
        return []

    if len(story_records) == 1:
        return [[story_records[0]]]

    model = _get_model()
    encoding_texts = [_encoding_text(r) for r in story_records]
    embeddings = model.encode(encoding_texts, convert_to_tensor=True, show_progress_bar=False)

    clusters_indices = st_util.community_detection(
        embeddings,
        threshold=settings.dedup_threshold,
        min_community_size=1,
        show_progress_bar=False,
    )

    result = [[story_records[i] for i in cluster] for cluster in clusters_indices]

    logger.info(
        "Clustered %d story records into %d groups (threshold=%.2f)",
        len(story_records),
        len(result),
        settings.dedup_threshold,
    )
    return result
