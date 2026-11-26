"""Threshold fallback similarity search over persistent FPSim2 indexes."""

import json
import sqlite3
from functools import lru_cache
from pathlib import Path

from FPSim2 import FPSim2Engine

from .chemistry import standardize_smiles
from .config import SearchConfig
from .index import index_paths
from .models import QueryMolecule, SearchMatch


@lru_cache(maxsize=16)
def _disk_engine(path: str) -> FPSim2Engine:
    """Reuse file metadata and handles across queries in the same process."""
    return FPSim2Engine(path, in_memory_fps=False)


def search_provider(
    query: QueryMolecule, provider: str, root: Path, config: SearchConfig
) -> list[SearchMatch]:
    fp_path, db_path, meta_path = index_paths(root, provider)
    if not all(p.exists() for p in (fp_path, db_path, meta_path)):
        raise FileNotFoundError(f"Index missing for {provider}; run the index command")
    metadata = json.loads(meta_path.read_text())
    expected = metadata["fingerprint"]
    actual = {
        "kind": config.fingerprint.kind,
        "radius": config.fingerprint.radius,
        "n_bits": config.fingerprint.n_bits,
    }
    if expected != actual:
        raise ValueError(f"Fingerprint configuration differs from index: {expected} != {actual}")
    canonical = standardize_smiles(query.smiles)
    engine = _disk_engine(str(fp_path.resolve()))
    thresholds = (
        [config.minimum_threshold]
        if config.all_above_minimum
        else [config.threshold, *config.fallback_thresholds]
    )
    hits = None
    used = thresholds[-1]
    for used in thresholds:
        hits = engine.on_disk_similarity(
            canonical,
            used,
            metric="tanimoto",
            n_workers=config.n_workers,
            chunk_size=config.disk_chunk_size,
        )
        if len(hits):
            break
    if hits is None or not len(hits):
        return []
    ordered = sorted(
        ((int(hit["mol_id"]), float(hit["coeff"])) for hit in hits),
        key=lambda x: x[1],
        reverse=True,
    )[: config.max_results]
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = {
            row["internal_id"]: row
            for row in connection.execute(
                f"SELECT * FROM compounds WHERE internal_id IN ({','.join('?' for _ in ordered)})",
                [i for i, _ in ordered],
            )
        }
    finally:
        connection.close()
    return [
        SearchMatch(
            query.molecule_id,
            query.smiles,
            rows[i]["smiles"],
            rows[i]["smiles"],
            provider,
            rows[i]["provider_id"],
            score,
            used,
            rows[i]["catalog_version"],
            product_url=json.loads(rows[i]["properties_json"]).get("link", ""),
        )
        for i, score in ordered
    ]
