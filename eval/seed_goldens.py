"""Seed golden Icelandic sentences from ESBvaktin's exemplar banks.

Extracts the GOLD / FORDÆMI known-good passages (blockquote lines) from
  knowledge/exemplars_is.md
  knowledge/exemplars_editorial_is.md
and writes them — one sentence per line — into eval/golden/*.md.

Only FORDÆMI (good exemplars) are taken. Everything from the first
ANDFORDÆMI / FYRIR / ANDMYNSTUR heading onward is excluded, because those
sections contain deliberately-broken anti-exemplars (ASCII transliteration,
hedging, English terms) that MUST NOT become goldens — they are exactly the
errors the pipeline should flag.

Each blockquote passage is split into sentences so the per-sentence fp_rate is
computed over real sentence units. Sentences shorter than a small floor are
dropped (fragments like "Eina." carry no signal).

Run from the esbvaktin repo root:
    .venv/bin/python eval/seed_goldens.py
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KNOWLEDGE = REPO / "knowledge"
OUT_DIR = REPO / "eval" / "golden"

# Headings that mark the end of the good-exemplar zone. Once any of these is
# seen, stop collecting blockquotes from that file.
_STOP_HEADINGS = ("ANDFORDÆMI", "ANDMYNSTUR", "FYRIR/EFTIR", "FYRIR (", "FYRIR/")

_MIN_SENTENCE_LEN = 25  # chars — drop fragments


def _collect_blockquotes(md_path: Path) -> list[str]:
    """Return blockquote text lines that appear before any stop heading."""
    quotes: list[str] = []
    for raw in md_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#"):
            heading = line.lstrip("#").strip().upper()
            if any(stop in heading for stop in _STOP_HEADINGS):
                break  # everything after is anti-exemplar / before/after demo
            continue
        if line.startswith(">"):
            body = line[1:].strip()
            if body:
                quotes.append(body)
    return quotes


def _split_sentences(passage: str) -> list[str]:
    """Split a passage into sentences on terminal punctuation + whitespace."""
    parts = re.split(r"(?<=[.!?])\s+", passage.strip())
    out = []
    for p in parts:
        p = p.strip()
        if len(p) >= _MIN_SENTENCE_LEN:
            out.append(p)
    return out


def seed_file(src: Path, out_name: str) -> int:
    passages = _collect_blockquotes(src)
    sentences: list[str] = []
    seen: set[str] = set()
    for passage in passages:
        for sent in _split_sentences(passage):
            if sent not in seen:
                seen.add(sent)
                sentences.append(sent)

    out_path = OUT_DIR / out_name
    header = f"# Golden Icelandic sentences extracted from {src.name}\n"
    header += "# (FORDÆMI / GOLD only — anti-exemplars excluded). One sentence per line.\n\n"
    out_path.write_text(header + "\n".join(sentences) + "\n", encoding="utf-8")
    return len(sentences)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n1 = seed_file(KNOWLEDGE / "exemplars_is.md", "assessment_goldens_is.md")
    n2 = seed_file(KNOWLEDGE / "exemplars_editorial_is.md", "editorial_goldens_is.md")
    print(f"assessment_goldens_is.md: {n1} sentences")
    print(f"editorial_goldens_is.md:  {n2} sentences")
    print(f"total goldens:            {n1 + n2}")


if __name__ == "__main__":
    main()
