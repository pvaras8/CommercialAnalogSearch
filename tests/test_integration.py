from pathlib import Path

import numpy as np
import pytest
from rdkit import Chem

from commercial_analog_search.chemistry import tanimoto
from commercial_analog_search.config import FingerprintConfig, SearchConfig
from commercial_analog_search.index import build_index
from commercial_analog_search.models import QueryMolecule
from commercial_analog_search.search import search_provider


def _catalog(path: Path):
    writer = Chem.SDWriter(str(path))
    for name, smiles in [("ENA-1", "CCO"), ("ENA-2", "CCCO"), ("ENA-3", "c1ccccc1")]:
        mol = Chem.MolFromSmiles(smiles)
        mol.SetProp("Catalog_ID", name)
        mol.SetProp("Collection", "Test")
        writer.write(mol)
    writer.close()


def test_fpsim2_matches_direct_rdkit(tmp_path: Path):
    source = tmp_path / "Enamine_screening_collection_202610.sdf"
    _catalog(source)
    root = tmp_path / "indices"
    fp = FingerprintConfig()
    meta = build_index("enamine", source, root, fp)
    assert meta["record_count"] == 3
    matches = search_provider(
        QueryMolecule("q1", "CCO"),
        "enamine",
        root,
        SearchConfig(threshold=0.0, fallback_thresholds=(), fingerprint=fp),
    )
    assert matches[0].commercial_id == "ENA-1"
    for match in matches:
        assert match.similarity == pytest.approx(tanimoto("CCO", match.analog_smiles, fp), abs=1e-6)


def test_threshold_fallback_uses_first_successful_level(tmp_path: Path, monkeypatch):
    source = tmp_path / "Enamine_screening_collection_202610.sdf"
    _catalog(source)
    root = tmp_path / "indices"
    fp = FingerprintConfig()
    build_index("enamine", source, root, fp)
    attempted: list[float] = []

    class FakeEngine:
        fp_type = fp.fpsim2_type
        fp_params = fp.fpsim2_params

        def on_disk_similarity(self, query, threshold, **kwargs):
            attempted.append(threshold)
            dtype = [("mol_id", "<u8"), ("coeff", "<f4")]
            return np.array([] if threshold > 0.75 else [(1, 0.77)], dtype=dtype)

    monkeypatch.setattr("commercial_analog_search.search._disk_engine", lambda path: FakeEngine())
    matches = search_provider(
        QueryMolecule("q1", "CCO"),
        "enamine",
        root,
        SearchConfig(threshold=0.80, fallback_thresholds=(0.75, 0.70), fingerprint=fp),
    )
    assert attempted == [0.80, 0.75]
    assert matches[0].threshold == 0.75


def test_index_does_not_silently_reuse_sample_as_full(tmp_path: Path):
    source = tmp_path / "Enamine_screening_collection_202610.sdf"
    _catalog(source)
    root = tmp_path / "indices"
    fp = FingerprintConfig()
    build_index("enamine", source, root, fp, limit=2)
    with pytest.raises(ValueError, match="another catalogue/configuration"):
        build_index("enamine", source, root, fp, limit=None)
