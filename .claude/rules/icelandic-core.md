# Icelandic Language: Core Principles

These rules apply to ALL Icelandic text generation in the project.

1. **Write Icelandic first** — compose from evidence data, never translate from English prose. Icelandic output must be original composition, not translation.
2. **Pattern-match** against `knowledge/exemplars_is.md` (gold-standard assessment passages + anti-exemplars).
3. **Self-review** against the 7-point checklist in `ICELANDIC.md § Self-Review` before finalising.
4. **Unicode always** — every Icelandic paragraph must contain characters from {þ, ð, á, é, í, ó, ú, ý, æ, ö}. If it doesn't, the output is defective — rewrite immediately.

Full reference: `ICELANDIC.md` (10 LLM failure patterns, morphology tools, post-processing layers).
Grammar deep dive: `.claude/rules/icelandic-writing.md` (auto-loaded for `*_is.*` files).
