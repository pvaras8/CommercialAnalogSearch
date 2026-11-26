"""CSV and Excel query ingestion."""

from pathlib import Path

import pandas as pd

from .models import QueryMolecule


def read_queries(
    path: Path, smiles_column: str = "SMILES", id_column: str = "molecule_id"
) -> tuple[list[QueryMolecule], list[str]]:
    errors: list[str] = []
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        book = pd.ExcelFile(path)
        sheet = "Kept" if "Kept" in book.sheet_names else book.sheet_names[0]
        frame = pd.read_excel(path, sheet_name=sheet)
    elif path.suffix.lower() in {".csv", ".tsv"}:
        frame = pd.read_csv(path, sep="\t" if path.suffix.lower() == ".tsv" else ",")
    else:
        raise ValueError("Input must be CSV, TSV or Excel")
    lowered = {str(c).lower(): str(c) for c in frame.columns}
    smi_col = lowered.get(smiles_column.lower()) or lowered.get("smiles")
    mol_col = lowered.get(id_column.lower()) or lowered.get("id")
    if not smi_col or not mol_col:
        raise ValueError(f"Required columns SMILES and molecule_id; found {list(frame.columns)}")
    queries = []
    for row_number, row in frame.iterrows():
        if pd.isna(row[smi_col]) or pd.isna(row[mol_col]):
            errors.append(f"row {row_number + 2}: missing value")
            continue
        properties = {
            str(column): (None if pd.isna(value) else value)
            for column, value in row.to_dict().items()
        }
        queries.append(QueryMolecule(str(row[mol_col]), str(row[smi_col]), properties))
    return queries, errors
