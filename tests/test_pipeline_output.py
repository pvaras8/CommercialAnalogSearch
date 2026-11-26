import csv
from pathlib import Path

import pandas as pd

from commercial_analog_search.config import SearchConfig
from commercial_analog_search.export import export_results
from commercial_analog_search.input import read_queries
from commercial_analog_search.models import QueryMolecule, SearchMatch
from commercial_analog_search.service import CommercialAnalogSearch


def test_arbitrary_pipeline_csv_preserves_properties(tmp_path: Path):
    source = tmp_path / "predictions.csv"
    pd.DataFrame(
        {
            "rank": [1, 2],
            "molecule_id": ["q1", "q2"],
            "SMILES": ["CCO", "N"],
            "6pcf_vina_score": [-8.2, -7.0],
            "S_Boltz": [0.91, 0.55],
        }
    ).to_csv(source, index=False)
    queries, errors = read_queries(source)
    assert not errors
    assert queries[0].properties["6pcf_vina_score"] == -8.2


def test_result_schema_ranking_best_match_and_no_hit(tmp_path: Path):
    queries = [
        QueryMolecule("q1", "CCO", {"rank": 4, "6pcf_vina_score": -8.2}),
        QueryMolecule("q2", "N", {"rank": 5, "6pcf_vina_score": -6.1}),
    ]
    matches = [
        SearchMatch(
            "q1",
            "CCO",
            "CCCO",
            "CCCO",
            "enamine",
            "Z2",
            0.8,
            0.8,
            "202610",
            product_url="https://example/Z2",
        ),
        SearchMatch(
            "q1",
            "CCO",
            "CCO",
            "CCO",
            "enamine",
            "Z1",
            1.0,
            0.8,
            "202610",
            product_url="https://example/Z1",
        ),
    ]
    stats = export_results(queries, matches, tmp_path)
    assert stats == {"matches": 2, "unique_candidates": 2}
    with (tmp_path / "commercial_matches.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["catalog_id"] == "Z1"
    assert rows[0]["similarity_rank"] == "1"
    assert rows[0]["max_similarity"] == "1.0"
    assert rows[0]["is_best_match"] == "True"
    assert rows[0]["query_rank"] == "4"
    assert rows[0]["query_property__6pcf_vina_score"] == "-8.2"
    assert rows[2]["query_molecule_id"] == "q2"
    assert rows[2]["search_status"] == "no_analogue_found"
    with (tmp_path / "pipeline_input.csv").open() as handle:
        pipeline = list(csv.DictReader(handle))
    assert {row["SMILES"] for row in pipeline} == {"CCO", "CCCO"}


def test_provider_search_uses_one_global_fallback_threshold(monkeypatch):
    attempted: list[tuple[str, float]] = []

    def fake_search(query, provider, root, config):
        attempted.append((provider, config.threshold))
        if provider == "provider-a" and config.threshold == 0.8:
            return [SearchMatch("q1", "CCO", "CCO", "CCO", provider, "A1", 1.0, 0.8, "v1")]
        return []

    monkeypatch.setattr("commercial_analog_search.service.search_provider", fake_search)
    service = CommercialAnalogSearch(config=SearchConfig())
    matches, _ = service.search([QueryMolecule("q1", "CCO")], ["provider-a", "provider-b"])
    assert len(matches) == 1
    assert attempted == [("provider-a", 0.8), ("provider-b", 0.8)]
