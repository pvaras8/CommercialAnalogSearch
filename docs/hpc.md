# Linux HPC deployment

## Compatibility

The project supports CPython 3.11, 3.12 and 3.14 on Linux x86-64 and tests those versions in `.github/workflows/test.yml`. Python 3.12 is the conservative HPC recommendation. Current RDKit wheels require glibc 2.28 or newer; check with `ldd --version`. FPSim2 0.7.x, RDKit, pandas, PyYAML, openpyxl and Typer all provide compatible wheels or pure-Python packages for these versions.

No CUDA dependency is installed. The search path deliberately uses FPSim2's CPU/on-disk implementation. GPUs are not requested because this workload is well served by CPU POPCNT and the requested deployment prioritises CPU.

The dependency matrix is:

| Dependency | Python 3.11 | Python 3.12 | Python 3.14 | Linux notes |
|---|---:|---:|---:|---|
| FPSim2 0.7.x | yes | yes | yes | manylinux x86-64 wheels |
| RDKit 2025.3+ | yes | yes | yes | glibc 2.28+ wheels |
| pandas 2.2–3.x | yes | yes | yes | manylinux wheels |
| PyYAML / openpyxl / Typer | yes | yes | yes | wheels or pure Python |

## Installation

Run from a login node in the cloned repository. Replace the module names with those used by the cluster:

```bash
module purge
module load Python/3.12

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
pytest
commercial-search --help
```

All operational paths are relative by default and configurable with `--input`, `--index-root`, and `--output`. No path in the package depends on macOS or a user home directory.

## Resource planning for Enamine 4.8 million

The 10,000-record measurement produced a 2.12 MB HDF5 index and 3.49 MB SQLite sidecar. Linear extrapolation gives approximately 1.02 GB HDF5 plus 1.68 GB SQLite for 4.8 million records. The supplied ZIP is 1.36 GB. HDF5 sorting temporarily keeps an unsorted and sorted fingerprint file, so allow at least 6 GB; 10–15 GB of working space is recommended for filesystem/block-size variation, logs, and future catalogue growth.

Index RAM is bounded by streaming SDF parsing and FPSim2's 32,000-record write batch. Provision 4 GB minimum and 8 GB conservatively. Index construction is mostly sequential: ZIP/SDF parsing, RDKit standardisation, FPSim2 fingerprint construction and final PyTables sorting do not expose a useful worker count in FPSim2 0.7.4. More CPUs will not materially accelerate this step.

Search uses FPSim2 `on_disk_similarity`, which uses a process pool when `--cpus` is greater than one. With `--chunk-size 100000`, raw fingerprint blocks are roughly 27 MB per active process; process/RDKit/PyTables overhead and concurrent I/O make 16 GB RAM a safe starting request for 60 CPUs. If the job approaches its memory limit, reduce `--chunk-size` to 50000 or reduce `--cpus`. Performance can become storage-I/O-bound before reaching 60 CPUs, so benchmark 16, 32 and 60 on the cluster filesystem.

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

Do not build the full index until validation is accepted. The eventual production command is:

```bash
commercial-search index \
  --provider enamine \
  --input data/raw/enamine/ \
  --index-root indices/production
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
commercial-search index --provider enamine --input data/raw/enamine/ --index-root indices/production
```

## Search with up to 60 CPUs

```bash
source .venv/bin/activate

commercial-search search \
  --input 6PCF_PockLigGPT_predictions_DeNovo_filtradas.csv \
  --providers enamine \
  --threshold 0.80 \
  --min-threshold 0.70 \
  --cpus 60 \
  --chunk-size 100000 \
  --index-root indices/production \
  --output outputs/6pcf-commercial-analogues/
```

Omit `--max-results` to return every hit at the first successful threshold. Add, for example, `--max-results 100` to cap the combined result set across all selected providers for each query.

Example Slurm search request:

```bash
#!/usr/bin/env bash
#SBATCH --job-name=cas-search
#SBATCH --cpus-per-task=60
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --output=logs/search-%j.out

set -euo pipefail
source .venv/bin/activate
commercial-search search --input molecules.csv --providers enamine --cpus "${SLURM_CPUS_PER_TASK}" --index-root indices/production --output outputs/run-001/
```

## Updating a provider catalogue

Never overwrite the production catalogue or index in place. Store the new archive in a versioned directory, build into a new index root, validate it, and then point searches at that root:

```bash
commercial-search index \
  --provider enamine \
  --input data/raw/enamine/202701/ \
  --index-root indices/enamine-202701 \
  --limit 10000

commercial-search index \
  --provider enamine \
  --input data/raw/enamine/202701/ \
  --index-root indices/enamine-202701 \
  --force

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
