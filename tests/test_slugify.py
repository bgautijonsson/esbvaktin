"""Tests for the shared icelandic_slugify utility."""

from esbvaktin.utils.slugify import icelandic_slugify


def test_basic_icelandic_name():
    assert icelandic_slugify("Björn Leví Gunnarsson") == "bjorn-levi-gunnarsson"


def test_thorn_and_eth():
    assert icelandic_slugify("Þorgerður Katrín") == "thorgerdur-katrin"


def test_ae_and_o_umlaut():
    assert icelandic_slugify("Bændasamtök Íslands") == "baendasamtok-islands"


def test_accented_vowels():
    assert icelandic_slugify("Ísland á Evrópuvegi") == "island-a-evropuvegi"


def test_strips_special_chars():
    assert icelandic_slugify("Viðskipti & verslun (2026)") == "vidskipti-verslun-2026"


def test_collapses_multiple_hyphens():
    assert icelandic_slugify("Sjávarútvegur -- Íslands") == "sjavarutvegur-islands"


def test_strips_leading_trailing_hyphens():
    assert icelandic_slugify("  Ísland  ") == "island"


def test_empty_string():
    assert icelandic_slugify("") == ""


def test_ascii_passthrough():
    assert icelandic_slugify("hello world") == "hello-world"
