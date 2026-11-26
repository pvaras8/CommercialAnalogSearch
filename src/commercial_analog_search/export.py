"""Result tables and SDF export with structural de-duplication."""

import csv
from pathlib import Path
from typing import Any

from rdkit import Chem

from .models import QueryMolecule, SearchMatch

RESULT_FIELDS = [
    "query_molecule_id",
    "query_smiles",
    "query_rank",
    "analogue_id",
    "analogue_smiles",
    "provider",
    "catalog_id",
    "similarity",
    "similarity_threshold",
    "similarity_rank",
    "max_similarity",
    "is_best_match",
    "catalog_version",
    "availability_status",
    "product_url",
    "search_status",
]


def _extra_fields(queries: list[QueryMolecule]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    fields: list[tuple[str, str]] = []
    for query in queries:
        for original in query.properties:
            if original.lower() in {"smiles", "molecule_id", "rank"}:
                continue
            output = f"query_property__{original}"
            if output not in seen:
                seen.add(output)
                fields.append((original, output))
    return fields


def _query_rank(query: QueryMolecule) -> Any:
    return next((value for name, value in query.properties.items() if name.lower() == "rank"), "")


def export_results(
    queries: list[QueryMolecule], matches: list[SearchMatch], output: Path
) -> dict[str, int]:
    output.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[SearchMatch]] = {query.molecule_id: [] for query in queries}
    unique: dict[str, str] = {}
    for match in matches:
        grouped.setdefault(match.original_id, []).append(match)
        unique.setdefault(match.canonical_smiles, f"CAS-{len(unique) + 1:07d}")
    extras = _extra_fields(queries)
    with (output / "commercial_matches.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*RESULT_FIELDS, *(name for _, name in extras)])
        writer.writeheader()
        for query in queries:
            ranked = sorted(
                grouped.get(query.molecule_id, []), key=lambda item: item.similarity, reverse=True
            )
            maximum = ranked[0].similarity if ranked else ""
            for similarity_rank, match in enumerate(ranked or [None], 1):
                row: dict[str, Any] = {
                    "query_molecule_id": query.molecule_id,
                    "query_smiles": query.smiles,
                    "query_rank": _query_rank(query),
                    "analogue_id": "" if match is None else unique[match.canonical_smiles],
                    "analogue_smiles": "" if match is None else match.analog_smiles,
                    "provider": "" if match is None else match.provider,
                    "catalog_id": "" if match is None else match.commercial_id,
                    "similarity": "" if match is None else match.similarity,
                    "similarity_threshold": "" if match is None else match.threshold,
                    "similarity_rank": "" if match is None else similarity_rank,
                    "max_similarity": maximum,
                    "is_best_match": match is not None and similarity_rank == 1,
                    "catalog_version": "" if match is None else match.catalog_version,
                    "availability_status": "" if match is None else match.availability_status,
                    "product_url": "" if match is None else match.product_url,
                    "search_status": "no_analogue_found" if match is None else "matched",
                }
                row.update(
                    {
                        output_name: query.properties.get(original, "")
                        for original, output_name in extras
                    }
                )
                writer.writerow(row)
    with (output / "pipeline_input.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["SMILES", "molecule_id"])
        writer.writeheader()
        for smiles, candidate_id in unique.items():
            writer.writerow({"SMILES": smiles, "molecule_id": candidate_id})
    mapping_fields = [
        "candidate_id",
        "canonical_smiles",
        "query_molecule_id",
        "provider",
        "catalog_id",
    ]
    seen = set()
    with (output / "commercial_mapping.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=mapping_fields)
        writer.writeheader()
        for match in matches:
            row = (
                unique[match.canonical_smiles],
                match.canonical_smiles,
                match.original_id,
                match.provider,
                match.commercial_id,
            )
            if row in seen:
                continue
            seen.add(row)
            writer.writerow(dict(zip(mapping_fields, row, strict=True)))
    writer = Chem.SDWriter(str(output / "commercial_candidates.sdf"))
    try:
        for smiles, candidate_id in unique.items():
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                continue
            mol.SetProp("_Name", candidate_id)
            mol.SetProp("SMILES", smiles)
            writer.write(mol)
    finally:
        writer.close()
    return {"matches": len(matches), "unique_candidates": len(unique)}


def export_log(rows: list[dict[str, Any]], output: Path) -> None:
    fields = ["molecule_id", "provider", "status", "matches", "elapsed_seconds", "error"]
    with (output / "search_log.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
