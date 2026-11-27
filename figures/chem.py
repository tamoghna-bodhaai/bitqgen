"""Deterministic chemistry figures with RDKit: a structure, a reaction scheme, or option structures."""
from __future__ import annotations

from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem, Draw
from rdkit.Chem.Draw import rdMolDraw2D


# Drawn at a fixed bond length so every structure (and all four options) share one scale,
# rendered at 3x for crisp print, then cropped to the ink.
SCALE = 3
BOND_PX = 32 * SCALE          # bond length in the PNG
BOND_PCT = 5.5                # printed bond length as % of the column (~4.8 mm on A4 two-column)


def _opts(d):
    o = d.drawOptions()
    o.fixedBondLength = BOND_PX
    o.bondLineWidth = 2 * SCALE
    o.scaleBondWidth = False
    # labels ~body-text size in print (font px relative to bond length)
    o.fixedFontSize = 26 * SCALE
    o.minFontSize = 22 * SCALE
    o.maxFontSize = 30 * SCALE
    o.addStereoAnnotation = False
    o.padding = 0.02
    o.clearBackground = True
    o.useBWAtomPalette()


def _crop(png: bytes, out: Path) -> None:
    """Trim the white margin (keep a small border) so the printed width matches the molecule."""
    import io
    from PIL import Image, ImageChops
    im = Image.open(io.BytesIO(png)).convert("RGB")
    bbox = ImageChops.difference(im, Image.new("RGB", im.size, "white")).getbbox()
    if bbox:
        pad = 6 * SCALE
        im = im.crop((max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                      min(im.width, bbox[2] + pad), min(im.height, bbox[3] + pad)))
    im.save(out, dpi=(300, 300))


def valid_smiles(smi: str) -> bool:
    smi = (smi or "").strip()
    if not smi:
        return False
    if ">" in smi:
        try:
            return AllChem.ReactionFromSmarts(smi, useSmiles=True) is not None
        except Exception:
            return False
    return Chem.MolFromSmiles(smi) is not None


def draw_smiles(smi: str, out: Path, size: tuple[int, int] | None = None) -> Path:
    """Render a molecule or a reaction ('A.B>>C' or 'A>reagent>C') to a cropped PNG."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    smi = smi.strip()
    if ">" in smi:
        rxn = AllChem.ReactionFromSmarts(smi, useSmiles=True)
        if rxn is None:
            raise ValueError(f"bad reaction SMILES: {smi}")
        heavy = sum(m.GetNumAtoms() for m in list(rxn.GetReactants()) + list(rxn.GetProducts()))
        n = rxn.GetNumReactantTemplates() + rxn.GetNumProductTemplates()
        w, h = size or (min(4200, (BOND_PX * 3 + 220) * n + 300 + heavy * 30), BOND_PX * 7)
        d = rdMolDraw2D.MolDraw2DCairo(w, h)
        _opts(d)
        d.DrawReaction(rxn)
    else:
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            raise ValueError(f"bad SMILES: {smi}")
        AllChem.Compute2DCoords(mol)
        # canvas big enough that the fixed bond length is never shrunk to fit
        xs = [mol.GetConformer().GetAtomPosition(i) for i in range(mol.GetNumAtoms())]
        span_x = (max(p.x for p in xs) - min(p.x for p in xs)) if xs else 1
        span_y = (max(p.y for p in xs) - min(p.y for p in xs)) if xs else 1
        # RDKit 2D coords use bond length 1.5
        w, h = size or (int((span_x / 1.5 + 5) * BOND_PX), int((span_y / 1.5 + 5) * BOND_PX))
        d = rdMolDraw2D.MolDraw2DCairo(w, h)
        _opts(d)
        rdMolDraw2D.PrepareAndDrawMolecule(d, mol)
    d.FinishDrawing()
    _crop(d.GetDrawingText(), out)
    return out


def natural_width(path: Path, cap: int = 95) -> int:
    """Printed width (% of column) that keeps the fixed bond length, from the cropped PNG."""
    from PIL import Image
    w = Image.open(path).width
    return max(8, min(cap, round(w / BOND_PX * BOND_PCT)))


def width_for(smi: str, in_option: bool = False) -> int:
    """Suggested width as % of the paper column."""
    if in_option:
        return 22
    if ">" in smi:
        return 95
    mol = Chem.MolFromSmiles(smi)
    heavy = mol.GetNumHeavyAtoms() if mol else 10
    return 32 if heavy < 10 else 45 if heavy < 22 else 60
