"""Typed configuration with YAML loaders."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml


@dataclass(frozen=True, slots=True)
class FingerprintConfig:
    kind: Literal["morgan", "rdkit"] = "morgan"
    radius: int = 2
    n_bits: int = 2048

    @property
    def fpsim2_type(self) -> str:
        return "Morgan" if self.kind == "morgan" else "RDKit"

    @property
    def fpsim2_params(self) -> dict[str, int]:
        return (
            {"radius": self.radius, "fpSize": self.n_bits}
            if self.kind == "morgan"
            else {"fpSize": self.n_bits}
        )


@dataclass(frozen=True, slots=True)
class SearchConfig:
    threshold: float = 0.80
    fallback_thresholds: tuple[float, ...] = (0.75, 0.70)
    max_results: int | None = None
    all_above_minimum: bool = False
    n_workers: int = 1
    fingerprint: FingerprintConfig = field(default_factory=FingerprintConfig)
    disk_chunk_size: int = 100_000

    @property
    def minimum_threshold(self) -> float:
        return min((self.threshold, *self.fallback_thresholds))


def load_search_config(path: Path | None) -> SearchConfig:
    if path is None:
        return SearchConfig()
    raw = yaml.safe_load(path.read_text()) or {}
    fp = FingerprintConfig(**raw.pop("fingerprint", {}))
    if "fallback_thresholds" in raw:
        raw["fallback_thresholds"] = tuple(raw["fallback_thresholds"])
    return SearchConfig(fingerprint=fp, **raw)
