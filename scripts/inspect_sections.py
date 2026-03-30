"""Diagnostic script: dump _extract_sections() output for a real .eml file.

Usage:
    python scripts/inspect_sections.py path/to/email.eml

Prints each section's index, character count, full text, and all extracted links.
No AI, no IMAP, no database — parser inspection only.

Purpose:
    Identify which failure mode is causing within-chunk link contamination:
    1. Single-newline boundary miss (html2text emits \\n not \\n\\n between stories)
    2. Heading-merge overreach (heading fused with wrong body section)
    3. Inline link position (links from one story appear in the next section)
"""
from __future__ import annotations

import email
import sys
import os
from email import policy

# Allow running from the project root without installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.email_parser import _extract_sections


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/inspect_sections.py path/to/email.eml")
        sys.exit(1)

    eml_path = sys.argv[1]
    with open(eml_path, "rb") as f:
        raw = f.read()

    msg = email.message_from_bytes(raw, policy=policy.default)

    # Extract sender for context
    sender = msg.get("From", "(unknown sender)")
    subject = msg.get("Subject", "(no subject)")
    print(f"From:    {sender}")
    print(f"Subject: {subject}")
    print()

    # Get HTML part
    html_part = msg.get_body(preferencelist=("html",))
    if html_part is None:
        print("ERROR: No HTML part found in this email.")
        sys.exit(1)

    html_text = html_part.get_content()
    sections = _extract_sections(html_text)

    print(f"Total sections extracted: {len(sections)}")
    print("=" * 70)

    for i, section in enumerate(sections, 1):
        text = section["text"]
        links = section.get("links", [])
        print(f"\n=== Section {i} ({len(text)} chars) ===")
        print(text)
        if links:
            print(f"\n  Links ({len(links)}):")
            for link in links:
                anchor = link.get("anchor_text", "")
                url = link.get("url", "")
                print(f"    [{anchor}] -> {url}")
        else:
            print("\n  Links: (none)")
        print("-" * 70)


if __name__ == "__main__":
    main()
