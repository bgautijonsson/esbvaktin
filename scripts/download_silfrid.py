#!/usr/bin/env python3
"""
download_silfrid.py — Download specific Silfrið episodes from the Acast RSS feed.

Usage:
    # List all episodes with numbers, dates, and descriptions:
    python scripts/download_silfrid.py --list

    # Download specific episodes by number:
    python scripts/download_silfrid.py --episodes 19 20

    # Download episodes whose title/description matches a keyword:
    python scripts/download_silfrid.py --search "ESB" --search "Evrópu" --search "aðildar"

    # Combine: search + explicit episodes, with a custom output directory:
    python scripts/download_silfrid.py --search "ESB" --episodes 13 --output data/audio/silfrid

    # Dry run (show what would be downloaded without downloading):
    python scripts/download_silfrid.py --search "ESB" --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from html import unescape
from pathlib import Path
from urllib.request import urlopen, Request

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FEED_URL = "https://feeds.acast.com/public/shows/68b5b70071ccb00a03e060e6"
USER_AGENT = "ESBvaktin/1.0 (podcast-downloader)"
DEFAULT_OUTPUT = "data/audio/silfrid"

# XML namespaces used in the Acast feed
NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "acast": "https://schema.acast.com/1.0/",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Episode:
    """A single podcast episode parsed from the RSS feed."""

    number: int | None  # Episode number extracted from title, or None
    title: str
    pub_date: str  # Raw pubDate string
    duration: str  # e.g. "44:37"
    description: str  # Plain-text description (HTML stripped)
    audio_url: str  # Direct MP3 URL from <enclosure>
    guid: str  # Acast episode ID
    link: str  # Web link to the episode

    @property
    def filename(self) -> str:
        """Generate a clean filename from the episode metadata."""
        # Use episode number if available, otherwise guid
        prefix = f"{self.number:02d}" if self.number else self.guid[:8]
        # Slugify the title
        slug = self.title.lower()
        # Remove episode number prefix like "19. þáttur: " or "19.þáttur: "
        slug = re.sub(r"^\d+\.?\s*þáttur:?\s*", "", slug)
        # Keep alphanumeric + Icelandic chars, replace rest with hyphens
        slug = re.sub(r"[^\wáéíóúýþæöðÁÉÍÓÚÝÞÆÖÐ]+", "-", slug, flags=re.UNICODE)
        slug = slug.strip("-")[:80]
        return f"{prefix}-{slug}.mp3"

    @property
    def metadata_filename(self) -> str:
        """JSON metadata sidecar filename."""
        return self.filename.rsplit(".", 1)[0] + ".json"


# ---------------------------------------------------------------------------
# Feed parsing
# ---------------------------------------------------------------------------

def fetch_feed(url: str = FEED_URL) -> str:
    """Fetch the RSS feed XML as a string."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def strip_html(html: str) -> str:
    """Remove HTML tags and unescape entities."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Remove Acast boilerplate
    text = re.sub(r"\s*Hosted on Acast\..*$", "", text)
    return text


def parse_episode_number(title: str) -> int | None:
    """Extract episode number from title like '19. þáttur: ...'."""
    m = re.match(r"(\d+)\.?\s*þáttur", title)
    return int(m.group(1)) if m else None


def parse_feed(xml_text: str) -> list[Episode]:
    """Parse the RSS XML into a list of Episode objects."""
    root = ET.fromstring(xml_text)
    episodes: list[Episode] = []

    for item in root.findall(".//item"):
        title = item.findtext("title", "")
        enclosure = item.find("enclosure")
        if enclosure is None:
            continue

        audio_url = enclosure.get("url", "")
        description_raw = item.findtext("description", "")

        episodes.append(Episode(
            number=parse_episode_number(title),
            title=title,
            pub_date=item.findtext("pubDate", ""),
            duration=item.findtext("itunes:duration", "", NS),
            description=strip_html(description_raw),
            audio_url=audio_url,
            guid=item.findtext("guid", ""),
            link=item.findtext("link", ""),
        ))

    return episodes


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def filter_by_numbers(episodes: list[Episode], numbers: list[int]) -> list[Episode]:
    """Select episodes by their episode number."""
    num_set = set(numbers)
    return [ep for ep in episodes if ep.number in num_set]


def filter_by_search(
    episodes: list[Episode],
    terms: list[str],
    case_insensitive: bool = True,
) -> list[Episode]:
    """Select episodes whose title or description matches any search term."""
    flags = re.IGNORECASE if case_insensitive else 0
    patterns = [re.compile(re.escape(t), flags) for t in terms]

    matched: list[Episode] = []
    for ep in episodes:
        haystack = f"{ep.title} {ep.description}"
        if any(p.search(haystack) for p in patterns):
            matched.append(ep)
    return matched


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

def download_episode(ep: Episode, output_dir: Path, overwrite: bool = False) -> Path:
    """Download an episode MP3 and write a JSON metadata sidecar."""
    output_dir.mkdir(parents=True, exist_ok=True)

    mp3_path = output_dir / ep.filename
    meta_path = output_dir / ep.metadata_filename

    if mp3_path.exists() and not overwrite:
        print(f"  ⏭  Already exists: {mp3_path.name}")
        return mp3_path

    print(f"  ⬇  Downloading: {ep.title}")
    print(f"     → {mp3_path.name}")

    req = Request(ep.audio_url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 1024 * 256  # 256 KB chunks

        with open(mp3_path, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded / total * 100
                    mb = downloaded / 1024 / 1024
                    total_mb = total / 1024 / 1024
                    print(
                        f"\r     {mb:.1f}/{total_mb:.1f} MB ({pct:.0f}%)",
                        end="",
                        flush=True,
                    )
        print()  # newline after progress

    # Write metadata sidecar
    meta = asdict(ep)
    meta["downloaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    meta["local_file"] = str(mp3_path)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return mp3_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_episode_list(episodes: list[Episode], highlight_terms: list[str] | None = None) -> None:
    """Print a formatted list of episodes to stdout."""
    for ep in sorted(episodes, key=lambda e: e.number or 0):
        num = f"{ep.number:2d}" if ep.number else " ?"
        # Truncate description for display
        desc = ep.description[:120] + "..." if len(ep.description) > 120 else ep.description
        print(f"  [{num}]  {ep.pub_date[:16]}  ({ep.duration})")
        print(f"        {ep.title}")
        print(f"        {desc}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Silfrið episodes from Acast RSS feed.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available episodes and exit.",
    )
    parser.add_argument(
        "--episodes", "-e",
        type=int,
        nargs="+",
        metavar="N",
        help="Episode numbers to download (e.g. 19 20).",
    )
    parser.add_argument(
        "--search", "-s",
        action="append",
        metavar="TERM",
        help="Download episodes matching this term in title/description. "
             "Can be repeated (OR logic). Case-insensitive.",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path(DEFAULT_OUTPUT),
        help=f"Output directory (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded without actually downloading.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download even if file already exists.",
    )
    parser.add_argument(
        "--feed-url",
        default=FEED_URL,
        help="Override the RSS feed URL.",
    )

    args = parser.parse_args()

    # Fetch and parse
    print(f"Fetching feed from {args.feed_url} ...")
    xml_text = fetch_feed(args.feed_url)
    episodes = parse_feed(xml_text)
    print(f"Found {len(episodes)} episodes.\n")

    # List mode
    if args.list:
        print_episode_list(episodes)
        return

    # Build selection
    if not args.episodes and not args.search:
        parser.error("Specify --episodes and/or --search (or use --list to browse).")

    selected: dict[str, Episode] = {}  # guid → Episode (dedup)

    if args.episodes:
        for ep in filter_by_numbers(episodes, args.episodes):
            selected[ep.guid] = ep

    if args.search:
        for ep in filter_by_search(episodes, args.search):
            selected[ep.guid] = ep

    if not selected:
        print("No episodes matched your criteria.")
        sys.exit(1)

    # Sort by episode number
    to_download = sorted(selected.values(), key=lambda e: e.number or 0)

    print(f"Selected {len(to_download)} episode(s):\n")
    for ep in to_download:
        num = f"Ep. {ep.number}" if ep.number else ep.guid[:8]
        print(f"  • {num}: {ep.title}")
    print()

    if args.dry_run:
        print("(Dry run — nothing downloaded.)")
        return

    # Download
    print(f"Downloading to: {args.output}/\n")
    for ep in to_download:
        download_episode(ep, args.output, overwrite=args.overwrite)

    print(f"\nDone! {len(to_download)} episode(s) saved to {args.output}/")


if __name__ == "__main__":
    main()
