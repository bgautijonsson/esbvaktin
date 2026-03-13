"""Initialise the Ground Truth Database schema.

Usage:
    uv run python scripts/init_db.py          # Create schema only
    uv run python scripts/init_db.py --seed    # Create schema + seed evidence
"""

import argparse
import subprocess
import sys

from dotenv import load_dotenv


def main() -> None:
    load_dotenv()

    from esbvaktin.ground_truth import get_connection, init_schema

    parser = argparse.ArgumentParser(description="Initialise ESBvaktin database")
    parser.add_argument(
        "--seed", action="store_true", help="Also seed evidence from data/seeds/"
    )
    args = parser.parse_args()

    print("Connecting to database...")
    conn = get_connection()

    print("Creating schema (tables, indices, triggers)...")
    init_schema(conn)
    print("Schema ready.")

    count = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    print(f"  Evidence entries: {count}")
    claims = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    print(f"  Claims: {claims}")
    conn.close()

    if args.seed:
        print("\nSeeding evidence from data/seeds/...")
        subprocess.run(
            [sys.executable, "scripts/seed_evidence.py", "insert", "data/seeds/"],
            check=True,
        )
        print("Seeding complete.")


if __name__ == "__main__":
    main()
