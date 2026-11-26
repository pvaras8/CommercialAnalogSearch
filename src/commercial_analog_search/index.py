"""Persistent FPSim2 index and provider metadata store."""

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from FPSim2.io import create_db_file

from .config import FingerprintConfig
from .providers.registry import get

LOG = logging.getLogger(__name__)


def index_paths(root: Path, provider: str) -> tuple[Path, Path, Path]:
    folder = root / provider
    return folder / "fingerprints.h5", folder / "catalog.sqlite", folder / "metadata.json"


def build_index(
    provider_name: str,
    source: Path,
    root: Path,
    fingerprint: FingerprintConfig,
    limit: int | None = None,
    force: bool = False,
) -> dict:
    provider = get(provider_name)
    fp_path, db_path, meta_path = index_paths(root, provider_name)
    fp_path.parent.mkdir(parents=True, exist_ok=True)
    source_path = provider.discover(source)
    catalog_version = provider.version(source_path) if hasattr(provider, "version") else "unknown"
    requested_fp = {
        "kind": fingerprint.kind,
        "radius": fingerprint.radius,
        "n_bits": fingerprint.n_bits,
    }
    if not force and fp_path.exists() and db_path.exists() and meta_path.exists():
        existing = json.loads(meta_path.read_text())
        compatible = (
            existing.get("catalog_version") == catalog_version
            and existing.get("fingerprint") == requested_fp
            and existing.get("record_limit") == limit
        )
        if compatible:
            LOG.info("Reusing existing compatible index %s", fp_path)
            return existing
        raise ValueError(
            "Existing index belongs to another catalogue/configuration; use --force or a new --index-root"
        )
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
        "provider": provider_name,
        "catalog_version": catalog_version,
        "record_count": count,
        "record_limit": limit,
        "fingerprint": requested_fp,
        "indexed_at": datetime.now(UTC).isoformat(),
        "source": str(source_path),
    }
    build_meta.write_text(json.dumps(metadata, indent=2) + "\n")
    build_fp.replace(fp_path)
    build_db.replace(db_path)
    build_meta.replace(meta_path)
    return metadata
