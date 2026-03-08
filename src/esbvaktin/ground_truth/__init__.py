"""Ground Truth Database — curated evidence for article analysis."""

from .models import Confidence, Domain, EvidenceEntry, SearchResult, SourceType
from .operations import (
    embed_text,
    embed_texts,
    get_connection,
    get_topic_counts,
    get_total_count,
    init_schema,
    insert_evidence,
    insert_evidence_batch,
    search_evidence,
)

__all__ = [
    "Confidence",
    "Domain",
    "EvidenceEntry",
    "SearchResult",
    "SourceType",
    "embed_text",
    "embed_texts",
    "get_connection",
    "get_topic_counts",
    "get_total_count",
    "init_schema",
    "insert_evidence",
    "insert_evidence_batch",
    "search_evidence",
]
