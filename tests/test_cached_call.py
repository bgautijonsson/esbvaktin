"""Tests for the cached-call harness for the claim-assessor (cost-01).

Pure-function tests with an injected fake Anthropic client — no `anthropic`
dependency and no network calls. The live two-call measurement
(scripts/measure_assessor_cache.py) is billable and exercised manually.
"""

from __future__ import annotations


def test_split_separates_invariant_prefix_from_variable_claims():
    """The invariant instruction block (cacheable) is split from the per-article
    claims at the '## Fullyrðingar og heimildir' marker."""
    from esbvaktin.llm.cached_call import split_assessment_context

    md = (
        "INSTRUCTIONS — invariant block\n\nÍslenskar gæðareglur ...\n\n"
        "## Fullyrðingar og heimildir\n\n"
        "Fullyrðing 1 ... heimildir ..."
    )
    prefix, suffix = split_assessment_context(md, language="is")

    assert prefix == "INSTRUCTIONS — invariant block\n\nÍslenskar gæðareglur ..."
    assert suffix.startswith("## Fullyrðingar og heimildir")
    assert "Fullyrðing 1" in suffix


def test_split_with_no_marker_caches_nothing():
    """If the claims marker is absent (unexpected structure), cache nothing: the
    whole text is treated as variable so we never cache a wrong prefix."""
    from esbvaktin.llm.cached_call import split_assessment_context

    md = "some text with no claims marker at all"
    prefix, suffix = split_assessment_context(md)

    assert prefix == ""
    assert suffix == md


def test_build_cached_messages_caches_prefix_only():
    """cache_control lands on the invariant prefix block (so the API caches system
    + prefix), never on the variable suffix block."""
    from esbvaktin.llm.cached_call import build_cached_messages

    req = build_cached_messages("SYS", "INVARIANT", "VARIABLE")
    content = req["messages"][0]["content"]

    assert content[0]["text"] == "INVARIANT"
    assert content[0]["cache_control"]["type"] == "ephemeral"
    assert content[1]["text"] == "VARIABLE"
    assert "cache_control" not in content[1]
    assert req["system"] == "SYS"


def test_build_cached_messages_extended_ttl_and_empty_prefix():
    """An explicit ttl is carried onto the cache breakpoint; an empty prefix
    caches nothing (only the variable suffix block, uncached)."""
    from esbvaktin.llm.cached_call import build_cached_messages

    req = build_cached_messages("SYS", "INVARIANT", "VARIABLE", ttl="1h")
    assert req["messages"][0]["content"][0]["cache_control"]["ttl"] == "1h"

    req_empty = build_cached_messages("SYS", "", "VARIABLE")
    content = req_empty["messages"][0]["content"]
    assert len(content) == 1
    assert content[0]["text"] == "VARIABLE"
    assert "cache_control" not in content[0]


def test_parse_usage_extracts_cache_token_counts():
    """parse_usage maps an Anthropic-style usage object to the four counts."""
    from esbvaktin.llm.cached_call import parse_usage

    class FakeUsage:
        input_tokens = 120
        cache_creation_input_tokens = 3000
        cache_read_input_tokens = 0
        output_tokens = 450

    assert parse_usage(FakeUsage()) == {
        "input_tokens": 120,
        "cache_creation_input_tokens": 3000,
        "cache_read_input_tokens": 0,
        "output_tokens": 450,
    }


def test_parse_usage_defaults_missing_cache_fields_to_zero():
    """When the SDK omits cache_* fields (None or absent), they read as 0."""
    from esbvaktin.llm.cached_call import parse_usage

    class Sparse:
        input_tokens = 50
        cache_creation_input_tokens = None
        output_tokens = 200
        # cache_read_input_tokens absent entirely

    u = parse_usage(Sparse())
    assert u["input_tokens"] == 50
    assert u["cache_creation_input_tokens"] == 0
    assert u["cache_read_input_tokens"] == 0


def test_call_cached_forwards_payload_and_returns_text_and_usage():
    """call_cached builds the cached payload, calls the injected client, and
    returns (response_text, parsed_usage). No network."""
    from esbvaktin.llm.cached_call import call_cached

    captured: dict = {}

    class FakeBlock:
        text = '[{"verdict": "supported"}]'

    class FakeUsage:
        input_tokens = 10
        cache_creation_input_tokens = 3000
        cache_read_input_tokens = 0
        output_tokens = 20

    class FakeResponse:
        content = [FakeBlock()]
        usage = FakeUsage()

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

    class FakeClient:
        messages = FakeMessages()

    text, usage = call_cached(
        FakeClient(),
        system="SYS",
        prefix="INVARIANT",
        suffix="## Fullyrðingar og heimildir\n\nVARIABLE",
        model="claude-opus-4-8",
        max_tokens=2048,
    )

    assert text == '[{"verdict": "supported"}]'
    assert usage["cache_creation_input_tokens"] == 3000
    assert captured["model"] == "claude-opus-4-8"
    assert captured["max_tokens"] == 2048
    assert captured["system"] == "SYS"
    # the cache breakpoint rode through onto the prefix block
    assert captured["messages"][0]["content"][0]["cache_control"]["type"] == "ephemeral"


def test_assessor_system_prompt_strips_frontmatter_and_adds_json_override(tmp_path):
    """The SDK system prompt keeps the agent's Icelandic rules but drops the
    frontmatter and instructs a JSON-array response (no Write tool in a bare call)."""
    from esbvaktin.llm.cached_call import assessor_system_prompt

    agent = tmp_path / "claim-assessor.md"
    agent.write_text(
        "---\nname: claim-assessor\nmodel: opus\n---\n\n"
        "# Fullyrðingamat\n\n- **Óhlutdrægni**: metið jafnt.\n"
        "Skrifaðu mat í `_assessments.json`.\n",
        encoding="utf-8",
    )

    sp = assessor_system_prompt(agent_path=agent)

    assert "Óhlutdrægni" in sp  # assessment rules carried over from the body
    assert "name: claim-assessor" not in sp  # frontmatter stripped
    assert "JSON" in sp  # response-format instruction present
    assert "svari" in sp.lower()  # "... beint í svari þínu" (return in your response)
