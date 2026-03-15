# MCP Cost Awareness

Applies to all code and agent prompts that use MCP tools.

## Málstaður API (mideind MCP server)

- **Pricing:** ~1 kr per 100 characters (grammar, correction, translation). Speech recognition: 2,000 kr/hour.
- **Always send full text in one call**, never sentence-by-sentence or paragraph-by-paragraph.
- Agents should call `correct_text` **at most once per document**.
- Use `check_grammar` only when uncertain — don't run it routinely on every batch.
- Do not call both `check_grammar` AND `correct_text` on the same text — pick one based on intent (review vs fix).
- Do not call grammar tools on non-Icelandic text — they only support Icelandic.

## Málstaður translate API

- Rate-limited: use 0.5s delay between calls + retry with exponential backoff.
- Batch translations where possible to minimise call count.

## General

- Never re-check or re-translate text that has already been processed in the same session.
- For speech transcription, poll `get_transcription_status` at reasonable intervals (5-10s), not in a tight loop.
