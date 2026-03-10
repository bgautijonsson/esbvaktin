"""GreynirEngine deep CFG parsing — flag unparseable sentences.

Adapted from Þingfréttir with minimal changes.
"""

try:
    from reynir import Greynir

    _HAS_GREYNIR = True
except ImportError:
    _HAS_GREYNIR = False


def deep_parse(
    sentences: list[tuple[str, int]],
) -> list[dict]:
    """Run full CFG parsing on each sentence. Flag those with no parse tree."""
    if not _HAS_GREYNIR:
        return []

    g = Greynir()
    flagged = []

    for text, line_num in sentences:
        # Skip very short sentences (fragments)
        if len(text.split()) < 4:
            continue
        try:
            result = g.parse_single(text)
            if result.tree is None:
                flagged.append(
                    {
                        "line": line_num,
                        "text": text,
                        "num_tokens": result.num_tokens
                        if hasattr(result, "num_tokens")
                        else len(text.split()),
                    }
                )
        except Exception:
            flagged.append(
                {
                    "line": line_num,
                    "text": text,
                    "num_tokens": len(text.split()),
                }
            )

    return flagged


def format_deep_parse_results(flagged: list[dict], filename: str) -> int:
    """Print deep parse results. Returns count of unparseable sentences."""
    if not flagged:
        print(f"  {filename}: All sentences parsed successfully")
        return 0

    for f in flagged:
        display = f["text"][:100] + "..." if len(f["text"]) > 100 else f["text"]
        print(f"  L{f['line']:3d} [PARSE FAIL] ({f['num_tokens']} tokens)")
        print(f'        "{display}"')

    return len(flagged)
