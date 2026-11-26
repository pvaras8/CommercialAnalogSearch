"""Command-line interface."""

import json
import logging
from pathlib import Path
from typing import Annotated

import typer

from .config import FingerprintConfig, SearchConfig
from .index import build_index
from .service import CommercialAnalogSearch

app = typer.Typer(
    no_args_is_help=True, help="Search commercial molecular catalogues for analogues."
)


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command()
def index(
    provider: Annotated[str, typer.Option()] = "enamine",
    input: Annotated[Path, typer.Option(exists=True)] = Path("data/raw/enamine"),
    index_root: Annotated[Path, typer.Option()] = Path("indices"),
    limit: Annotated[
        int | None, typer.Option(help="Limit records; use 10000 for validation.")
    ] = None,
    fingerprint: Annotated[str, typer.Option()] = "morgan",
    radius: Annotated[int, typer.Option()] = 2,
    bits: Annotated[int, typer.Option()] = 2048,
    force: Annotated[bool, typer.Option()] = False,
    verbose: Annotated[bool, typer.Option()] = False,
) -> None:
    """Build an index once, or reuse an existing compatible index."""
    setup_logging(verbose)
    fp = FingerprintConfig(kind=fingerprint, radius=radius, n_bits=bits)  # type: ignore[arg-type]
    typer.echo(json.dumps(build_index(provider, input, index_root, fp, limit, force), indent=2))


@app.command()
def search(
    input: Annotated[Path, typer.Option(exists=True)],
    providers: Annotated[str, typer.Option()] = "enamine",
    threshold: Annotated[float, typer.Option()] = 0.80,
    min_threshold: Annotated[float, typer.Option()] = 0.70,
    max_results: Annotated[
        int | None, typer.Option(min=1, help="Maximum analogues per query; unlimited by default.")
    ] = None,
    output: Annotated[Path, typer.Option()] = Path("outputs"),
    index_root: Annotated[Path, typer.Option()] = Path("indices"),
    all_above_minimum: Annotated[bool, typer.Option()] = False,
    workers: Annotated[
        int,
        typer.Option("--cpus", "--workers", min=1, max=60, help="CPU processes for FPSim2 search."),
    ] = 1,
    chunk_size: Annotated[
        int,
        typer.Option(min=10_000, help="Fingerprints read per worker/chunk; lower uses less RAM."),
    ] = 100_000,
    fingerprint: Annotated[str, typer.Option()] = "morgan",
    radius: Annotated[int, typer.Option()] = 2,
    bits: Annotated[int, typer.Option()] = 2048,
    verbose: Annotated[bool, typer.Option()] = False,
) -> None:
    """Search CSV/Excel molecules, applying 0.80 -> 0.75 -> 0.70 fallback."""
    setup_logging(verbose)
    fallback = tuple(level for level in (0.75, min_threshold) if level < threshold)
    fp = FingerprintConfig(kind=fingerprint, radius=radius, n_bits=bits)  # type: ignore[arg-type]
    config = SearchConfig(
        threshold=threshold,
        fallback_thresholds=fallback,
        max_results=max_results,
        all_above_minimum=all_above_minimum,
        n_workers=workers,
        fingerprint=fp,
        disk_chunk_size=chunk_size,
    )
    stats = CommercialAnalogSearch(index_root, config).search_file(
        input, [p.strip() for p in providers.split(",")], output
    )
    typer.echo(json.dumps(stats, indent=2))


if __name__ == "__main__":
    app()
