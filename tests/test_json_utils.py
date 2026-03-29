"""Tests for the shared Icelandic quote JSON sanitiser."""

import json

from esbvaktin.utils.json_utils import extract_json, sanitise_icelandic_quotes


class TestSanitiseIcelandicQuotes:
    def test_replaces_left_double_quotation(self):
        # „ (U+201E) should become escaped quote
        assert '\\"' in sanitise_icelandic_quotes("\u201e")

    def test_replaces_right_double_quotation(self):
        # " (U+201D) should become escaped quote
        assert '\\"' in sanitise_icelandic_quotes("\u201d")

    def test_already_valid_json_unchanged(self):
        text = '{"title": "Normal quotes"}'
        result = sanitise_icelandic_quotes(text)
        assert json.loads(result) == {"title": "Normal quotes"}

    def test_preserves_escaped_quotes(self):
        text = r'{"text": "He said \"hello\""}'
        result = sanitise_icelandic_quotes(text)
        assert json.loads(result)["text"] == 'He said "hello"'

    def test_single_smart_quotes_replaced(self):
        # ' (U+2019) should become escaped single quote
        result = sanitise_icelandic_quotes("it\u2019s")
        assert "\\'" in result


class TestExtractJson:
    def test_extracts_from_markdown_code_block(self):
        text = 'Some text\n```json\n{"key": "value"}\n```\nMore text'
        result = extract_json(text)
        assert json.loads(result) == {"key": "value"}

    def test_raw_json_string(self):
        text = '{"key": "value"}'
        result = extract_json(text)
        assert json.loads(result) == {"key": "value"}

    def test_icelandic_quotes_in_code_block(self):
        # „ open + " close inside a JSON value within a code block
        text = '```json\n{"title": "\u201eGreiðsluþreyta\u201c"}\n```'
        result = extract_json(text)
        parsed = json.loads(result)
        assert "Greiðsluþreyta" in parsed["title"]

    def test_valid_json_not_sanitised(self):
        """Valid JSON should not be modified by sanitisation."""
        text = '{"emoji": "\\u2764"}'
        result = extract_json(text)
        assert json.loads(result) == {"emoji": "\u2764"}

    def test_code_block_without_json_label(self):
        text = 'Text\n```\n{"a": 1}\n```'
        result = extract_json(text)
        assert json.loads(result) == {"a": 1}

    def test_icelandic_mixed_open_ascii_close(self):
        # „ (U+201E) open + plain ASCII " close — most common real-world pattern
        # The value is wrapped in proper JSON quotes, with Icelandic pair inside
        text = '{"title": "\u201eGreiðsluþreyta" er rétt"}'
        result = extract_json(text)
        parsed = json.loads(result)
        assert "Greiðsluþreyta" in parsed["title"]
