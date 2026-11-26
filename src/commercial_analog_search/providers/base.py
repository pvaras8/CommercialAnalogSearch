"""Provider interface."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

from ..models import CatalogRecord


class CatalogProvider(ABC):
    name: str

    @abstractmethod
    def discover(self, source: Path) -> Path: ...
    @abstractmethod
    def records(self, source: Path, limit: int | None = None) -> Iterator[CatalogRecord]: ...
