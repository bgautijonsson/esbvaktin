#!/usr/bin/env python3
"""Check evidence source URLs for link rot, content drift, and soft 404s.

Three-tier verification:
  1. HTTP reachability — is the URL alive? (HEAD, then GET fallback)
  2. Redirect detection — did it redirect to a homepage or generic page?
  3. Content verification — does the page still contain the source_excerpt?

The source_excerpt is a short distinctive phrase from the source page that
the evidence statement is based on. If the page loads but the excerpt is
gone, the link is effectively broken (content drift).

Usage:
    uv run python scripts/check_evidence_urls.py check             # Check all URLs
    uv run python scripts/check_evidence_urls.py check --topic fisheries  # Check one topic
    uv run python scripts/check_evidence_urls.py check --recheck   # Re-check previously checked
    uv run python scripts/check_evidence_urls.py report            # Show link health report
    uv run python scripts/check_evidence_urls.py populate          # Auto-populate excerpts (fetch + match)
    uv run python scripts/check_evidence_urls.py populate --dry-run
    uv run python scripts/check_evidence_urls.py status            # Quick summary
"""

from __future__ import annotations

import re
import sys
import time
from collections import Counter
from difflib import SequenceMatcher
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

from esbvaktin.ground_truth.operations import get_connection

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REQUEST_TIMEOUT = 15
DELAY_BETWEEN_REQUESTS = 0.5  # polite crawling
USER_AGENT = "ESBvaktin-LinkChecker/1.0 (+https://esbvaktin.is)"

# Domains where we can extract text (others may be PDFs, APIs, etc.)
EXTRACTABLE_DOMAINS = {
    "www.althingi.is", "eur-lex.europa.eu", "ec.europa.eu",
    "enlargement.ec.europa.eu", "neighbourhood-enlargement.ec.europa.eu",
    "www.efta.int", "www.government.is", "www.stjornarradid.is",
    "www.europarl.europa.eu", "www.eftasurv.int", "www.ecb.europa.eu",
    "eeagrants.org", "island.is", "www.sedlabanki.is", "orkustofnun.is",
    "fel.hi.is", "www.oecd.org", "commission.europa.eu",
    "www.statice.is", "data.worldbank.org", "www.gallup.is",
    "en.wikipedia.org", "is.wikipedia.org",
}

# Domains that serve data APIs / statistical tables (not HTML pages)
NON_HTML_DOMAINS = {"px.hagstofa.is", "data.worldbank.org"}

# Known domain migrations
DOMAIN_REDIRECTS = {
    "enlargement.ec.europa.eu": "neighbourhood-enlargement.ec.europa.eu",
}

# ---------------------------------------------------------------------------
# URL checking
# ---------------------------------------------------------------------------


def _is_homepage_redirect(original_url: str, final_url: str) -> bool:
    """Detect if a redirect landed on a homepage or generic page."""
    orig = urlparse(original_url)
    final = urlparse(final_url)

    # Different domain entirely
    if orig.netloc != final.netloc:
        # Known migration?
        if DOMAIN_REDIRECTS.get(orig.netloc) == final.netloc:
            return False  # Expected migration, not a broken redirect
        return True

    # Redirected to root
    if final.path in ("", "/", "/en", "/en/", "/is", "/is/"):
        return True

    # Redirected to a much shorter path (lost specificity)
    orig_depth = orig.path.strip("/").count("/")
    final_depth = final.path.strip("/").count("/")
    if orig_depth >= 2 and final_depth == 0:
        return True

    return False


def check_url(url: str) -> dict:
    """Check a single URL and return status info.

    Returns dict with keys:
      - status: 'ok' | 'redirect_homepage' | 'content_moved' | 'error' | 'timeout' | 'dns_error'
      - http_code: int or None
      - final_url: str or None
      - error: str or None
    """
    if not url or not url.startswith("http"):
        return {"status": "invalid", "http_code": None, "final_url": None, "error": "not a URL"}

    headers = {"User-Agent": USER_AGENT}

    try:
        with httpx.Client(follow_redirects=True, timeout=REQUEST_TIMEOUT) as client:
            # Try HEAD first (cheaper)
            try:
                resp = client.head(url, headers=headers)
            except httpx.HTTPError:
                resp = client.get(url, headers=headers)

            # Some servers return 405 for HEAD
            if resp.status_code == 405:
                resp = client.get(url, headers=headers)

            final_url = str(resp.url)

            if resp.status_code >= 400:
                return {
                    "status": "error",
                    "http_code": resp.status_code,
                    "final_url": final_url,
                    "error": f"HTTP {resp.status_code}",
                }

            if _is_homepage_redirect(url, final_url):
                return {
                    "status": "redirect_homepage",
                    "http_code": resp.status_code,
                    "final_url": final_url,
                    "error": "redirected to homepage/generic page",
                }

            if final_url != url:
                return {
                    "status": "redirect_ok",
                    "http_code": resp.status_code,
                    "final_url": final_url,
                    "error": None,
                }

            return {
                "status": "ok",
                "http_code": resp.status_code,
                "final_url": final_url,
                "error": None,
            }

    except httpx.TimeoutException:
        return {"status": "timeout", "http_code": None, "final_url": None, "error": "timeout"}
    except httpx.ConnectError as e:
        return {"status": "dns_error", "http_code": None, "final_url": None, "error": str(e)}
    except httpx.HTTPError as e:
        return {"status": "error", "http_code": None, "final_url": None, "error": str(e)}


def fetch_page_text(url: str) -> str | None:
    """Fetch a page and extract its text content using trafilatura."""
    try:
        import trafilatura

        downloaded = trafilatura.fetch_url(url)
        if downloaded is None:
            return None
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
        return text
    except Exception:
        return None


def verify_excerpt(url: str, excerpt: str) -> dict:
    """Fetch the page and check if the excerpt is still present.

    Returns dict with:
      - content_status: 'confirmed' | 'missing' | 'partial_match' | 'fetch_failed'
      - similarity: float (0-1) best match ratio if partial
    """
    text = fetch_page_text(url)
    if text is None:
        return {"content_status": "fetch_failed", "similarity": 0.0}

    # Normalise whitespace for comparison
    text_norm = re.sub(r"\s+", " ", text.lower().strip())
    excerpt_norm = re.sub(r"\s+", " ", excerpt.lower().strip())

    # Exact substring match
    if excerpt_norm in text_norm:
        return {"content_status": "confirmed", "similarity": 1.0}

    # Fuzzy match — the excerpt may have minor differences (encoding, formatting)
    # Use sliding window over text to find best match region
    excerpt_len = len(excerpt_norm)
    best_ratio = 0.0

    # Sample positions to avoid O(n*m) on very long pages
    step = max(1, len(text_norm) // 500)
    for i in range(0, len(text_norm) - excerpt_len + 1, step):
        window = text_norm[i : i + excerpt_len]
        ratio = SequenceMatcher(None, excerpt_norm, window).ratio()
        best_ratio = max(best_ratio, ratio)
        if best_ratio > 0.85:
            return {"content_status": "confirmed", "similarity": best_ratio}

    if best_ratio > 0.6:
        return {"content_status": "partial_match", "similarity": best_ratio}

    return {"content_status": "missing", "similarity": best_ratio}


# ---------------------------------------------------------------------------
# Excerpt auto-population
# ---------------------------------------------------------------------------


def _extract_key_terms(statement: str) -> list[str]:
    """Extract distinctive terms from an evidence statement for fuzzy page matching.

    Looks for numbers, percentages, proper nouns, and technical terms.
    """
    terms = []

    # Numbers and percentages (e.g. "75%", "€1.2 billion", "2024")
    terms.extend(re.findall(r"\d+(?:\.\d+)?%", statement))
    terms.extend(re.findall(r"€[\d.,]+ (?:billion|million|milljón|milljarð)", statement, re.IGNORECASE))
    terms.extend(re.findall(r"\b\d{4}\b", statement))  # years

    # Article references (e.g. "Article 49", "Chapter 13")
    terms.extend(re.findall(r"(?:Article|Chapter|Annex|Protocol)\s+\d+", statement, re.IGNORECASE))

    # Specific proper nouns and technical terms that are likely unique to the source
    # (words starting with uppercase that aren't sentence-starters)
    words = statement.split()
    for i, w in enumerate(words):
        if i > 0 and w[0].isupper() and len(w) > 3 and w not in {"The", "This", "That", "These", "Under"}:
            terms.append(w.rstrip(".,;:"))

    return terms


def _find_best_excerpt(page_text: str, statement: str) -> str | None:
    """Find the sentence in page_text that best matches the evidence statement.

    Uses two strategies:
    1. Full-sentence similarity (for sources that closely mirror our statement)
    2. Key-term matching (for statistical/data sources where our statement is a synthesis)

    Returns a 100-300 char excerpt, or None if no good match.
    """
    # Split into sentences (rough but effective)
    sentences = re.split(r"(?<=[.!?])\s+", page_text)
    if not sentences:
        return None

    statement_lower = statement.lower()
    best_sentence = None
    best_ratio = 0.0

    # Strategy 1: Full-sentence similarity
    for sent in sentences:
        sent_stripped = sent.strip()
        if len(sent_stripped) < 20:
            continue

        ratio = SequenceMatcher(None, statement_lower, sent_stripped.lower()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_sentence = sent_stripped

    if best_ratio >= 0.25 and best_sentence is not None:
        if len(best_sentence) > 300:
            best_sentence = best_sentence[:297].rsplit(" ", 1)[0] + "..."
        return best_sentence

    # Strategy 2: Key-term matching — find a sentence containing the most key terms
    key_terms = _extract_key_terms(statement)
    if len(key_terms) < 2:
        return None

    best_term_sentence = None
    best_term_count = 0

    for sent in sentences:
        sent_stripped = sent.strip()
        if len(sent_stripped) < 30:
            continue

        sent_lower = sent_stripped.lower()
        matches = sum(1 for t in key_terms if t.lower() in sent_lower)
        if matches > best_term_count:
            best_term_count = matches
            best_term_sentence = sent_stripped

    # Need at least 2 key terms matching to be confident
    if best_term_count >= 2 and best_term_sentence is not None:
        if len(best_term_sentence) > 300:
            best_term_sentence = best_term_sentence[:297].rsplit(" ", 1)[0] + "..."
        return best_term_sentence

    return None


def populate_excerpts(*, dry_run: bool = False) -> None:
    """Fetch pages and auto-populate source_excerpt for entries that lack one."""
    conn = get_connection()

    rows = conn.execute("""
        SELECT evidence_id, source_url, statement, topic
        FROM evidence
        WHERE source_url IS NOT NULL
          AND source_url LIKE 'http%'
          AND source_excerpt IS NULL
        ORDER BY topic, evidence_id
    """).fetchall()

    print(f"Entries needing excerpts: {len(rows)}")
    if not rows:
        conn.close()
        return

    populated = 0
    skipped_domains = 0
    fetch_failed = 0
    no_match = 0

    for eid, url, statement, topic in rows:
        parsed = urlparse(url)
        domain = parsed.netloc

        # Skip non-HTML sources
        if domain in NON_HTML_DOMAINS:
            skipped_domains += 1
            continue

        print(f"  {eid}: fetching {domain}...", end=" ", flush=True)
        time.sleep(DELAY_BETWEEN_REQUESTS)

        page_text = fetch_page_text(url)
        if page_text is None:
            print("fetch failed")
            fetch_failed += 1
            continue

        excerpt = _find_best_excerpt(page_text, statement)
        if excerpt is None:
            print("no matching text found")
            no_match += 1
            continue

        print(f"found ({len(excerpt)} chars)")

        if not dry_run:
            conn.execute(
                "UPDATE evidence SET source_excerpt = %s WHERE evidence_id = %s",
                (excerpt, eid),
            )
            conn.commit()

        populated += 1

    print(f"\nPopulated: {populated}")
    print(f"Skipped (non-HTML domain): {skipped_domains}")
    print(f"Fetch failed: {fetch_failed}")
    print(f"No matching text: {no_match}")

    conn.close()


# ---------------------------------------------------------------------------
# Check command
# ---------------------------------------------------------------------------


def check_all(*, topic: str | None = None, recheck: bool = False) -> None:
    """Check all evidence URLs and update status in DB."""
    conn = get_connection()

    where_clauses = ["source_url IS NOT NULL", "source_url LIKE 'http%%'"]
    params: list = []

    if topic:
        where_clauses.append("topic = %s")
        params.append(topic)

    if not recheck:
        where_clauses.append("(source_url_checked IS NULL OR source_url_checked < CURRENT_DATE - INTERVAL '7 days')")

    query = f"""
        SELECT evidence_id, source_url, source_excerpt, topic
        FROM evidence
        WHERE {' AND '.join(where_clauses)}
        ORDER BY topic, evidence_id
    """
    rows = conn.execute(query, params).fetchall()

    print(f"URLs to check: {len(rows)}")
    if not rows:
        conn.close()
        return

    results = Counter()

    for eid, url, excerpt, etopic in rows:
        print(f"  {eid}: ", end="", flush=True)
        time.sleep(DELAY_BETWEEN_REQUESTS)

        url_result = check_url(url)
        status = url_result["status"]

        # If URL is ok and we have an excerpt, verify content
        content_status = None
        if status in ("ok", "redirect_ok") and excerpt:
            check_target = url_result["final_url"] or url
            content_result = verify_excerpt(check_target, excerpt)
            content_status = content_result["content_status"]

            if content_status == "missing":
                status = "content_drift"
            elif content_status == "partial_match":
                status = "content_partial"
            # confirmed → keep status as ok/redirect_ok

        results[status] += 1

        # Compose final status string
        if content_status and content_status != "confirmed":
            final_status = f"{status}"
        else:
            final_status = status

        error_note = url_result.get("error", "")
        print(f"{final_status}" + (f" — {error_note}" if error_note else ""))

        # Update DB
        conn.execute(
            """UPDATE evidence
               SET source_url_status = %s,
                   source_url_checked = CURRENT_DATE
               WHERE evidence_id = %s""",
            (final_status, eid),
        )
        conn.commit()

    print(f"\n{'='*50}")
    print("Results:")
    for status, count in results.most_common():
        print(f"  {status}: {count}")

    conn.close()


# ---------------------------------------------------------------------------
# Report command
# ---------------------------------------------------------------------------


def show_report() -> None:
    """Show link health report from stored check results."""
    conn = get_connection()

    # Summary
    total = conn.execute("SELECT COUNT(*) FROM evidence WHERE source_url LIKE 'http%'").fetchone()[0]
    checked = conn.execute("SELECT COUNT(*) FROM evidence WHERE source_url_checked IS NOT NULL").fetchone()[0]
    print(f"Evidence URLs: {total} total, {checked} checked\n")

    # Status breakdown
    statuses = conn.execute("""
        SELECT source_url_status, COUNT(*)
        FROM evidence
        WHERE source_url_status IS NOT NULL
        GROUP BY source_url_status
        ORDER BY COUNT(*) DESC
    """).fetchall()

    if statuses:
        print("Status breakdown:")
        for status, count in statuses:
            marker = "" if status in ("ok", "redirect_ok") else " ⚠"
            print(f"  {status}: {count}{marker}")

    # Problem URLs
    problems = conn.execute("""
        SELECT evidence_id, topic, source_url, source_url_status, source_name
        FROM evidence
        WHERE source_url_status IS NOT NULL
          AND source_url_status NOT IN ('ok', 'redirect_ok')
        ORDER BY source_url_status, topic, evidence_id
    """).fetchall()

    if problems:
        print(f"\nProblems ({len(problems)}):")
        current_status = None
        for eid, topic, url, status, name in problems:
            if status != current_status:
                current_status = status
                print(f"\n  [{status}]")
            print(f"    {eid} ({topic}): {name}")
            print(f"      {url}")

    # Unchecked
    unchecked = conn.execute("""
        SELECT COUNT(*) FROM evidence
        WHERE source_url LIKE 'http%'
          AND source_url_checked IS NULL
    """).fetchone()[0]
    if unchecked:
        print(f"\nUnchecked: {unchecked} URLs (run 'check' to verify)")

    # Excerpt coverage
    has_excerpt = conn.execute("""
        SELECT COUNT(*) FROM evidence
        WHERE source_url LIKE 'http%' AND source_excerpt IS NOT NULL
    """).fetchone()[0]
    print(f"\nExcerpt coverage: {has_excerpt}/{total} ({100*has_excerpt/total:.0f}%)")

    conn.close()


def show_status() -> None:
    """Quick one-line summary."""
    conn = get_connection()

    total = conn.execute("SELECT COUNT(*) FROM evidence WHERE source_url LIKE 'http%'").fetchone()[0]
    checked = conn.execute("SELECT COUNT(*) FROM evidence WHERE source_url_checked IS NOT NULL").fetchone()[0]
    ok = conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE source_url_status IN ('ok', 'redirect_ok')"
    ).fetchone()[0]
    problems = conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE source_url_status IS NOT NULL AND source_url_status NOT IN ('ok', 'redirect_ok')"
    ).fetchone()[0]
    has_excerpt = conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE source_url LIKE 'http%' AND source_excerpt IS NOT NULL"
    ).fetchone()[0]

    print(f"Link health: {total} URLs, {checked} checked ({ok} ok, {problems} problems)")
    print(f"Excerpt coverage: {has_excerpt}/{total} ({100*has_excerpt/total:.0f}%)")

    conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "check":
        topic = None
        recheck = False
        args = sys.argv[2:]
        while args:
            if args[0] == "--topic" and len(args) > 1:
                topic = args[1]
                args = args[2:]
            elif args[0] == "--recheck":
                recheck = True
                args = args[1:]
            else:
                print(f"Unknown argument: {args[0]}")
                sys.exit(1)
        check_all(topic=topic, recheck=recheck)

    elif cmd == "populate":
        dry_run = "--dry-run" in sys.argv
        populate_excerpts(dry_run=dry_run)

    elif cmd == "set-excerpt":
        # Usage: set-excerpt EVIDENCE_ID "excerpt text"
        if len(sys.argv) < 4:
            print("Usage: set-excerpt EVIDENCE_ID \"excerpt text\"")
            sys.exit(1)
        eid = sys.argv[2]
        excerpt_text = sys.argv[3]
        conn = get_connection()
        result = conn.execute(
            "UPDATE evidence SET source_excerpt = %s WHERE evidence_id = %s RETURNING evidence_id",
            (excerpt_text, eid),
        ).fetchone()
        conn.commit()
        if result:
            print(f"Set excerpt for {eid} ({len(excerpt_text)} chars)")
        else:
            print(f"Evidence ID not found: {eid}")
        conn.close()

    elif cmd == "show-excerpt":
        # Usage: show-excerpt EVIDENCE_ID
        if len(sys.argv) < 3:
            print("Usage: show-excerpt EVIDENCE_ID")
            sys.exit(1)
        eid = sys.argv[2]
        conn = get_connection()
        row = conn.execute(
            "SELECT source_url, source_excerpt, source_url_status FROM evidence WHERE evidence_id = %s",
            (eid,),
        ).fetchone()
        if row:
            url, excerpt, status = row
            print(f"URL: {url}")
            print(f"Status: {status or 'unchecked'}")
            print(f"Excerpt: {excerpt or '(none)'}")
        else:
            print(f"Evidence ID not found: {eid}")
        conn.close()

    elif cmd == "report":
        show_report()

    elif cmd == "status":
        show_status()

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
