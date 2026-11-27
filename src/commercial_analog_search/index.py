"""Persistent FPSim2 index and provider metadata store."""

import json
import logging
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from FPSim2 import __version__ as fpsim2_version
from FPSim2.io import create_db_file
from rdkit import __version__ as rdkit_version

from .config import FingerprintConfig
from .providers.registry import get

LOG = logging.getLogger(__name__)


def index_paths(
    root: Path, provider: str, fingerprint: FingerprintConfig | None = None
) -> tuple[Path, Path, Path]:
    """Return paths while preserving the original default-Morgan layout."""
    legacy_morgan = fingerprint is None or (
        fingerprint.kind == "morgan" and fingerprint.radius == 2 and fingerprint.n_bits == 2048
    )
    if legacy_morgan:
        folder = root / provider
    else:
        folder = root / provider / "indexes" / fingerprint.slug
    return folder / "fingerprints.h5", folder / "catalog.sqlite", folder / "metadata.json"


def _compatible(
    metadata: dict,
    catalog_version: str,
    fingerprint: FingerprintConfig,
    limit: int | None,
) -> bool:
    return (
        metadata.get("catalog_version") == catalog_version
        and metadata.get("fingerprint") == fingerprint.as_dict()
        and metadata.get("record_limit") == limit
    )


def validate_index(
    paths: tuple[Path, Path, Path], fingerprint: FingerprintConfig | None = None
) -> dict:
    """Validate HDF5 readability, SQLite row count and metadata consistency."""
    from FPSim2 import FPSim2Engine

    fp_path, db_path, meta_path = paths
    if not all(path.is_file() and path.stat().st_size > 0 for path in paths):
        raise ValueError(f"Incomplete index at {fp_path.parent}")
    metadata = json.loads(meta_path.read_text())
    if fingerprint is not None and metadata.get("fingerprint") != fingerprint.as_dict():
        raise ValueError("Fingerprint metadata does not match the requested representation")
    engine = FPSim2Engine(str(fp_path), in_memory_fps=False)
    if fingerprint is not None and (
        engine.fp_type != fingerprint.fpsim2_type or engine.fp_params != fingerprint.fpsim2_params
    ):
        raise ValueError("FPSim2 embedded fingerprint parameters do not match metadata")
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        count = int(connection.execute("SELECT COUNT(*) FROM compounds").fetchone()[0])
    finally:
        connection.close()
    if count != metadata.get("record_count"):
        raise ValueError(
            f"SQLite count {count} differs from metadata {metadata.get('record_count')}"
        )
    return metadata


def _copy_index(source: tuple[Path, Path, Path], destination: tuple[Path, Path, Path]) -> None:
    """Copy without rsync and publish metadata last."""
    destination[0].parent.mkdir(parents=True, exist_ok=True)
    staged = tuple(path.with_name(f".{path.name}.copying") for path in destination)
    for source_path, staged_path in zip(source, staged, strict=True):
        shutil.copy2(source_path, staged_path)
    for staged_path, destination_path in zip(staged, destination, strict=True):
        staged_path.replace(destination_path)


def stage_index_for_search(
    persistent_root: Path,
    local_root: Path,
    provider: str,
    fingerprint: FingerprintConfig,
) -> tuple[Path, Path, Path]:
    """Reuse or refresh a validated node-local read cache."""
    persistent = index_paths(persistent_root, provider, fingerprint)
    persistent_meta = validate_index(persistent, fingerprint)
    local = index_paths(local_root, provider, fingerprint)
    if all(path.exists() for path in local):
        try:
            local_meta = validate_index(local, fingerprint)
            keys = ("catalog_version", "record_count", "indexed_at", "fingerprint")
            if all(local_meta.get(key) == persistent_meta.get(key) for key in keys):
                LOG.info("Reusing compatible local index cache %s", local[0].parent)
                return local
        except (ValueError, OSError, json.JSONDecodeError):
            pass
    LOG.info("Copying index to node-local cache %s", local[0].parent)
    _copy_index(persistent, local)
    validate_index(local, fingerprint)
    return local


def build_index(
    provider_name: str,
    source: Path,
    root: Path,
    fingerprint: FingerprintConfig,
    limit: int | None = None,
    force: bool = False,
    scratch_root: Path | None = None,
) -> dict:
    provider = get(provider_name)
    fp_path, db_path, meta_path = index_paths(root, provider_name, fingerprint)
    fp_path.parent.mkdir(parents=True, exist_ok=True)
    source_path = provider.discover(source)
    catalog_version = provider.version(source_path) if hasattr(provider, "version") else "unknown"
    requested_fp = fingerprint.as_dict()
    if not force and fp_path.exists() and db_path.exists() and meta_path.exists():
        existing = json.loads(meta_path.read_text())
        if _compatible(existing, catalog_version, fingerprint, limit):
            LOG.info("Reusing existing compatible index %s", fp_path)
            return existing
        raise ValueError(
            "Existing index belongs to another catalogue/configuration; use --force or a new --index-root"
        )
    if scratch_root is not None:
        try:
            metadata = build_index(
                provider_name, source, scratch_root, fingerprint, limit, force, scratch_root=None
            )
        except ValueError:
            LOG.info("Replacing stale node-local build cache")
            metadata = build_index(
                provider_name, source, scratch_root, fingerprint, limit, True, scratch_root=None
            )
        local_paths = index_paths(scratch_root, provider_name, fingerprint)
        validate_index(local_paths, fingerprint)
        _copy_index(local_paths, (fp_path, db_path, meta_path))
        validate_index((fp_path, db_path, meta_path), fingerprint)
        return metadata
    build_fp = fp_path.with_suffix(".building.h5")
    build_db = db_path.with_suffix(".building.sqlite")
    build_meta = meta_path.with_suffix(".building.json")
    for path in (build_fp, build_db, build_meta):
        if path.exists():
            path.unlink()
    connection = sqlite3.connect(build_db)
    connection.execute(
        "CREATE TABLE compounds (internal_id INTEGER PRIMARY KEY, provider_id TEXT NOT NULL, smiles TEXT NOT NULL, catalog_version TEXT NOT NULL, properties_json TEXT NOT NULL)"
    )
    connection.execute("CREATE INDEX compounds_smiles_idx ON compounds(smiles)")
    count = 0

    def molecules():
        nonlocal count
        for count, record in enumerate(provider.records(source, limit), 1):
            connection.execute(
                "INSERT INTO compounds VALUES (?, ?, ?, ?, ?)",
                (
                    count,
                    record.provider_id,
                    record.smiles,
                    record.catalog_version,
                    json.dumps(record.properties),
                ),
            )
            if count % 10000 == 0:
                connection.commit()
                LOG.info("Indexed source records: %d", count)
            yield record.smiles, count

    try:
        create_db_file(
            molecules(),
            str(build_fp),
            "smiles",
            fingerprint.fpsim2_type,
            dict(fingerprint.fpsim2_params),
        )
        connection.commit()
    finally:
        connection.close()
    metadata = {
        "index_schema_version": 2,
        "provider": provider_name,
        "catalog_version": catalog_version,
        "record_count": count,
        "record_limit": limit,
        "fingerprint": requested_fp,
        "fpsim2_version": fpsim2_version,
        "rdkit_version": rdkit_version,
        "indexed_at": datetime.now(UTC).isoformat(),
        "source": str(source_path),
    }
    build_meta.write_text(json.dumps(metadata, indent=2) + "\n")
    build_fp.replace(fp_path)
    build_db.replace(db_path)
    build_meta.replace(meta_path)
    return metadata
