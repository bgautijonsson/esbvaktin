"""latency-06: prepare_site builds entity scorecards and the evidence cited-by index
from the report dicts already in memory, instead of re-globbing _data/reports from disk
twice more. These tests pin that the in-memory path is byte-identical to the disk path
(including citation ordering) and that it is actually used.

prepare_site.py is a script, loaded via importlib (its top level is import-safe).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "prepare_site.py"


def _load():
    spec = importlib.util.spec_from_file_location("_prepare_site_single_pass", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _report(slug, citations):
    """Build a minimal report dict. citations: list of (evidence_id, role)."""
    supporting = [{"id": eid} for eid, role in citations if role == "supporting"]
    contradicting = [{"id": eid} for eid, role in citations if role == "contradicting"]
    return {
        "slug": slug,
        "article_title": f"Grein {slug}",
        "article_source": "mbl",
        "article_date": "2026-05-01",
        "claims": [
            {
                "claim": {"claim_text": f"Statement {slug}", "category": "trade"},
                "verdict": "supported",
                "supporting_evidence": supporting,
                "contradicting_evidence": contradicting,
            }
        ],
    }


def test_cited_by_index_memory_matches_disk_including_order(tmp_path):
    ps = _load()
    # Slugs chosen so filename order ("foo-2.json" < "foo.json") differs from naive
    # slug order ("foo" < "foo-2") — the ordering trap the in-memory path must honour.
    reports = [
        _report("foo", [("TRADE-DATA-001", "supporting")]),
        _report("foo-2", [("TRADE-DATA-001", "contradicting")]),
    ]
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    for r in reports:
        (reports_dir / f"{r['slug']}.json").write_text(
            json.dumps(r, ensure_ascii=False), encoding="utf-8"
        )

    disk = ps._build_cited_by_index(reports_dir)
    # Pass in a deliberately unsorted order to prove the function re-sorts internally.
    memory = ps._build_cited_by_index(reports=list(reversed(reports)))

    assert memory == disk
    # Citation order matches the on-disk glob (by filename), not naive slug order.
    assert [c["report_slug"] for c in memory["TRADE-DATA-001"]] == ["foo-2", "foo"]


def test_prepare_entity_details_uses_in_memory_reports(tmp_path):
    ps = _load()
    site_dir = tmp_path / "site"
    (site_dir / "_data").mkdir(parents=True)
    # reports_dir is intentionally empty: if the function re-globbed disk instead of
    # using the passed reports, the scorecard would come out empty.
    (site_dir / "_data" / "reports").mkdir()
    entities = [
        {
            "slug": "jon-jonsson",
            "name": "Jon Jonsson",
            "type": "individual",
            "articles": ["grein-1"],
        }
    ]
    (site_dir / "_data" / "entities.json").write_text(
        json.dumps(entities, ensure_ascii=False), encoding="utf-8"
    )

    reports = [
        {
            "slug": "grein-1",
            "article_title": "Grein 1",
            "article_source": "mbl",
            "article_date": "2026-05-01",
            "claims": [
                {
                    "claim": {"claim_text": "X", "category": "trade"},
                    "verdict": "supported",
                    "supporting_evidence": [],
                    "contradicting_evidence": [],
                    "speakers": [{"name": "Jon Jonsson", "attribution": "asserted"}],
                }
            ],
        }
    ]

    ps.prepare_entity_details(site_dir, reports=reports)

    detail = json.loads(
        (site_dir / "_data" / "entity-details" / "jon-jonsson.json").read_text(encoding="utf-8")
    )
    assert detail["scorecard"] == {"supported": 1}
