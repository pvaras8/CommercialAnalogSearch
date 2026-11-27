# Linux HPC deployment

## Compatibility

The project supports CPython 3.11, 3.12 and 3.14 on Linux x86-64 and tests those versions in `.github/workflows/test.yml`. Python 3.12 is the conservative HPC recommendation. Current RDKit wheels require glibc 2.28 or newer; check with `ldd --version`. FPSim2 0.7.x, RDKit, pandas, PyYAML, openpyxl and Typer all provide compatible wheels or pure-Python packages for these versions.

No CUDA dependency is installed. The search path deliberately uses FPSim2's CPU/on-disk implementation. GPUs are not requested because this workload is well served by CPU POPCNT and the requested deployment prioritises CPU.

The deployed environment is Mirmidon (Rocky Linux 9.5, glibc 2.34, 64 physical CPUs, about 188 GB RAM and four NVIDIA GPUs) with the Mamba environment `commercial_search`. Rocky's glibc satisfies the wheel requirement.

The existing Enamine 202610 Morgan index contains 4,824,873 molecules and was built with Python 3.12, RDKit 2026.9.2 and FPSim2 0.7.4 in 82 minutes 16 seconds. In the initial 84-query PockLigGPT run, no Morgan hit reached 0.70; observed maximum similarities were 0.5000 (6PCF), 0.6207 (4AH6) and 0.6508 (8PPR). Fixed-threshold and exact top-k modes are provided to explore this lower-similarity regime explicitly rather than silently changing scientific interpretation.

The dependency matrix is:

| Dependency | Python 3.11 | Python 3.12 | Python 3.14 | Linux notes |
|---|---:|---:|---:|---|
| FPSim2 0.7.x | yes | yes | yes | manylinux x86-64 wheels |
| RDKit 2025.3+ | yes | yes | yes | glibc 2.28+ wheels |
| pandas 2.2–3.x | yes | yes | yes | manylinux wheels |
| PyYAML / openpyxl / Typer | yes | yes | yes | wheels or pure Python |

## Installation

Activate the existing Mamba environment from the cloned repository:

```bash
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate commercial_search
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
pytest
commercial-search --help
```

All operational paths are relative by default and configurable with `--input`, `--index-root`, and `--output`. No path in the package depends on macOS or a user home directory.

## Resource planning for Enamine 4.8 million

The 10,000-record measurement produced a 2.12 MB HDF5 index and 3.49 MB SQLite sidecar. Linear extrapolation gives approximately 1.02 GB HDF5 plus 1.68 GB SQLite for 4.8 million records. The supplied ZIP is 1.36 GB. HDF5 sorting temporarily keeps an unsorted and sorted fingerprint file, so allow at least 6 GB; 10–15 GB of working space is recommended for filesystem/block-size variation, logs, and future catalogue growth.

Index RAM is bounded by streaming SDF parsing and FPSim2's 32,000-record write batch. Provision 4 GB minimum and 8 GB conservatively. Index construction is mostly sequential: ZIP/SDF parsing, RDKit standardisation, FPSim2 fingerprint construction and final PyTables sorting do not expose a useful worker count in FPSim2 0.7.4. More CPUs will not materially accelerate this step.

Search uses FPSim2 on-disk methods, which use a process pool when `--cpus` is greater than one. With `--chunk-size 100000`, raw fingerprint blocks are roughly 27 MB per active process; process/RDKit/PyTables overhead and concurrent I/O make 16 GB RAM a safe starting request for 64 CPUs. If the job approaches its memory limit, reduce `--chunk-size` to 50000 or reduce `--cpus`. Performance can become storage-I/O-bound before reaching 64 CPUs, so benchmark 16, 32 and 64 on the cluster filesystem.

## Validate and build

Place the provider archive under a project or shared-data path; it is ignored by Git.

```bash
source .venv/bin/activate

commercial-search index \
  --provider enamine \
  --input data/raw/enamine/ \
  --index-root indices/validation \
  --limit 10000
```

The existing full Morgan production index must not be rebuilt. For a future catalogue, publish to a new versioned root:

```bash
commercial-search index \
  --provider enamine \
  --input data/raw/enamine/202701/ \
  --index-root indices/enamine-202701 \
  --scratch-root "/tmp/${USER}/commercial-search-build"
```

Example Slurm script for the eventual full build:

```bash
#!/usr/bin/env bash
#SBATCH --job-name=cas-index-enamine
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=24:00:00
#SBATCH --output=logs/index-enamine-%j.out

set -euo pipefail
source .venv/bin/activate
commercial-search index --provider enamine --input data/raw/enamine/202701/ --index-root indices/enamine-202701 --scratch-root "/tmp/${USER}/commercial-search-build"
```

## Existing production index and node-local storage

The completed Morgan index contains 4,824,873 molecules from catalogue 202610 and remains in the original layout. Do not move or rebuild it. Passing `--fingerprint morgan --radius 2 --bits 2048` resolves that legacy layout directly.

SQLite locking on LUSTRE/NFS is not disabled. Instead, `--scratch-root` builds and validates all three index files on local XFS before copying them with Python's standard library (no `rsync`). `--local-cache` validates and copies a persistent index to local storage for searching, or reuses it when catalogue version, row count, timestamp and fingerprint metadata match.

Use a job-specific or user-specific local directory with adequate space:

```bash
export COMMERCIAL_SEARCH_SCRATCH="/tmp/${USER}/commercial-search-build"
export COMMERCIAL_SEARCH_LOCAL_CACHE="/tmp/${USER}/commercial-search-cache"
mkdir -p "$COMMERCIAL_SEARCH_SCRATCH" "$COMMERCIAL_SEARCH_LOCAL_CACHE"
```

## Exact production commands

### 1. Reuse the existing Morgan index

```bash
conda activate commercial_search

commercial-search search \
  --input 6PCF_PockLigGPT_predictions_DeNovo_filtradas.csv \
  --providers enamine \
  --threshold 0.80 \
  --min-threshold 0.70 \
  --fingerprint morgan \
  --radius 2 \
  --bits 2048 \
  --cpus 64 \
  --chunk-size 100000 \
  --index-root indices/production \
  --local-cache "$COMMERCIAL_SEARCH_LOCAL_CACHE" \
  --output outputs/6pcf-commercial-analogues/
```

### 2. Build an independent RDKit Path index

This command leaves `indices/production/enamine/fingerprints.h5` untouched and publishes the new index below `indices/production/enamine/indexes/rdkit-min1-max7-n2048/`:

```bash
commercial-search index \
  --provider enamine \
  --input data/raw/enamine/ \
  --index-root indices/production \
  --fingerprint rdkit \
  --min-path 1 \
  --max-path 7 \
  --bits 2048 \
  --scratch-root "$COMMERCIAL_SEARCH_SCRATCH"
```

### 3. Retrieve the exact top 20

```bash
commercial-search search \
  --input molecules.csv \
  --providers enamine \
  --mode topk \
  --top-k 20 \
  --fingerprint morgan \
  --cpus 64 \
  --index-root indices/production \
  --local-cache "$COMMERCIAL_SEARCH_LOCAL_CACHE" \
  --output outputs/top20-morgan/
```

### 4. Search at a fixed threshold

```bash
commercial-search search \
  --input molecules.csv \
  --providers enamine \
  --mode fixed \
  --threshold 0.50 \
  --fingerprint rdkit \
  --min-path 1 \
  --max-path 7 \
  --cpus 64 \
  --index-root indices/production \
  --local-cache "$COMMERCIAL_SEARCH_LOCAL_CACHE" \
  --output outputs/rdkit-fixed-050/
```

### 5. Compare Morgan and RDKit Path

```bash
commercial-search compare \
  --input molecules.csv \
  --providers enamine \
  --mode topk \
  --top-k 20 \
  --cpus 64 \
  --index-root indices/production \
  --local-cache "$COMMERCIAL_SEARCH_LOCAL_CACHE" \
  --output outputs/fingerprint-comparison/
```

The comparison directory contains individual Morgan and RDKit result trees, union-based `fingerprint_comparison.csv`, and a unique commercial `pipeline_input.csv`.

Omit `--max-results` to return every hit at the first successful threshold. Add, for example, `--max-results 100` to cap the combined result set across all selected providers for each query.

Example Slurm search request:

```bash
#!/usr/bin/env bash
#SBATCH --job-name=cas-search
#SBATCH --cpus-per-task=64
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --output=logs/search-%j.out

set -euo pipefail
conda activate commercial_search
commercial-search search --input molecules.csv --providers enamine --mode topk --top-k 20 --cpus "${SLURM_CPUS_PER_TASK}" --index-root indices/production --local-cache "/tmp/${USER}/commercial-search-cache" --output outputs/run-001/
```

## Updating a provider catalogue

Never overwrite the production catalogue or index in place. Store the new archive in a versioned directory, build into a new index root, validate it, and then point searches at that root:

```bash
commercial-search index \
  --provider enamine \
  --input data/raw/enamine/202701/ \
  --index-root indices/enamine-202701-validation \
  --limit 10000 \
  --scratch-root "$COMMERCIAL_SEARCH_SCRATCH"

commercial-search index \
  --provider enamine \
  --input data/raw/enamine/202701/ \
  --index-root indices/enamine-202701 \
  --scratch-root "$COMMERCIAL_SEARCH_SCRATCH"

commercial-search search \
  --input validation_queries.csv \
  --providers enamine \
  --index-root indices/enamine-202701 \
  --output outputs/catalog-validation-202701/
```

The index builder records catalogue version, record limit, fingerprint parameters, source and timestamp. It refuses to silently reuse an incompatible index. Builds use temporary `.building` files and replace the active files only after successful completion. Retain the previous version until scientific validation is complete.

## Git safety

`.gitignore` excludes raw/sample/provider catalogues, ZIP/SDF/SMI files, HDF5 indexes, SQLite-containing index directories, outputs, virtual/Conda environments, credentials, caches and Slurm output. Before committing, verify with:

```bash
git status --short --ignored
git check-ignore -v data/raw/enamine/catalog.zip indices/production/fingerprints.h5 outputs/run/commercial_matches.csv .venv/bin/python
```
