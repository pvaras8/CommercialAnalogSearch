from pathlib import Path

import pandas as pd
import pytest

from commercial_analog_search.chemistry import standardize_smiles, tanimoto
from commercial_analog_search.config import FingerprintConfig
from commercial_analog_search.input import read_queries


def test_standardization_and_tanimoto():
    config = FingerprintConfig()
    assert standardize_smiles("C(C)O") == "CCO"
    assert tanimoto("CCO", "C(C)O", config) == pytest.approx(1.0)
    assert tanimoto("CCO", "c1ccccc1", config) < 1.0


def test_excel_prefers_kept(tmp_path: Path):
    path = tmp_path / "queries.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"SMILES": ["N"], "molecule_id": ["wrong"]}).to_excel(
            writer, sheet_name="Other", index=False
        )
        pd.DataFrame({"SMILES": ["CCO"], "molecule_id": ["kept"]}).to_excel(
            writer, sheet_name="Kept", index=False
        )
    queries, errors = read_queries(path)
    assert not errors and queries[0].molecule_id == "kept"
