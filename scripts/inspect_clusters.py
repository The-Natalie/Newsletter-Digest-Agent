"""Diagnostic script: dump cluster membership and source-link competition for a real .eml file.

Usage:
    python scripts/inspect_clusters.py path/to/email.eml

Runs the pipeline through embed_and_cluster() + deduplicate() and prints, for each story
group, every chunk's text preview, all candidate links, the CTA filter result, the
_score_source() value for each candidate, and the winning link.

Purpose:
    Determine whether incorrect source links are caused by:
    1. Scoring failure — the correct chunk IS in the cluster but _score_source() selects
       a worse link (e.g. a long prose in-text anchor beats a headline anchor).
    2. Clustering false positive — the wrong chunk is in the cluster; the anchor text
       comes from a section that covers a different story entirely.

No AI, no IMAP, no database — pipeline runs through deduplication only.
"""
from __future__ import annotations

import email
import sys
import os
from email import policy
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.email_parser import parse_emails
from processing.embedder import embed_and_cluster
from processing.deduplicator import _is_cta_link, _score_source


def _path_depth(url: str) -> int:
    try:
        path = urlparse(url).path.rstrip("/")
        return len([s for s in path.split("/") if s])
    except Exception:
        return 0


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/inspect_clusters.py path/to/email.eml")
        sys.exit(1)

    eml_path = sys.argv[1]
    with open(eml_path, "rb") as f:
        raw = f.read()

    msg = email.message_from_bytes(raw, policy=policy.default)
    sender_hdr = msg.get("From", "(unknown sender)")
    subject = msg.get("Subject", "(no subject)")
    print(f"From:    {sender_hdr}")
    print(f"Subject: {subject}")
    print()

    parsed = parse_emails([raw])
    if not parsed:
        print("ERROR: No parseable email found.")
        sys.exit(1)

    print("Running embed_and_cluster() — loading sentence-transformers model if not cached...")
    clusters = embed_and_cluster(parsed)
    print(f"Total clusters: {len(clusters)}")
    print("=" * 70)

    for group_idx, cluster in enumerate(clusters, 1):
        # Reproduce _build_sources() logic verbosely
        sources_selected: list[dict] = []
        seen_urls: set[str] = set()

        print(f"\n=== Story Group {group_idx} ({len(cluster)} chunk(s)) ===")

        for chunk_idx, chunk in enumerate(cluster, 1):
            preview = chunk.text[:80].replace("\n", " ")
            print(f"  Chunk {chunk_idx} [sender: {chunk.sender!r}] ({len(chunk.text)} chars)")
            print(f"    Text preview: \"{preview}{'...' if len(chunk.text) > 80 else ''}\"")

            if not chunk.links:
                print("    Links: (none)")
                continue

            cta_count = 0
            candidates: list[dict] = []
            all_links = chunk.links

            for link in all_links:
                anchor = link.get("anchor_text", "")
                url = link.get("url", "")
                is_cta = _is_cta_link({"anchor_text": anchor})
                if is_cta:
                    cta_count += 1
                else:
                    candidates.append(link)

            # Fallback: if all links are CTA, use all
            if not candidates:
                candidates = all_links
                fallback_note = " [CTA-fallback: all links are CTAs]"
            else:
                fallback_note = ""

            print(f"    Candidate links ({len(all_links)} total, {cta_count} CTA-filtered{fallback_note}):")
            for link in all_links:
                anchor = link.get("anchor_text", "")
                url = link.get("url", "")
                is_cta = _is_cta_link({"anchor_text": anchor})
                score = _score_source({"url": url, "anchor_text": anchor})
                depth = _path_depth(url)
                word_count = len(anchor.split())
                cta_marker = " [CTA]" if is_cta else ""
                print(f"      [{anchor}]{cta_marker}")
                print(f"        url: {url}")
                print(f"        path_depth={depth}  word_count={word_count}  score={score}")

            best = max(candidates, key=lambda l: _score_source({"url": l.get("url", ""), "anchor_text": l.get("anchor_text", "")}))
            winner_url = best.get("url", "")
            winner_anchor = best.get("anchor_text", "")

            if winner_url and winner_url not in seen_urls:
                seen_urls.add(winner_url)
                sources_selected.append({
                    "newsletter": chunk.sender,
                    "url": winner_url,
                    "anchor_text": winner_anchor,
                })
                print(f"    WINNER: [{winner_anchor}] -> {winner_url}")
            else:
                print(f"    WINNER: [{winner_anchor}] -> {winner_url}  (URL already seen — skipped)")

        print()
        print(f"  Sources for this group ({len(sources_selected)}):")
        for src in sources_selected:
            print(f"    newsletter={src['newsletter']!r}  anchor={src['anchor_text']!r}")
            print(f"    url: {src['url']}")
        print("-" * 70)


if __name__ == "__main__":
    main()
