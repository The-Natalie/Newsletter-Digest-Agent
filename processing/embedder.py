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

# Substrings identifying non-story newsletter sections.
# These are sections whose content is administrative, editorial meta, or promotional
# infrastructure — they are not news stories and should not reach the AI prompt.
# Each phrase is multi-word to reduce false positives.
# NOT included: sponsor content, product announcements, research, tools, job listings.
# These are conservative signals: only drop on clear non-story match.
_NON_STORY_SIGNALS = (
    # Subscription-receiving meta (onboarding blurbs)
    "you're receiving this because",
    "you are receiving this because",
    # Frequency / notification settings prompts
    "to change how often you receive",
    "to update your notification preferences",
    # Audience growth / ad recruitment copy
    "want to advertise with us",
    "interested in advertising with us",
    "interested in sponsoring this",
    # Newsletter outro / sign-off boilerplate
    "that's all for this week",
    "that's it for this week",
    "see you next issue",
    "see you in the next issue",
    # Feedback / survey prompts
    "take our survey",
    "fill out our survey",
)


def _is_non_story_chunk(text: str) -> bool:
    """Return True if this chunk is non-story newsletter content (meta/admin/editorial).

    Uses substring matching against _NON_STORY_SIGNALS. Only filters on clear,
    multi-word signals to avoid false positives on legitimate stories.
    """
    text_lower = text.lower()
    return any(signal in text_lower for signal in _NON_STORY_SIGNALS)


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
    """Split email body into story candidates.

    Preferred path: use pre-extracted sections from email_parser (HTML emails).
    Each section already has local links and boilerplate filtered out.

    Fallback path: split plain-text body at blank-line/HR boundaries with no links.
    """
    if parsed_email.sections:
        chunks = []
        non_story_count = 0
        for section in parsed_email.sections:
            if len(section["text"]) < _MIN_CHUNK_CHARS:
                continue
            if _is_non_story_chunk(section["text"]):
                non_story_count += 1
                continue
            chunks.append(StoryChunk(
                text=section["text"],
                sender=parsed_email.sender,
                links=section["links"],
            ))
        if non_story_count:
            logger.debug(
                "Email from %s: dropped %d non-story section(s)",
                parsed_email.sender, non_story_count,
            )
        logger.debug(
            "Email from %s: used %d pre-extracted sections → %d chunks",
            parsed_email.sender, len(parsed_email.sections), len(chunks),
        )
        return chunks

    # Fallback: plain-text email — split body, no links available
    segments = _SPLIT_PATTERN.split(parsed_email.body)
    chunks = []
    non_story_count = 0
    for seg in segments:
        seg = seg.strip()
        if len(seg) < _MIN_CHUNK_CHARS:
            continue
        if _is_non_story_chunk(seg):
            non_story_count += 1
            continue
        chunks.append(StoryChunk(
            text=seg,
            sender=parsed_email.sender,
            links=[],
        ))
    if non_story_count:
        logger.debug(
            "Email from %s: dropped %d non-story segment(s) (plain-text fallback)",
            parsed_email.sender, non_story_count,
        )
    logger.debug(
        "Email from %s: plain-text fallback → %d chunks",
        parsed_email.sender, len(chunks),
    )
    return chunks


def _encoding_text(chunk: StoryChunk) -> str:
    """Return the text used for semantic encoding (title + first ~2–3 sentences)."""
    return chunk.text[:_MAX_ENCODING_CHARS]


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
