"""Core database operations for the Ground Truth Database.

Uses psycopg v3 + pgvector for PostgreSQL with vector similarity search.
"""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector

from .models import EvidenceEntry, SearchResult

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection(autocommit: bool = False) -> psycopg.Connection:
    load_dotenv()
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=autocommit)
    try:
        register_vector(conn)
    except psycopg.ProgrammingError:
        # vector extension not yet created — init_schema will handle it
        pass
    return conn


def init_schema(conn: psycopg.Connection | None = None) -> None:
    """Create the evidence table and indices."""
    close = False
    if conn is None:
        conn = get_connection()
        close = True

    # Need autocommit for CREATE EXTENSION
    old_autocommit = conn.autocommit
    conn.autocommit = True
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.autocommit = old_autocommit

    # Register vector type now that the extension exists
    register_vector(conn)

    sql = SCHEMA_PATH.read_text()
    # Remove the CREATE EXTENSION line since we already did it
    lines = [l for l in sql.split("\n") if "CREATE EXTENSION" not in l]
    conn.execute("\n".join(lines))
    conn.commit()
    if close:
        conn.close()


_embedding_model = None


def _get_embedding_model():
    """Lazy-load BGE-M3 model (cached after first call)."""
    global _embedding_model
    if _embedding_model is None:
        from FlagEmbedding import BGEM3FlagModel

        _embedding_model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
    return _embedding_model


def embed_text(text: str) -> list[float]:
    """Generate 1024-dim embedding using BAAI/bge-m3 (local, multilingual)."""
    model = _get_embedding_model()
    result = model.encode([text])
    return result["dense_vecs"][0].tolist()


def embed_texts(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Batch-embed multiple texts."""
    model = _get_embedding_model()
    result = model.encode(texts, batch_size=batch_size)
    return [v.tolist() for v in result["dense_vecs"]]


def insert_evidence(entry: EvidenceEntry, conn: psycopg.Connection | None = None) -> None:
    """Insert a single evidence entry with auto-generated embedding."""
    embed_input = entry.statement
    if entry.caveats:
        embed_input += f" ({entry.caveats})"
    embedding = embed_text(embed_input)

    close = False
    if conn is None:
        conn = get_connection()
        close = True

    conn.execute(
        """
        INSERT INTO evidence (
            evidence_id, domain, topic, subtopic, statement,
            source_name, source_url, source_date, source_type,
            confidence, caveats, related_entries, last_verified, embedding
        ) VALUES (
            %(evidence_id)s, %(domain)s, %(topic)s, %(subtopic)s, %(statement)s,
            %(source_name)s, %(source_url)s, %(source_date)s, %(source_type)s,
            %(confidence)s, %(caveats)s, %(related_entries)s, %(last_verified)s,
            %(embedding)s
        ) ON CONFLICT (evidence_id) DO UPDATE SET
            statement = EXCLUDED.statement,
            source_name = EXCLUDED.source_name,
            source_url = EXCLUDED.source_url,
            source_date = EXCLUDED.source_date,
            caveats = EXCLUDED.caveats,
            last_verified = EXCLUDED.last_verified,
            embedding = EXCLUDED.embedding,
            updated_at = NOW()
        """,
        {
            "evidence_id": entry.evidence_id,
            "domain": entry.domain.value,
            "topic": entry.topic,
            "subtopic": entry.subtopic,
            "statement": entry.statement,
            "source_name": entry.source_name,
            "source_url": entry.source_url,
            "source_date": entry.source_date,
            "source_type": entry.source_type.value,
            "confidence": entry.confidence.value,
            "caveats": entry.caveats,
            "related_entries": entry.related_entries,
            "last_verified": entry.last_verified,
            "embedding": embedding,
        },
    )
    conn.commit()

    if close:
        conn.close()


def insert_evidence_batch(
    entries: list[EvidenceEntry], conn: psycopg.Connection | None = None
) -> int:
    """Insert multiple evidence entries. Returns count of entries inserted."""
    close = False
    if conn is None:
        conn = get_connection()
        close = True

    count = 0
    for entry in entries:
        insert_evidence(entry, conn=conn)
        count += 1

    if close:
        conn.close()
    return count


def search_evidence(
    query: str,
    topic_filter: str | None = None,
    domain_filter: str | None = None,
    top_k: int = 10,
    conn: psycopg.Connection | None = None,
) -> list[SearchResult]:
    """Semantic search: embed the query, find closest evidence entries."""
    query_embedding = embed_text(query)

    close = False
    if conn is None:
        conn = get_connection()
        close = True

    conditions = []
    params: dict = {
        "embedding": query_embedding,
        "top_k": top_k,
    }

    if topic_filter:
        conditions.append("topic = %(topic)s")
        params["topic"] = topic_filter
    if domain_filter:
        conditions.append("domain = %(domain)s")
        params["domain"] = domain_filter

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = conn.execute(
        f"""
        SELECT evidence_id, domain, topic, subtopic, statement,
               source_name, source_url, source_date, source_type,
               confidence, caveats,
               1 - (embedding <=> %(embedding)s::vector) AS similarity,
               statement_is
        FROM evidence
        {where_clause}
        ORDER BY embedding <=> %(embedding)s::vector
        LIMIT %(top_k)s
        """,
        params,
    ).fetchall()

    columns = [
        "evidence_id", "domain", "topic", "subtopic", "statement",
        "source_name", "source_url", "source_date", "source_type",
        "confidence", "caveats", "similarity", "statement_is",
    ]
    results = [SearchResult(**dict(zip(columns, row))) for row in rows]

    if close:
        conn.close()
    return results


def get_topic_counts(conn: psycopg.Connection | None = None) -> dict[str, int]:
    """Get evidence entry counts by topic."""
    close = False
    if conn is None:
        conn = get_connection()
        close = True

    rows = conn.execute(
        "SELECT topic, COUNT(*) FROM evidence GROUP BY topic ORDER BY COUNT(*) DESC"
    ).fetchall()

    if close:
        conn.close()
    return dict(rows)


def get_total_count(conn: psycopg.Connection | None = None) -> int:
    """Get total number of evidence entries."""
    close = False
    if conn is None:
        conn = get_connection()
        close = True

    count = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]

    if close:
        conn.close()
    return count
