"""Sync seed files from DB after audit fixes.

Run with: uv run python scripts/sync_seeds_from_db.py
"""

import json
from pathlib import Path

# Mapping: evidence_id → seed file
SEED_MAP = {
    "CURR-DATA-003": "data/seeds/currency.json",
    "CURR-DATA-004": "data/seeds/currency.json",
    "CURRENCY-DATA-015": "data/seeds/data_backed_expanded.json",
    "POLL-DATA-014": "data/seeds/inbox_gaps_round1.json",
    "HOUSING-DATA-008": "data/seeds/gap_fill_housing.json",
    "AGRI-DATA-002": "data/seeds/agriculture_trade.json",
    "AGRI-DATA-021": "data/seeds/gap_fill_round5.json",
    "AGRI-DATA-018": "data/seeds/gap_fill_agriculture.json",
    "FISH-DATA-019": "data/seeds/data_backed.json",
    "FISH-DATA-020": "data/seeds/data_backed.json",
    "SOV-LEGAL-012": "data/seeds/sovereignty_expanded.json",
    "SOV-LEGAL-007": "data/seeds/political_party_actions.json",
    "EEA-DATA-011": "data/seeds/gap_fill_round5.json",
    "EEA-DATA-007": "data/seeds/data_backed_expanded.json",
    "POLITICAL-DATA-012": "data/seeds/gap_fill_political.json",
    "POL-DATA-011": "data/seeds/political_expanded.json",
    "POL-DATA-001": "data/seeds/political.json",
    "PREC-HIST-004": "data/seeds/precedents.json",
}

# Fields to sync from DB
SYNC_FIELDS = ["statement", "caveats", "statement_is", "caveats_is"]


def main():
    # Load DB data
    with open("/tmp/audit_fix_db_data.json") as f:
        db_data = json.load(f)

    # Group by seed file
    files: dict[str, list[str]] = {}
    for eid, fpath in SEED_MAP.items():
        files.setdefault(fpath, []).append(eid)

    for fpath, eids in sorted(files.items()):
        path = Path(fpath)
        if not path.exists():
            print(f"WARNING: {fpath} not found, skipping {eids}")
            continue

        with open(path) as f:
            seeds = json.load(f)

        updated = 0
        for entry in seeds:
            eid = entry.get("evidence_id")
            if eid in eids and eid in db_data:
                for field in SYNC_FIELDS:
                    if field in db_data[eid] and db_data[eid][field] is not None:
                        entry[field] = db_data[eid][field]
                # Reset proofreading hash if present
                if "is_proofread_hash" in entry:
                    entry["is_proofread_hash"] = None
                updated += 1

        if updated:
            with open(path, "w") as f:
                json.dump(seeds, f, ensure_ascii=False, indent=2)
                f.write("\n")
            print(f"Updated {updated} entries in {fpath}")
        else:
            print(f"No entries found to update in {fpath}")


if __name__ == "__main__":
    main()
