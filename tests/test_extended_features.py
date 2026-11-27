import csv
from pathlib import Path

import pytest
from rdkit import Chem

from commercial_analog_search.chemistry import tanimoto
from commercial_analog_search.compare import compare_fingerprints
from commercial_analog_search.config import FingerprintConfig, SearchConfig
from commercial_analog_search.export import export_results
from commercial_analog_search.index import build_index, index_paths, stage_index_for_search
from commercial_analog_search.models import QueryMolecule, SearchMatch
from commercial_analog_search.search import search_provider

CATALOG = [
    ("ENA-1", "CCO"),
    ("ENA-2", "CCCO"),
    ("ENA-3", "CCCCO"),
    ("ENA-4", "c1ccccc1"),
    ("ENA-5", "N"),
]


def make_catalog(path: Path) -> None:
    writer = Chem.SDWriter(str(path))
    for catalog_id, smiles in CATALOG:
        mol = Chem.MolFromSmiles(smiles)
        mol.SetProp("Catalog_ID", catalog_id)
        mol.SetProp("link", f"https://example.test/{catalog_id}")
        writer.write(mol)
    writer.close()


def build_pair(tmp_path: Path) -> tuple[Path, Path, FingerprintConfig, FingerprintConfig]:
    source = tmp_path / "Enamine_screening_collection_202610.sdf"
    make_catalog(source)
    root = tmp_path / "indices"
    morgan = FingerprintConfig(kind="morgan", radius=2, n_bits=2048)
    rdkit = FingerprintConfig(kind="rdkit", min_path=1, max_path=7, n_bits=2048)
    build_index("enamine", source, root, morgan)
    build_index("enamine", source, root, rdkit)
    return source, root, morgan, rdkit


def test_exact_top_k_matches_direct_rdkit(tmp_path: Path):
    _, root, morgan, _ = build_pair(tmp_path)
    query = QueryMolecule("q", "CCO")
    config = SearchConfig(mode="topk", top_k=3, fingerprint=morgan)
    matches = search_provider(query, "enamine", root, config)
    expected = sorted(
        ((catalog_id, tanimoto(query.smiles, smiles, morgan)) for catalog_id, smiles in CATALOG),
        key=lambda item: item[1],
        reverse=True,
    )[:3]
    assert [match.commercial_id for match in matches] == [item[0] for item in expected]
    assert [match.similarity for match in matches] == pytest.approx([item[1] for item in expected])


def test_fingerprint_indexes_are_independent_and_legacy_morgan_is_reused(tmp_path: Path):
    _, root, morgan, rdkit = build_pair(tmp_path)
    morgan_paths = index_paths(root, "enamine", morgan)
    rdkit_paths = index_paths(root, "enamine", rdkit)
    assert morgan_paths[0] == root / "enamine" / "fingerprints.h5"
    assert rdkit_paths[0].parent.name == "rdkit-min1-max7-n2048"
    assert morgan_paths[0] != rdkit_paths[0]
    query = QueryMolecule("q", "CCCCO")
    morgan_matches = search_provider(
        query, "enamine", root, SearchConfig(mode="fixed", threshold=0.0, fingerprint=morgan)
    )
    rdkit_matches = search_provider(
        query, "enamine", root, SearchConfig(mode="fixed", threshold=0.0, fingerprint=rdkit)
    )
    assert morgan_matches[0].similarity == pytest.approx(1.0)
    assert rdkit_matches[0].similarity == pytest.approx(1.0)
    for match in morgan_matches:
        assert match.similarity == pytest.approx(
            tanimoto(query.smiles, match.analog_smiles, morgan)
        )
    for match in rdkit_matches:
        assert match.similarity == pytest.approx(tanimoto(query.smiles, match.analog_smiles, rdkit))


def test_sequential_and_multicore_searches_are_equivalent(tmp_path: Path):
    _, root, morgan, _ = build_pair(tmp_path)
    query = QueryMolecule("q", "CCO")
    sequential = search_provider(
        query, "enamine", root, SearchConfig(mode="topk", top_k=5, n_workers=1, fingerprint=morgan)
    )
    parallel = search_provider(
        query, "enamine", root, SearchConfig(mode="topk", top_k=5, n_workers=2, fingerprint=morgan)
    )
    assert [(item.commercial_id, item.similarity) for item in sequential] == [
        (item.commercial_id, item.similarity) for item in parallel
    ]


def test_scratch_build_and_local_search_cache_are_reused(tmp_path: Path):
    source = tmp_path / "Enamine_screening_collection_202610.sdf"
    make_catalog(source)
    persistent = tmp_path / "lustre"
    scratch = tmp_path / "local-build"
    cache = tmp_path / "local-search"
    fp = FingerprintConfig()
    build_index("enamine", source, persistent, fp, scratch_root=scratch)
    local = stage_index_for_search(persistent, cache, "enamine", fp)
    mtimes = [path.stat().st_mtime_ns for path in local]
    assert stage_index_for_search(persistent, cache, "enamine", fp) == local
    assert [path.stat().st_mtime_ns for path in local] == mtimes


def test_fingerprint_comparison_rescores_union(tmp_path: Path):
    _, root, _, _ = build_pair(tmp_path)
    input_path = tmp_path / "queries.csv"
    input_path.write_text("molecule_id,SMILES\nq1,CCO\n")
    output = tmp_path / "comparison"
    stats = compare_fingerprints(
        input_path,
        ["enamine"],
        root,
        output,
        SearchConfig(mode="topk", top_k=2),
    )
    assert stats["union_candidates"] >= 2
    with (output / "fingerprint_comparison.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert all(row["morgan_tanimoto"] and row["rdkit_path_tanimoto"] for row in rows)
    assert (output / "morgan" / "query_summary.csv").exists()
    assert (output / "rdkit" / "query_summary.csv").exists()


def test_pipeline_deduplicates_same_structure_without_losing_mapping(tmp_path: Path):
    query = QueryMolecule("q", "CCO")
    matches = [
        SearchMatch("q", "CCO", "CCO", "CCO", "provider-a", "A-1", 1.0, 0.8, "v1"),
        SearchMatch("q", "CCO", "CCO", "CCO", "provider-b", "B-1", 1.0, 0.8, "v1"),
    ]
    export_results([query], matches, tmp_path)
    with (tmp_path / "pipeline_input.csv").open() as handle:
        assert len(list(csv.DictReader(handle))) == 1
    with (tmp_path / "commercial_mapping.csv").open() as handle:
        assert len(list(csv.DictReader(handle))) == 2
