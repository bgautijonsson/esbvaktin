"""iseval PipelineAdapter for ESBvaktin's correction-correctness family.

This shim is the seam between ESBvaktin's local Icelandic correction layers and
the shared `iseval` harness. It implements `iseval.adapter.PipelineAdapter`:
given one sentence, it runs the real correction layers and returns each finding
as an `iseval.models.PipelineFlag`.

Layers wired (correction family — things that would flag a putative error):
  - GreynirCorrect (`check_with_library`)  → layer="greynir"
  - confusable-word scanner (`check_confusables`) → layer="confusables"
  - EU terminology checker (`check_eu_terms`)     → layer="eu_terms"

Deliberately NOT wired in Phase 0:
  - Málstaður API (`check_with_malfridur`) — costs money (MALSTADUR_API_KEY) and
    needs network; out of scope for an offline baseline.
  - Icegrams naturalness / `run_heuristic_checks` — the naturalness family, not
    correction; and partly dead code per project notes.
  - BÍN inflection check (`check_inflections`) — a dictionary-membership *check*,
    not a correction layer; it flags any out-of-BÍN token (proper nouns, EU
    coinages) and would dominate the FP rate without telling us about the
    correction pipeline.
  - GreynirEngine deep parse — a parseability check, not a correction.

Char offsets: ESBvaktin's layers report line/token positions and a matched
substring rather than character spans, so this shim best-effort locates the
offending substring in the sentence (`str.find`); when it can't, it falls back
to (0, 0). Per-sentence fp_rate is unaffected by span precision (any flag on a
golden is a false positive), but honest spans aid inspection.

Install: `iseval` is brought in for local dev via an editable path install:
    uv pip install -e ~/iseval
Run from the esbvaktin venv (which has reynir_correct etc.):
    ~/esbvaktin/.venv/bin/python -m iseval run \
        --product esbvaktin --family correction \
        --adapter eval.iseval_adapter:EsbvaktinAdapter \
        --golden ~/esbvaktin/eval/golden \
        --out ~/esbvaktin/eval/baseline.json
(`eval.iseval_adapter` resolves because the harness is invoked with CWD at the
esbvaktin repo root, so `eval/` is an importable package directory.)
"""

from __future__ import annotations

import re

from iseval.models import PipelineFlag

from esbvaktin.corrections.confusables import check_confusables
from esbvaktin.corrections.eu_terms import check_eu_terms
from esbvaktin.corrections.greynir import check_with_library

# Pull the corrected word out of a GreynirCorrect annotation message such as
#   "Orðið 'setníng' var leiðrétt í 'setning'"
# so we can locate the offending span in the original sentence.
_GREYNIR_WORD_RE = re.compile(r"'([^']+)'")


def _span_for(needle: str, haystack: str) -> tuple[int, int]:
    """Best-effort character span of ``needle`` in ``haystack``; (0, 0) if absent."""
    if not needle:
        return (0, 0)
    idx = haystack.find(needle)
    if idx == -1:
        return (0, 0)
    return (idx, idx + len(needle))


class EsbvaktinAdapter:
    """ESBvaktin correction pipeline, exposed to iseval one sentence at a time."""

    product = "esbvaktin"

    def flags_for_sentence(self, text: str) -> list[PipelineFlag]:
        flags: list[PipelineFlag] = []

        # ── Layer 1: GreynirCorrect spelling/grammar ────────────────────
        # check_with_library wants (text, line_num) pairs; one sentence → line 1.
        for r in check_with_library([(text, 1)]):
            msg = r.get("text", "")
            m = _GREYNIR_WORD_RE.search(msg)
            needle = m.group(1) if m else ""
            start, end = _span_for(needle, text)
            flags.append(
                PipelineFlag(
                    category=r.get("code", "greynir"),
                    start=start,
                    end=end,
                    message=msg,
                    layer="greynir",
                )
            )

        # ── Layer 2: confusable-word scanner ────────────────────────────
        for w in check_confusables(text):
            match = w.get("match", "")
            start, end = _span_for(match, text)
            flags.append(
                PipelineFlag(
                    category="confusable",
                    start=start,
                    end=end,
                    message=w.get("description", ""),
                    layer="confusables",
                )
            )

        # ── Layer 3: EU terminology checker ─────────────────────────────
        for w in check_eu_terms(text):
            found = w.get("found", "")
            start, end = _span_for(found, text)
            flags.append(
                PipelineFlag(
                    category=f"eu_terms:{w.get('type', 'issue')}",
                    start=start,
                    end=end,
                    message=str(w.get("suggestion", "")),
                    layer="eu_terms",
                )
            )

        return flags
