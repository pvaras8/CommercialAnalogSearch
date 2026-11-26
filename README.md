# CommercialAnalogSearch

Independent Python library and CLI for finding structurally similar compounds in local commercial catalogues. It streams provider catalogues, creates persistent FPSim2 indexes, searches by Tanimoto similarity, de-duplicates structures without losing query/supplier relationships, and exports files for downstream molecular evaluation.

The current provider is Enamine. The provider interface and registry allow WuXi, Chemspace, Mcule, ChemBridge, or official APIs to be added without changing the search engine.

## Installation

Python 3.11–3.14 is supported and tested in the Linux CI matrix. Python 3.12 is recommended on the HPC. RDKit and FPSim2 publish Linux wheels for 3.11, 3.12 and 3.14; the local validated environment uses Python 3.14, RDKit 2026.09.2 and FPSim2 0.7.4. Linux requires glibc 2.28 or newer for current RDKit wheels.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Validate on 10,000 Enamine compounds

The ZIP is read as a stream; it is not fully extracted or loaded into RAM.

```bash
commercial-search index --provider enamine --input data/raw/enamine/ --limit 10000
```

Indexes are stored under `indices/<provider>/`: compressed FPSim2 fingerprints, a SQLite identifier/SMILES/property sidecar, and JSON metadata. An existing index is reused. Use `--force` only to rebuild it.

Input may be CSV, TSV, or Excel and must contain `SMILES` and `molecule_id` (case-insensitive). For Excel, `Kept` is selected when present, otherwise the first sheet.

```bash
commercial-search search \
  --input molecules.csv \
  --providers enamine \
  --threshold 0.80 \
  --min-threshold 0.70 \
  --output outputs/
```

The default fallback is 0.80, then 0.75, then 0.70 when no hit is found. `--all-above-minimum` performs one search at the minimum threshold. There is no result limit unless `--max-results` is supplied. `--cpus` (alias `--workers`) configures 1–60 FPSim2 CPU processes and `--chunk-size` bounds per-process I/O memory. Fingerprints default to Morgan radius 2 / 2048 bits; use `--fingerprint rdkit` for RDKit path fingerprints. Search settings must match the index settings.

With multiple providers (`--providers enamine,other-provider`), every provider is searched at the same threshold. The threshold is reduced only when none of the selected providers returns a hit.

## Full index

After validating the sample, build the complete catalogue (remove `--limit`). `--force` is required when replacing the sample index:

```bash
commercial-search index --provider enamine --input data/raw/enamine/ --force
```

Allow enough disk space for streaming decompression plus the fingerprint/metadata index. The code never keeps the complete catalogue in memory.

Index construction is streaming but FPSim2 fingerprint generation and final HDF5 sorting are sequential. `--cpus` applies to searching, not indexing. This is the principal full-build bottleneck and is reported explicitly rather than presenting ineffective index parallelism.

## Outputs

- `commercial_matches.csv`: every query-to-commercial-entry hit and similarity.
- `pipeline_input.csv`: unique structures with generated internal `CAS-…` IDs.
- `commercial_mapping.csv`: unique candidate to original query and supplier ID relations.
- `search_log.csv`: elapsed time, counts, and per-query errors.
- `commercial_candidates.sdf`: unique selected candidates.

`historical_catalog_listing` means only that the entry occurs in the supplied catalogue. It is not real-time commercial availability. A future provider API must explicitly verify stock before this status changes.

`commercial_matches.csv` also contains one `no_analogue_found` row for every unmatched query. Hits are ordered by similarity and include `similarity_rank`, `max_similarity`, `is_best_match`, product URL, catalogue version, and all extra input columns under the `query_property__` prefix. Thus arbitrary prediction CSVs do not require preprocessing.

## Python API

```python
from commercial_analog_search import CommercialAnalogSearch, SearchConfig

service = CommercialAnalogSearch("indices", SearchConfig(max_results=20, n_workers=4))
stats = service.search_file("molecules.xlsx", ["enamine"], "outputs")
```

From another repository, install this package into that project's environment without copying source code:

```bash
python -m pip install -e /shared/software/CommercialAnalogSearch
```

## Adding a provider

Implement `CatalogProvider.discover()` and streaming `CatalogProvider.records()`, then call `providers.register(instance)`. Keep source parsing and live availability checks in the provider; return normalized `CatalogRecord` values to the shared indexing layer. Add its declarative YAML under `config/providers/` and provider-specific tests.

## Development

```bash
pytest
ruff check .
```

The integration test builds a tiny FPSim2 index and verifies every returned score against direct RDKit Tanimoto calculation. See [catalogue inspection](docs/catalog_inspection.md) for the observed Enamine schema.

For Linux HPC installation, Slurm examples, resource estimates, catalogue updates, and exact production commands, see [HPC deployment](docs/hpc.md).
