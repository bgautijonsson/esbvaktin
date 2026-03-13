"""Shared test configuration and markers."""

import pytest


def _has_embeddings() -> bool:
    try:
        import FlagEmbedding  # noqa: F401

        return True
    except ImportError:
        return False


requires_embeddings = pytest.mark.skipif(
    not _has_embeddings(),
    reason="FlagEmbedding not installed — install with: uv sync --extra embeddings",
)
