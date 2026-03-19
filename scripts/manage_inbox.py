"""Article inbox — persistent tracking of discovered articles.

Stores discovered articles with metadata, priority, and status so that
the backlog survives between sessions.

Usage:
    uv run python scripts/manage_inbox.py status
    uv run python scripts/manage_inbox.py list
    uv run python scripts/manage_inbox.py list --priority high
    uv run python scripts/manage_inbox.py list --status queued
    uv run python scripts/manage_inbox.py add --url URL --title TITLE --source SOURCE
    uv run python scripts/manage_inbox.py reject ID [ID ...]
    uv run python scripts/manage_inbox.py skip ID [ID ...]
    uv run python scripts/manage_inbox.py queue ID [ID ...]
    uv run python scripts/manage_inbox.py set-status ID STATUS
    uv run python scripts/manage_inbox.py save-text ID TEXT_FILE
    uv run python scripts/manage_inbox.py known-ids --json
    uv run python scripts/manage_inbox.py next --high-only --limit 5
    uv run python scripts/manage_inbox.py prune --days 30
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

INBOX_PATH = Path("data/inbox/inbox.json")
TEXTS_DIR = Path("data/inbox/texts")
REGISTRY_PATH = Path("data/article_registry.json")
REJECTED_PATH = Path("data/rejected_urls.txt")

VALID_STATUSES = ("pending", "queued", "analysing", "processed", "rejected", "skipped")
VALID_PRIORITIES = ("high", "medium", "low")


def _normalise_url(url: str) -> str:
    return url.rstrip("/").lower()


def _make_id(source: str, url: str) -> str:
    """Generate a stable ID from source slug + URL hash."""
    slug = re.sub(r"[^a-z0-9]", "", source.lower())[:12]
    h = hashlib.sha256(_normalise_url(url).encode()).hexdigest()[:8]
    return f"{slug}-{h}"


def _load_inbox() -> list[dict]:
    if INBOX_PATH.exists():
        return json.loads(INBOX_PATH.read_text())
    return []


def _save_inbox(entries: list[dict]) -> None:
    INBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INBOX_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False, default=str))


def _load_processed_urls() -> set[str]:
    if REGISTRY_PATH.exists():
        registry = json.loads(REGISTRY_PATH.read_text())
        return {_normalise_url(e["url"]) for e in registry if e.get("url")}
    return set()


def _load_rejected_urls() -> set[str]:
    urls = set()
    if REJECTED_PATH.exists():
        for line in REJECTED_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.add(_normalise_url(line))
    return urls


def _find_entry(inbox: list[dict], entry_id: str) -> dict | None:
    """Find entry by ID or partial ID match."""
    for e in inbox:
        if e["id"] == entry_id:
            return e
    # Partial match
    matches = [e for e in inbox if entry_id in e["id"]]
    if len(matches) == 1:
        return matches[0]
    return None


# --- Subcommands ---


def cmd_status(args: argparse.Namespace) -> None:
    inbox = _load_inbox()
    if not inbox:
        print("Article inbox is empty.")
        return

    # Counts by status
    by_status: dict[str, list] = {}
    for e in inbox:
        by_status.setdefault(e["status"], []).append(e)

    print(f"Article Inbox: {len(inbox)} articles")
    for status in VALID_STATUSES:
        items = by_status.get(status, [])
        if not items:
            continue
        priority_counts = {}
        for e in items:
            p = e.get("priority", "?")
            priority_counts[p] = priority_counts.get(p, 0) + 1
        detail = ", ".join(f"{c} {p}" for p, c in sorted(priority_counts.items()))
        print(f"  {status:12} {len(items):3}  ({detail})")

    # By topic
    topic_counts: dict[str, int] = {}
    pending = [e for e in inbox if e["status"] in ("pending", "queued")]
    for e in pending:
        for t in e.get("topics", []):
            topic_counts[t] = topic_counts.get(t, 0) + 1
    if topic_counts:
        print("\nPending/queued by topic:")
        for topic, count in sorted(topic_counts.items(), key=lambda x: -x[1]):
            print(f"  {topic:25} {count}")

    # Oldest pending
    pending_dates = [e.get("discovered", "") for e in inbox if e["status"] == "pending"]
    if pending_dates:
        oldest = min(d for d in pending_dates if d)[:10]
        print(f"\nOldest pending: {oldest}")


def cmd_list(args: argparse.Namespace) -> None:
    inbox = _load_inbox()
    if not inbox:
        print("Article inbox is empty.")
        return

    filtered = inbox
    if args.status:
        filtered = [e for e in filtered if e["status"] == args.status]
    else:
        # Default: show actionable items
        filtered = [e for e in filtered if e["status"] in ("pending", "queued")]

    if args.priority:
        filtered = [e for e in filtered if e.get("priority") == args.priority]

    if not filtered:
        print(f"No articles matching filters (status={args.status}, priority={args.priority}).")
        return

    # Sort: priority (high first), then date (newest first within each tier)
    priority_order = {"high": 0, "medium": 1, "low": 2}
    filtered.sort(
        key=lambda e: (
            priority_order.get(e.get("priority", "low"), 3),
            # Negate date for descending sort — pad missing dates to sort last
            "".join(chr(0x10FFFF - ord(c)) for c in e.get("date", "") or "0000-00-00"),
        )
    )

    # Group by priority
    current_priority = None
    for e in filtered:
        p = e.get("priority", "?")
        if p != current_priority:
            current_priority = p
            print(f"\n### {p.upper()}")
            print(f"{'ID':20} {'Status':10} {'Source':15} {'Words':>5}  {'Date':10}  Title")
            print("-" * 100)
        text_marker = "T" if e.get("has_text") else " "
        print(
            f"{e['id']:20} {e['status']:10} {e.get('source', '?'):15} "
            f"{e.get('word_count', '?'):>5}  {e.get('date', '?'):10}  "
            f"{text_marker} {e.get('title', '?')[:55]}"
        )

    print(f"\n{len(filtered)} articles shown. (T = text cached)")


def cmd_add(args: argparse.Namespace) -> None:
    inbox = _load_inbox()
    processed = _load_processed_urls()
    rejected = _load_rejected_urls()

    norm_url = _normalise_url(args.url)

    # Check for duplicates
    if norm_url in processed:
        print(f"SKIP: Already processed — {args.url}")
        sys.exit(0)
    if norm_url in rejected:
        print(f"SKIP: Already rejected — {args.url}")
        sys.exit(0)
    for e in inbox:
        if _normalise_url(e["url"]) == norm_url:
            print(f"SKIP: Already in inbox as {e['id']} ({e['status']}) — {args.url}")
            sys.exit(0)

    entry_id = _make_id(args.source or "unknown", args.url)
    entry = {
        "id": entry_id,
        "url": args.url,
        "title": args.title or "",
        "source": args.source or "",
        "date": args.date or "",
        "discovered": datetime.now(UTC).isoformat(timespec="seconds"),
        "word_count": args.words or 0,
        "article_type": args.type or "",
        "topics": [t.strip() for t in (args.topics or "").split(",") if t.strip()],
        "priority": args.priority or "medium",
        "status": "pending",
        "frettasafn_id": args.frettasafn_id or "",
        "has_text": False,
        "notes": args.notes or "",
    }

    inbox.append(entry)
    _save_inbox(inbox)
    print(f"Added: {entry_id} [{entry['priority']}] {entry['title'][:60]}")

    # Save text if provided via stdin or file
    if args.text_file:
        text_path = TEXTS_DIR / f"{entry_id}.md"
        TEXTS_DIR.mkdir(parents=True, exist_ok=True)
        text_path.write_text(Path(args.text_file).read_text())
        entry["has_text"] = True
        _save_inbox(inbox)
        print(f"  Text saved: {text_path}")


def cmd_add_batch(args: argparse.Namespace) -> None:
    """Add multiple articles from a JSON file (batch import from /find-articles)."""
    raw = Path(args.file).read_text()
    # Sanitise Icelandic quotes that break JSON parsing
    raw = raw.replace("\u201e", "'").replace("\u201c", "'")
    data = json.loads(raw)
    if not isinstance(data, list):
        print("Error: expected a JSON array of article objects.", file=sys.stderr)
        sys.exit(1)

    inbox = _load_inbox()
    processed = _load_processed_urls()
    rejected = _load_rejected_urls()
    existing_urls = {_normalise_url(e["url"]) for e in inbox}

    added = 0
    skipped = 0
    for item in data:
        url = item.get("url", "")
        if not url:
            continue
        norm_url = _normalise_url(url)
        if norm_url in processed or norm_url in rejected or norm_url in existing_urls:
            skipped += 1
            continue

        source = item.get("source", "unknown")
        entry_id = _make_id(source, url)
        entry = {
            "id": entry_id,
            "url": url,
            "title": item.get("title", ""),
            "source": source,
            "date": item.get("date", ""),
            "discovered": datetime.now(UTC).isoformat(timespec="seconds"),
            "word_count": item.get("word_count", 0),
            "article_type": item.get("article_type", ""),
            "topics": item.get("topics", []),
            "priority": item.get("priority", "medium"),
            "status": "pending",
            "frettasafn_id": item.get("frettasafn_id", ""),
            "has_text": False,
            "notes": item.get("notes", ""),
        }
        inbox.append(entry)
        existing_urls.add(norm_url)
        added += 1

    _save_inbox(inbox)
    print(f"Batch import: {added} added, {skipped} skipped (duplicate/processed/rejected)")


def _set_status_bulk(ids: list[str], status: str, inbox: list[dict]) -> int:
    """Set status on multiple entries. Returns count of updated."""
    updated = 0
    for entry_id in ids:
        entry = _find_entry(inbox, entry_id)
        if entry:
            entry["status"] = status
            updated += 1
        else:
            print(f"  Not found: {entry_id}", file=sys.stderr)
    return updated


def cmd_reject(args: argparse.Namespace) -> None:
    inbox = _load_inbox()
    updated = _set_status_bulk(args.ids, "rejected", inbox)
    _save_inbox(inbox)

    # Also append to rejected_urls.txt
    with open(REJECTED_PATH, "a") as f:
        for entry_id in args.ids:
            entry = _find_entry(inbox, entry_id)
            if entry:
                f.write(f"{entry['url']}\n")

    print(f"Rejected {updated} articles (also added to {REJECTED_PATH}).")


def cmd_skip(args: argparse.Namespace) -> None:
    inbox = _load_inbox()
    updated = _set_status_bulk(args.ids, "skipped", inbox)
    _save_inbox(inbox)
    print(f"Skipped {updated} articles.")


def cmd_queue(args: argparse.Namespace) -> None:
    inbox = _load_inbox()
    updated = _set_status_bulk(args.ids, "queued", inbox)
    _save_inbox(inbox)
    print(f"Queued {updated} articles for analysis.")


def cmd_set_status(args: argparse.Namespace) -> None:
    if args.status not in VALID_STATUSES:
        print(f"Invalid status: {args.status}. Must be one of: {VALID_STATUSES}")
        sys.exit(1)
    inbox = _load_inbox()
    entry = _find_entry(inbox, args.id)
    if not entry:
        print(f"Not found: {args.id}")
        sys.exit(1)
    old = entry["status"]
    entry["status"] = args.status
    _save_inbox(inbox)
    print(f"{entry['id']}: {old} → {args.status}")


def cmd_save_text(args: argparse.Namespace) -> None:
    inbox = _load_inbox()
    entry = _find_entry(inbox, args.id)
    if not entry:
        print(f"Not found: {args.id}")
        sys.exit(1)

    TEXTS_DIR.mkdir(parents=True, exist_ok=True)
    text_path = TEXTS_DIR / f"{entry['id']}.md"
    text_path.write_text(Path(args.text_file).read_text())
    entry["has_text"] = True
    _save_inbox(inbox)
    print(f"Text saved: {text_path} ({text_path.stat().st_size} bytes)")


def cmd_known_ids(args: argparse.Namespace) -> None:
    """Output all known frettasafn article IDs (for scan_eu exclude_ids)."""
    ids: set[str] = set()

    # From inbox (all statuses — pending, processed, rejected, skipped, etc.)
    inbox = _load_inbox()
    for e in inbox:
        fid = e.get("frettasafn_id", "")
        if fid:
            ids.add(fid)

    # From article registry
    if REGISTRY_PATH.exists():
        registry = json.loads(REGISTRY_PATH.read_text())
        for e in registry:
            fid = e.get("frettasafn_id", "")
            if fid:
                ids.add(fid)

    if args.json:
        print(json.dumps(sorted(ids)))
    else:
        for fid in sorted(ids):
            print(fid)
    if not args.json:
        print(f"\n{len(ids)} known frettasafn IDs", file=sys.stderr)


def cmd_next(args: argparse.Namespace) -> None:
    """Output the next batch of articles ready for analysis.

    Returns HIGH priority pending/queued articles, preferring those with
    cached text. Outputs JSON for programmatic consumption or a human
    table. Newest articles first, but articles older than --backlog-days
    are flagged as backlog (still included, just annotated).
    """
    inbox = _load_inbox()
    limit = args.limit

    # Filter to actionable articles
    actionable = [
        e for e in inbox
        if e["status"] in ("pending", "queued")
        and e.get("priority") in ("high", "medium")
    ]

    if args.high_only:
        actionable = [e for e in actionable if e.get("priority") == "high"]

    if not actionable:
        if args.json:
            print("[]")
        else:
            print("No actionable articles in inbox.")
        return

    # Sort: text-cached first, then by date (newest first)
    def sort_key(e: dict) -> tuple:
        has_text = 0 if e.get("has_text") else 1
        # Negate date for descending
        date_str = e.get("date", "") or "0000-00-00"
        neg_date = "".join(chr(0x10FFFF - ord(c)) for c in date_str)
        return (has_text, neg_date)

    actionable.sort(key=sort_key)

    # HIGH before MEDIUM within the text/no-text groups
    priority_order = {"high": 0, "medium": 1}
    actionable.sort(
        key=lambda e: (
            0 if e.get("has_text") else 1,
            priority_order.get(e.get("priority", "medium"), 1),
            "".join(chr(0x10FFFF - ord(c)) for c in (e.get("date", "") or "0000-00-00")),
        )
    )

    batch = actionable[:limit]

    if args.json:
        print(json.dumps(batch, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"Next {len(batch)} articles for analysis:\n")
        for i, e in enumerate(batch, 1):
            text_marker = "T" if e.get("has_text") else " "
            age = ""
            if e.get("date"):
                try:
                    d = datetime.fromisoformat(e["date"])
                    days_old = (datetime.now(UTC) - d.replace(tzinfo=UTC)).days
                    if days_old > 7:
                        age = f" (backlog: {days_old}d old)"
                except (ValueError, TypeError):
                    pass
            print(
                f"  {i}. [{e.get('priority', '?').upper()}] {text_marker} "
                f"{e['id']}  {e.get('date', '?'):10}  "
                f"{e.get('title', '?')[:50]}{age}"
            )
        print(f"\n{len(actionable)} total actionable ({len(actionable) - len(batch)} more)")


def cmd_prune(args: argparse.Namespace) -> None:
    inbox = _load_inbox()
    cutoff = datetime.now(UTC) - timedelta(days=args.days)
    prunable = ("processed", "rejected", "skipped")

    keep = []
    removed = 0
    for e in inbox:
        if e["status"] in prunable:
            disc = e.get("discovered", "")
            if disc and datetime.fromisoformat(disc) < cutoff:
                # Remove cached text too
                text_path = TEXTS_DIR / f"{e['id']}.md"
                if text_path.exists():
                    text_path.unlink()
                removed += 1
                continue
        keep.append(e)

    _save_inbox(keep)
    print(f"Pruned {removed} entries older than {args.days} days. {len(keep)} remaining.")


def main():
    parser = argparse.ArgumentParser(description="Article inbox management")
    sub = parser.add_subparsers(dest="command")

    # status
    sub.add_parser("status", help="Show inbox summary")

    # list
    p_list = sub.add_parser("list", help="List inbox articles")
    p_list.add_argument("--status", choices=VALID_STATUSES, help="Filter by status")
    p_list.add_argument("--priority", choices=VALID_PRIORITIES, help="Filter by priority")

    # add
    p_add = sub.add_parser("add", help="Add a single article")
    p_add.add_argument("--url", required=True)
    p_add.add_argument("--title", default="")
    p_add.add_argument("--source", default="")
    p_add.add_argument("--date", default="")
    p_add.add_argument("--words", type=int, default=0)
    p_add.add_argument("--type", default="")
    p_add.add_argument("--topics", default="", help="Comma-separated topic slugs")
    p_add.add_argument("--priority", choices=VALID_PRIORITIES, default="medium")
    p_add.add_argument("--frettasafn-id", default="")
    p_add.add_argument("--notes", default="")
    p_add.add_argument("--text-file", help="Path to article text file to cache")

    # add-batch
    p_batch = sub.add_parser("add-batch", help="Import articles from JSON file")
    p_batch.add_argument("file", help="Path to JSON array of article objects")

    # reject, skip, queue
    for name, help_text in [
        ("reject", "Reject articles (also adds to rejected_urls.txt)"),
        ("skip", "Skip articles (not false positive, just not worth it)"),
        ("queue", "Queue articles for next analysis batch"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("ids", nargs="+", help="Article IDs")

    # set-status
    p_set = sub.add_parser("set-status", help="Set status of an article")
    p_set.add_argument("id", help="Article ID")
    p_set.add_argument("status", choices=VALID_STATUSES)

    # save-text
    p_text = sub.add_parser("save-text", help="Cache article text")
    p_text.add_argument("id", help="Article ID")
    p_text.add_argument("text_file", help="Path to text file")

    # known-ids
    p_known = sub.add_parser("known-ids", help="Output all known frettasafn article IDs")
    p_known.add_argument("--json", action="store_true", help="Output as JSON array")

    # next
    p_next = sub.add_parser("next", help="Show next articles ready for analysis")
    p_next.add_argument("--limit", type=int, default=5, help="Max articles to return")
    p_next.add_argument("--high-only", action="store_true", help="Only HIGH priority")
    p_next.add_argument("--json", action="store_true", help="Output as JSON")

    # prune
    p_prune = sub.add_parser("prune", help="Remove old processed/rejected entries")
    p_prune.add_argument("--days", type=int, default=30, help="Prune entries older than N days")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "status": cmd_status,
        "list": cmd_list,
        "add": cmd_add,
        "add-batch": cmd_add_batch,
        "reject": cmd_reject,
        "skip": cmd_skip,
        "queue": cmd_queue,
        "set-status": cmd_set_status,
        "save-text": cmd_save_text,
        "known-ids": cmd_known_ids,
        "next": cmd_next,
        "prune": cmd_prune,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
