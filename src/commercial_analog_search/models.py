"""Domain models."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CatalogRecord:
    smiles: str
    provider_id: str
    provider: str
    catalog_version: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QueryMolecule:
    molecule_id: str
    smiles: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SearchMatch:
    original_id: str
    original_smiles: str
    analog_smiles: str
    canonical_smiles: str
    provider: str
    commercial_id: str
    similarity: float
    threshold: float
    catalog_version: str
    availability_status: str = "historical_catalog_listing"
    product_url: str = ""
    fingerprint: str = "morgan-r2-n2048"
