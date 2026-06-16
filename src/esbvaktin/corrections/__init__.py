"""ESBvaktin Icelandic-correction CLI wrapper.

The correction *layers* (GreynirCorrect, Icegrams naturalness, BÍN inflections,
confusable scanner, EU-terminology, GreynirEngine deep parse, Málstaður) now live
in the shared ``ispipeline`` package — the union of the esbvaktin + althingi forks,
pinned by git ref and gated by iseval. Import them from there:

    from ispipeline import check_with_library, check_eu_terms  # etc.

This package retains only ESBvaktin's project-specific CLI orchestration in
``cli.py`` — JSON-field extraction, the ASCII/Unicode gate, and the
``check`` / ``check-editorial`` / ``check-claims`` subcommands — which delegates to
``ispipeline`` for every layer.
"""
