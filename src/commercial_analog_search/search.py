"""Threshold fallback similarity search over persistent FPSim2 indexes."""

import json
import sqlite3
from functools import lru_cache
from pathlib import Path

from FPSim2 import FPSim2Engine

from .chemistry import standardize_smiles
from .config import FingerprintConfig, SearchConfig
from .index import index_paths, stage_index_for_search
from .models import QueryMolecule, SearchMatch


@lru_cache(maxsize=16)
def _disk_engine(path: str) -> FPSim2Engine:
    """Reuse file metadata and handles across queries in the same process."""
    return FPSim2Engine(path, in_memory_fps=False)


@lru_cache(maxsize=16)
def _staged_index(
    persistent_root: str,
    local_root: str,
    provider: str,
    fingerprint: FingerprintConfig,
) -> tuple[Path, Path, Path]:
    return stage_index_for_search(Path(persistent_root), Path(local_root), provider, fingerprint)


def search_provider(
    query: QueryMolecule,
    provider: str,
    root: Path,
    config: SearchConfig,
    local_cache_root: Path | None = None,
) -> list[SearchMatch]:
    if local_cache_root is None:
        fp_path, db_path, meta_path = index_paths(root, provider, config.fingerprint)
    else:
        fp_path, db_path, meta_path = _staged_index(
            str(root.resolve()),
            str(local_cache_root.resolve()),
            provider,
            config.fingerprint,
        )
    if not all(p.exists() for p in (fp_path, db_path, meta_path)):
        raise FileNotFoundError(f"Index missing for {provider}; run the index command")
    metadata = json.loads(meta_path.read_text())
    expected = metadata["fingerprint"]
    actual = config.fingerprint.as_dict()
    if expected != actual:
        raise ValueError(f"Fingerprint configuration differs from index: {expected} != {actual}")
    canonical = standardize_smiles(query.smiles)
    engine = _disk_engine(str(fp_path.resolve()))
    if (
        engine.fp_type != config.fingerprint.fpsim2_type
        or engine.fp_params != config.fingerprint.fpsim2_params
    ):
        raise ValueError("FPSim2 index parameters do not exactly match the query fingerprint")
    if config.mode == "topk":
        used = 0.0
        hits = engine.on_disk_top_k(
            canonical,
            k=config.top_k,
            threshold=0.0,
            metric="tanimoto",
            n_workers=config.n_workers,
            chunk_size=config.disk_chunk_size,
        )
    else:
        thresholds = (
            [config.threshold]
            if config.mode == "fixed"
            else [config.minimum_threshold]
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
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
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
            fingerprint=config.fingerprint.slug,
        )
        for i, score in ordered
    ]
