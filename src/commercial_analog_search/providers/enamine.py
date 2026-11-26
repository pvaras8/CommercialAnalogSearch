"""Streaming Enamine SDF/ZIP catalogue reader."""

import re
import zipfile
from collections.abc import Iterator
from pathlib import Path

from rdkit import Chem

from ..chemistry import standardize_smiles
from ..models import CatalogRecord
from .base import CatalogProvider


class EnamineProvider(CatalogProvider):
    name = "enamine"

    def discover(self, source: Path) -> Path:
        if source.is_file() and source.suffix.lower() in {".zip", ".sdf"}:
            return source
        files = sorted((*source.glob("*.zip"), *source.glob("*.sdf")))
        if not files:
            raise FileNotFoundError(f"No .zip or .sdf catalogue found in {source}")
        return files[-1]

    @staticmethod
    def version(path: Path) -> str:
        match = re.search(r"(20\d{4})", path.name)
        return match.group(1) if match else "unknown"

    def records(self, source: Path, limit: int | None = None) -> Iterator[CatalogRecord]:
        path = self.discover(source)
        version = self.version(path)
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                members = [n for n in archive.namelist() if n.lower().endswith(".sdf")]
                if len(members) != 1:
                    raise ValueError(f"Expected one SDF in {path}, found {len(members)}")
                with archive.open(members[0]) as stream:
                    yield from self._supplier_records(
                        Chem.ForwardSDMolSupplier(stream), version, limit
                    )
        else:
            yield from self._supplier_records(Chem.ForwardSDMolSupplier(str(path)), version, limit)

    def _supplier_records(self, supplier, version: str, limit: int | None):
        emitted = 0
        for mol in supplier:
            if mol is None:
                continue
            provider_id = (
                mol.GetProp("Catalog_ID").strip()
                if mol.HasProp("Catalog_ID")
                else mol.GetProp("_Name").strip()
                if mol.HasProp("_Name")
                else ""
            )
            if not provider_id:
                continue
            smiles = standardize_smiles(Chem.MolToSmiles(mol, isomericSmiles=True))
            props = {name: mol.GetProp(name) for name in mol.GetPropNames()}
            yield CatalogRecord(smiles, provider_id, self.name, version, props)
            emitted += 1
            if limit is not None and emitted >= limit:
                return
