"""Icelandic text correction pipeline for ESBvaktin assessments.

This package re-exports all public functions. The implementation is split across:

  - greynir.py: GreynirCorrect grammar/spelling checks
  - naturalness.py: Icegrams trigram probability scoring
  - inflections.py: BÍN inflection validation
  - confusables.py: LLM confusable-word pattern scanner (incl. ASCII detection)
  - eu_terms.py: EU terminology consistency checker
  - parsing.py: GreynirEngine deep CFG parsing
  - cli.py: CLI entry point and orchestration

All callers should continue importing from esbvaktin.corrections directly.
All optional dependencies degrade gracefully (try/except ImportError).
"""

from esbvaktin.corrections.greynir import (  # noqa: F401
    check_with_library,
    check_with_api,
    apply_fixes,
    apply_fixes_to_text,
    format_results,
    AUTO_FIX_CODES,
    PHRASE_FIX_CODES,
)
from esbvaktin.corrections.naturalness import (  # noqa: F401
    score_naturalness,
    format_naturalness_results,
    run_heuristic_checks,
    format_heuristic_results,
    check_monotonous_openings,
    check_hedging,
    check_missing_icelandic_chars,
    check_overformal_register,
    _HAS_ICEGRAMS,
)
from esbvaktin.corrections.inflections import (  # noqa: F401
    check_inflections,
    format_inflection_results,
    _extract_words,
    _HAS_ISLENSKA,
)
from esbvaktin.corrections.confusables import (  # noqa: F401
    CONFUSABLE_PATTERNS,
    check_confusables,
    format_confusable_results,
)
from esbvaktin.corrections.eu_terms import (  # noqa: F401
    check_eu_terms,
    format_eu_term_results,
)
from esbvaktin.corrections.parsing import (  # noqa: F401
    deep_parse,
    format_deep_parse_results,
    _HAS_GREYNIR,
)
