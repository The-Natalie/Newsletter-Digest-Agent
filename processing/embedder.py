from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sentence_transformers import SentenceTransformer
from sentence_transformers import util as st_util

from config import settings
from ingestion.email_parser import ParsedEmail

logger = logging.getLogger(__name__)

_MODEL_NAME = "all-MiniLM-L6-v2"
_MIN_CHUNK_CHARS = 50       # segments shorter than this are filtered out
_MAX_ENCODING_CHARS = 400   # max chars fed to the encoder per chunk

_SPLIT_PATTERN = re.compile(r'\n{2,}|^\s*[-*_]{3,}\s*$', re.MULTILINE)

_model: SentenceTransformer | None = None


@dataclass
class StoryChunk:
    text: str                # full story text (for the AI prompt in digest_builder)
    sender: str              # newsletter display name (for source attribution)
    links: list[dict] = field(default_factory=list)  # links from the source email


def _get_model() -> SentenceTransformer:
    """Lazy-load and cache the sentence-transformers model."""
    global _model
    if _model is None:
        logger.info("Loading sentence-transformers model: %s", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _segment_email(parsed_email: ParsedEmail) -> list[StoryChunk]:
    """Split email body into story candidates at blank-line and horizontal-rule boundaries."""
    segments = _SPLIT_PATTERN.split(parsed_email.body)
    chunks = []
    for seg in segments:
        seg = seg.strip()
        if len(seg) >= _MIN_CHUNK_CHARS:
            chunks.append(StoryChunk(
                text=seg,
                sender=parsed_email.sender,
                links=_links_for_chunk(seg, parsed_email.links),
            ))
    logger.debug("Email from %s segmented into %d chunks", parsed_email.sender, len(chunks))
    return chunks


def _encoding_text(chunk: StoryChunk) -> str:
    """Return the text used for semantic encoding (title + first ~2–3 sentences)."""
    return chunk.text[:_MAX_ENCODING_CHARS]


def _links_for_chunk(text: str, all_links: list[dict]) -> list[dict]:
    """Return the subset of links whose anchor text appears in this chunk's text.

    html2text with ignore_links=True strips href attributes but keeps anchor text
    inline, so anchor text matching reliably associates links with their story chunk.
    """
    text_lower = text.lower()
    return [
        link for link in all_links
        if link.get("anchor_text", "").lower() in text_lower
        and link.get("anchor_text", "")  # skip links with empty anchor text
    ]


def embed_and_cluster(parsed_emails: list[ParsedEmail]) -> list[list[StoryChunk]]:
    """Segment emails into story chunks, encode, and cluster by semantic similarity.

    Args:
        parsed_emails: List of parsed email objects from parse_emails().

    Returns:
        List of story clusters. Each cluster is a list of StoryChunks representing
        semantically similar stories across newsletters. Singletons (unique stories)
        are returned as single-element clusters. Every story chunk is in exactly
        one cluster.
    """
    if not parsed_emails:
        return []

    all_chunks: list[StoryChunk] = []
    for parsed_email in parsed_emails:
        all_chunks.extend(_segment_email(parsed_email))

    if not all_chunks:
        return []

    if len(all_chunks) == 1:
        return [[all_chunks[0]]]

    model = _get_model()
    encoding_texts = [_encoding_text(c) for c in all_chunks]
    embeddings = model.encode(encoding_texts, convert_to_tensor=True, show_progress_bar=False)

    clusters_indices = st_util.community_detection(
        embeddings,
        threshold=settings.dedup_threshold,
        min_community_size=1,
        show_progress_bar=False,
    )

    result = [[all_chunks[i] for i in cluster] for cluster in clusters_indices]

    logger.info(
        "Clustered %d story chunks into %d groups (threshold=%.2f)",
        len(all_chunks),
        len(result),
        settings.dedup_threshold,
    )
    return result
