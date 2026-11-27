"""Molecular standardisation and fingerprint helpers."""

from rdkit import Chem, DataStructs
from rdkit.Chem import rdFingerprintGenerator

from .config import FingerprintConfig


def standardize_smiles(smiles: str) -> str:
    mol = Chem.MolFromSmiles(str(smiles).strip())
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")
    return Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)


def fingerprint(smiles: str, config: FingerprintConfig):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")
    gen = (
        rdFingerprintGenerator.GetMorganGenerator(radius=config.radius, fpSize=config.n_bits)
        if config.kind == "morgan"
        else rdFingerprintGenerator.GetRDKitFPGenerator(
            minPath=config.min_path, maxPath=config.max_path, fpSize=config.n_bits
        )
    )
    return gen.GetFingerprint(mol)


def tanimoto(left: str, right: str, config: FingerprintConfig) -> float:
    return float(
        DataStructs.TanimotoSimilarity(fingerprint(left, config), fingerprint(right, config))
    )
