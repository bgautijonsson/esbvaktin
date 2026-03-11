#!/usr/bin/env python3
"""
download_podcast.py — Download episodes from Icelandic political podcasts.

Supports multiple shows via a registry of known feeds. Currently:
  - silfrid   Silfrið (RÚV) — weekly political panel
  - spursmal  Spursmál (mbl.is) — Friday political discussion

Usage:
    # List all shows:
    python scripts/download_podcast.py shows

    # List episodes for a specific show:
    python scripts/download_podcast.py silfrid --list
    python scripts/download_podcast.py spursmal --list

    # Download by episode number:
    python scripts/download_podcast.py silfrid --episodes 19 20

    # Download by keyword search (OR logic, case-insensitive):
    python scripts/download_podcast.py silfrid --search "ESB" --search "Evrópu"

    # Search across ALL shows at once:
    python scripts/download_podcast.py all --search "ESB" --dry-run

    # Combine search + explicit episodes:
    python scripts/download_podcast.py spursmal --search "Evrópusamband" --episodes 115

    # Dry run (show what would be downloaded):
    python scripts/download_podcast.py all --search "ESB" --search "aðildar" --dry-run
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

USER_AGENT = "ESBvaktin/1.0 (podcast-downloader)"
DEFAULT_OUTPUT_ROOT = "data/audio"

# XML namespaces commonly used in podcast feeds
NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "acast": "https://schema.acast.com/1.0/",
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


# ---------------------------------------------------------------------------
# Show registry
# ---------------------------------------------------------------------------

@dataclass
class ShowConfig:
    """Configuration for a known podcast show."""

    slug: str  # CLI identifier, also used as output subdirectory
    name: str  # Human-readable name
    feed_url: str
    # Regex to extract episode number from title; group(1) must be the number
    episode_number_pattern: str
    # Regex for boilerplate to strip from descriptions
    description_boilerplate: str = ""

    def parse_episode_number(self, title: str) -> int | None:
        m = re.search(self.episode_number_pattern, title)
        return int(m.group(1)) if m else None

    def clean_description(self, raw: str) -> str:
        text = strip_html(raw)
        if self.description_boilerplate:
            text = re.sub(self.description_boilerplate, "", text)
        return text.strip()


# --- Known shows -----------------------------------------------------------

SHOWS: dict[str, ShowConfig] = {}


def register_show(show: ShowConfig) -> None:
    SHOWS[show.slug] = show


register_show(ShowConfig(
    slug="silfrid",
    name="Silfrið (RÚV)",
    feed_url="https://feeds.acast.com/public/shows/68b5b70071ccb00a03e060e6",
    episode_number_pattern=r"(\d+)\.?\s*þáttur",
    description_boilerplate=r"\s*Hosted on Acast\..*$",
))

register_show(ShowConfig(
    slug="spursmal",
    name="Spursmál (mbl.is)",
    feed_url="https://anchor.fm/s/f18f34b8/podcast/rss",
    # Titles like "#115. - Er Ísland á leið..." or "113. - Verður VG..."
    episode_number_pattern=r"#?(\d+)\.?\s*-?\s",
    description_boilerplate="",
))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Episode:
    """A single podcast episode parsed from an RSS feed."""

    show_slug: str  # Which show this belongs to
    number: int | None  # Episode number extracted from title, or None
    title: str
    pub_date: str  # Raw pubDate string
    duration: str  # e.g. "44:37" or "01:23:27"
    description: str  # Plain-text description (HTML stripped)
    audio_url: str  # Direct MP3 URL from <enclosure>
    guid: str  # Episode GUID
    link: str  # Web link to the episode

    @property
    def sort_key(self) -> tuple[str, int]:
        """Sort by show, then episode number."""
        return (self.show_slug, self.number or 0)

    @property
    def filename(self) -> str:
        """Generate a clean filename from the episode metadata."""
        prefix = f"{self.number:03d}" if self.number else self.guid[:8]
        slug = self.title.lower()
        # Remove common episode number prefixes
        slug = re.sub(r"^#?\d+\.?\s*(?:þáttur)?:?\s*-?\s*", "", slug)
        # Keep alphanumeric + Icelandic chars, replace rest with hyphens
        slug = re.sub(r"[^\wáéíóúýþæöðÁÉÍÓÚÝÞÆÖÐ]+", "-", slug, flags=re.UNICODE)
        slug = slug.strip("-")[:80]
        return f"{prefix}-{slug}.mp3"

    @property
    def metadata_filename(self) -> str:
        return self.filename.rsplit(".", 1)[0] + ".json"


# ---------------------------------------------------------------------------
# Feed parsing
# ---------------------------------------------------------------------------

def fetch_feed(url: str) -> str:
    """Fetch an RSS feed XML as a string."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def strip_html(html: str) -> str:
    """Remove HTML tags and unescape entities."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_feed(xml_text: str, show: ShowConfig) -> list[Episode]:
    """Parse RSS XML into Episode objects using show-specific config."""
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
            show_slug=show.slug,
            number=show.parse_episode_number(title),
            title=title,
            pub_date=item.findtext("pubDate", ""),
            duration=item.findtext("itunes:duration", "", NS),
            description=show.clean_description(description_raw),
            audio_url=audio_url,
            guid=item.findtext("guid", ""),
            link=item.findtext("link", ""),
        ))

    return episodes


def load_show_episodes(show: ShowConfig) -> list[Episode]:
    """Fetch and parse all episodes for a show."""
    print(f"  Fetching {show.name} ...")
    xml_text = fetch_feed(show.feed_url)
    episodes = parse_feed(xml_text, show)
    print(f"  → {len(episodes)} episodes found.")
    return episodes


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def filter_by_numbers(episodes: list[Episode], numbers: list[int]) -> list[Episode]:
    num_set = set(numbers)
    return [ep for ep in episodes if ep.number in num_set]


def filter_by_search(
    episodes: list[Episode],
    terms: list[str],
    case_insensitive: bool = True,
) -> list[Episode]:
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
    with urlopen(req, timeout=300) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 1024 * 256  # 256 KB

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
        print()

    # Write metadata sidecar
    meta = asdict(ep)
    meta["downloaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    meta["local_file"] = str(mp3_path)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return mp3_path


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_episode_list(episodes: list[Episode], show_name: str = "") -> None:
    """Print a formatted episode listing."""
    if show_name:
        print(f"\n{'=' * 60}")
        print(f"  {show_name}")
        print(f"{'=' * 60}\n")

    for ep in sorted(episodes, key=lambda e: e.number or 0):
        num = f"{ep.number:3d}" if ep.number else "  ?"
        desc = ep.description[:120] + "..." if len(ep.description) > 120 else ep.description
        print(f"  [{num}]  {ep.pub_date[:16]}  ({ep.duration})")
        print(f"        {ep.title}")
        print(f"        {desc}")
        print()


def print_show_list() -> None:
    """Print the registry of known shows."""
    print("\nAvailable shows:\n")
    for slug, show in SHOWS.items():
        print(f"  {slug:12s}  {show.name}")
        print(f"  {' ':12s}  {show.feed_url}")
        print()
    print("Use 'all' to operate on every show at once.")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def resolve_shows(show_arg: str) -> list[ShowConfig]:
    """Resolve a CLI show argument to ShowConfig(s)."""
    if show_arg == "all":
        return list(SHOWS.values())
    if show_arg in SHOWS:
        return [SHOWS[show_arg]]
    print(f"Unknown show: '{show_arg}'")
    print(f"Available: {', '.join(SHOWS.keys())}, all")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download episodes from Icelandic political podcasts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "show",
        nargs="?",
        default="shows",
        help="Show slug (silfrid, spursmal, all) or 'shows' to list available shows.",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all available episodes for the show(s).",
    )
    parser.add_argument(
        "--episodes", "-e",
        type=int,
        nargs="+",
        metavar="N",
        help="Episode numbers to download.",
    )
    parser.add_argument(
        "--search", "-s",
        action="append",
        metavar="TERM",
        help="Download episodes matching this term (OR logic, case-insensitive). "
             "Repeatable.",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help=f"Output directory (default: {DEFAULT_OUTPUT_ROOT}/<show>/).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded without downloading.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download even if file already exists.",
    )

    args = parser.parse_args()

    # 'shows' command — just list available shows
    if args.show == "shows":
        print_show_list()
        return

    shows = resolve_shows(args.show)

    # Load episodes from all requested shows
    print()
    all_episodes: dict[str, list[Episode]] = {}
    for show in shows:
        all_episodes[show.slug] = load_show_episodes(show)
    print()

    # List mode
    if args.list:
        for show in shows:
            print_episode_list(all_episodes[show.slug], show.name)
        return

    # Must have a filter
    if not args.episodes and not args.search:
        parser.error("Specify --episodes and/or --search (or use --list to browse).")

    # Apply filters per show, collect results
    selected: list[Episode] = []
    for show in shows:
        eps = all_episodes[show.slug]
        matched: dict[str, Episode] = {}  # guid → Episode (dedup)

        if args.episodes:
            for ep in filter_by_numbers(eps, args.episodes):
                matched[ep.guid] = ep

        if args.search:
            for ep in filter_by_search(eps, args.search):
                matched[ep.guid] = ep

        selected.extend(matched.values())

    if not selected:
        print("No episodes matched your criteria.")
        sys.exit(1)

    # Sort by show then episode number
    selected.sort(key=lambda e: e.sort_key)

    print(f"Selected {len(selected)} episode(s):\n")
    current_show = ""
    for ep in selected:
        if ep.show_slug != current_show:
            current_show = ep.show_slug
            print(f"  [{SHOWS[current_show].name}]")
        num = f"Ep. {ep.number}" if ep.number else ep.guid[:8]
        print(f"    • {num}: {ep.title}")
    print()

    if args.dry_run:
        print("(Dry run — nothing downloaded.)")
        return

    # Download
    for ep in selected:
        if args.output:
            out_dir = args.output
        else:
            out_dir = Path(DEFAULT_OUTPUT_ROOT) / ep.show_slug

        print(f"\n[{SHOWS[ep.show_slug].name}]")
        download_episode(ep, out_dir, overwrite=args.overwrite)

    show_counts = {}
    for ep in selected:
        show_counts[ep.show_slug] = show_counts.get(ep.show_slug, 0) + 1
    summary = ", ".join(f"{SHOWS[s].name}: {n}" for s, n in show_counts.items())
    print(f"\nDone! Downloaded {len(selected)} episode(s) ({summary})")


if __name__ == "__main__":
    main()
