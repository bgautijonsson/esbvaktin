"""Initialise the Ground Truth Database schema.

Usage:
    uv run python scripts/init_db.py
"""

from dotenv import load_dotenv

load_dotenv()

from esbvaktin.ground_truth import get_connection, init_schema


def main() -> None:
    conn = get_connection()
    init_schema(conn)
    print("✓ Database schema initialised")

    # Verify
    count = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    print(f"  Evidence entries: {count}")
    conn.close()


if __name__ == "__main__":
    main()
