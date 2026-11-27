"""Side-by-side fingerprint searches and union-based score comparison."""

import csv
from dataclasses import replace
from pathlib import Path

from .chemistry import tanimoto
from .config import FingerprintConfig, SearchConfig
from .export import export_log, export_query_summary, export_results
from .input import read_queries
from .models import SearchMatch
from .service import CommercialAnalogSearch


def compare_fingerprints(
    input_path: Path,
    providers: list[str],
    index_root: Path,
    output: Path,
    config: SearchConfig,
    local_cache_root: Path | None = None,
) -> dict[str, int]:
    """Search both indexes and rescore the union with both representations."""
    queries, input_errors = read_queries(input_path)
    if input_errors:
        raise ValueError("Invalid input rows: " + "; ".join(input_errors))
    fingerprints = {
        "morgan": FingerprintConfig(kind="morgan", radius=2, n_bits=2048),
        "rdkit": FingerprintConfig(kind="rdkit", min_path=1, max_path=7, n_bits=2048),
    }
    results: dict[str, list[SearchMatch]] = {}
    output.mkdir(parents=True, exist_ok=True)
    for name, fingerprint in fingerprints.items():
        fp_config = replace(config, fingerprint=fingerprint)
        service = CommercialAnalogSearch(index_root, fp_config, local_cache_root)
        matches, logs = service.search(queries, providers)
        results[name] = matches
        destination = output / name
        export_results(queries, matches, destination)
        export_log(logs, destination)
        export_query_summary(queries, matches, logs, fp_config, destination)

    query_by_id = {query.molecule_id: query for query in queries}
    union: dict[tuple[str, str, str], SearchMatch] = {}
    for matches in results.values():
        for match in matches:
            union.setdefault((match.original_id, match.provider, match.commercial_id), match)

    scored: dict[str, list[dict]] = {query.molecule_id: [] for query in queries}
    for (query_id, provider, catalog_id), match in union.items():
        query = query_by_id[query_id]
        scored[query_id].append(
            {
                "query_molecule_id": query_id,
                "query_smiles": query.smiles,
                "catalog_id": catalog_id,
                "analogue_smiles": match.analog_smiles,
                "provider": provider,
                "product_url": match.product_url,
                "morgan_tanimoto": tanimoto(
                    query.smiles, match.analog_smiles, fingerprints["morgan"]
                ),
                "rdkit_path_tanimoto": tanimoto(
                    query.smiles, match.analog_smiles, fingerprints["rdkit"]
                ),
            }
        )

    fields = [
        "query_molecule_id",
        "query_smiles",
        "catalog_id",
        "analogue_smiles",
        "morgan_tanimoto",
        "rdkit_path_tanimoto",
        "morgan_rank",
        "rdkit_path_rank",
        "morgan_max_similarity",
        "rdkit_path_max_similarity",
        "provider",
        "product_url",
    ]
    with (output / "fingerprint_comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for query in queries:
            rows = scored[query.molecule_id]
            morgan_order = sorted(rows, key=lambda row: row["morgan_tanimoto"], reverse=True)
            rdkit_order = sorted(rows, key=lambda row: row["rdkit_path_tanimoto"], reverse=True)
            morgan_ranks = {id(row): rank for rank, row in enumerate(morgan_order, 1)}
            rdkit_ranks = {id(row): rank for rank, row in enumerate(rdkit_order, 1)}
            morgan_max = morgan_order[0]["morgan_tanimoto"] if rows else ""
            rdkit_max = rdkit_order[0]["rdkit_path_tanimoto"] if rows else ""
            for row in morgan_order:
                row.update(
                    {
                        "morgan_rank": morgan_ranks[id(row)],
                        "rdkit_path_rank": rdkit_ranks[id(row)],
                        "morgan_max_similarity": morgan_max,
                        "rdkit_path_max_similarity": rdkit_max,
                    }
                )
                writer.writerow(row)

    unique: dict[str, str] = {}
    for match in union.values():
        unique.setdefault(match.canonical_smiles, f"CAS-{len(unique) + 1:07d}")
    with (output / "pipeline_input.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["SMILES", "molecule_id"])
        writer.writeheader()
        for smiles, molecule_id in unique.items():
            writer.writerow({"SMILES": smiles, "molecule_id": molecule_id})
    return {
        "queries": len(queries),
        "union_candidates": len(union),
        "unique_structures": len(unique),
    }
