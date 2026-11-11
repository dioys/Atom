"""make_character.py - cut an expression sheet into separate see-through pictures.

Atom's character is a folder of PNG pictures (one per expression) plus a
character.json that says which picture to show for which mood. This tool makes
those pictures from "expression sheet" images like the jester ones: a grid of
faces on a plain background.

Put the four sheet images here, named sheet1.jpg ... sheet4.jpg:

    assets\\sheets\\

then, with the (.venv) active, run:

    python scripts/make_character.py            # makes src\\characters\\jester\\*.png
    python scripts/make_character.py --preview  # also writes a contact sheet to check the cut-outs

To use your own sheets, edit GRID and FACES below (x/y of the grid cells, and
which cell is which expression). Nothing else in Atom needs to change.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent      # the repo folder
SHEETS_DIR = HERE / "assets" / "sheets"
OUT_DIR = HERE / "src" / "characters" / "jester"

# pixel boxes of the 3 columns and 2 rows of faces on each 1376x768 sheet
GRID = {
    "columns": [(85, 480), (486, 882), (884, 1282)],
    "rows": [(34, 374), (390, 734)],
}

BIG_PATCH = 1800  # pixels: bigger background-coloured areas inside a face are backdrop, not eyes

# expression name -> (sheet number, row 0-1, column 0-2)
FACES = {
    "talk_a": (2, 0, 0),      # open mouth, wide eyes
    "talk_b": (3, 0, 0),      # toothy grin
    "talk_c": (4, 0, 0),      # big open mouth
    "laughing": (1, 0, 0),
    "happy": (4, 0, 1),       # big smile, eyes closed
    "crying": (1, 0, 1),
    "annoyed": (1, 0, 2),
    "shocked": (1, 1, 0),
    "nervous": (1, 1, 1),
    "thinking": (1, 1, 2),    # hand on chin
    "stunned": (2, 0, 1),
    "furious": (2, 0, 2),
    "sad": (2, 1, 0),
    "surprised": (2, 1, 1),
    "smug": (2, 1, 2),
    "scared": (3, 0, 1),
    "angry": (3, 0, 2),
    "sleepy": (3, 1, 0),
    "curious": (3, 1, 1),
}

# which picture(s) Atom shows for each mood (see charpack.py for how they are used)
CHARACTER_JSON = {
    "name": "Jester",
    "height": 190,
    "talk": ["talk_a", "talk_b", "talk_c"],
    "rest": "smug",
    "face": [70, 70, 260, 260],     # the square of a picture used as his chat portrait (x, y, width, height)
    "states": {
        "idle": ["smug"],
        "talking": ["talk_a"],
        "thinking": ["thinking"],
        "listening": ["curious"],
        "happy": ["happy", "laughing"],
        "laughing": ["laughing"],
        "proud": ["smug", "happy"],
        "worried": ["nervous"],
        "sad": ["sad", "crying"],
        "surprised": ["surprised", "shocked"],
        "curious": ["curious"],
        "annoyed": ["annoyed"],
        "sleepy": ["sleepy"],
        "looking": ["smug"],
    },
    "icon": "happy",
}


def _background(rgb):
    """True for pixels that are the sheet's grey or cream backdrop."""
    import numpy as np

    r, g, b = (rgb[..., i].astype(int) for i in range(3))
    gray = (abs(r - g) < 9) & (abs(g - b) < 9) & (r > 165) & (r < 205)
    cream = (r > 232) & (g > 226) & (b > 190) & (r - b > 14) & (r - b < 70)
    return gray | cream


def cut_face(sheet, row: int, col: int):
    """One face from a sheet image, with the backdrop made see-through (RGBA)."""
    import numpy as np
    from PIL import Image
    from scipy import ndimage as ndi

    x0, x1 = GRID["columns"][col]
    y0, y1 = GRID["rows"][row]
    cell = np.array(sheet.convert("RGB").crop((x0, y0, x1, y1)))

    # backdrop = background-coloured pixels that connect to the edge of the cell.
    # Background-coloured spots INSIDE the face (cream eye whites) stay.
    bg = _background(cell)
    labels, count = ndi.label(bg)
    edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    edge = edge[edge > 0]
    backdrop = np.isin(labels, edge)
    # big enclosed patches (the sheet showing through under the hat) are backdrop too;
    # small ones (cream eye whites, teeth) belong to the face
    sizes = ndi.sum(bg, labels, range(1, count + 1))
    big = [i + 1 for i, size in enumerate(sizes) if size > BIG_PATCH]
    backdrop |= np.isin(labels, big)

    fg = ndi.binary_opening(~backdrop, iterations=1)
    labels, count = ndi.label(fg)
    if count == 0:
        raise ValueError("nothing found in this cell: check GRID")
    sizes = ndi.sum(fg, labels, range(1, count + 1))
    mask = labels == (1 + int(np.argmax(sizes)))  # the character, not stray text or a neighbour
    mask = ndi.binary_closing(mask, iterations=2)
    mask = ndi.binary_erosion(mask, iterations=1)  # trims the grey fringe around the outline
    alpha = ndi.gaussian_filter(mask.astype(float), 0.7)
    alpha = (np.clip(alpha * 1.15, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(np.dstack([cell, alpha]), "RGBA")


def find_sheet(number: int, folder: Path = SHEETS_DIR) -> Path | None:
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        path = folder / f"sheet{number}{ext}"
        if path.exists():
            return path
    return None


def build(sheets_dir: Path = SHEETS_DIR, out_dir: Path = OUT_DIR, preview: bool = False) -> list[str]:
    """Cut every face and write the pictures + character.json. Returns the names made."""
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    sheets: dict[int, Image.Image] = {}
    made: list[str] = []
    for name, (number, row, col) in FACES.items():
        if number not in sheets:
            path = find_sheet(number, sheets_dir)
            if path is None:
                raise FileNotFoundError(f"sheet{number}.jpg not found in {sheets_dir}")
            sheets[number] = Image.open(path)
        cut_face(sheets[number], row, col).save(out_dir / f"{name}.png")
        made.append(name)
    (out_dir / "character.json").write_text(json.dumps(CHARACTER_JSON, indent=2), encoding="utf-8")

    if preview:
        tiles = [Image.open(out_dir / f"{n}.png") for n in made]
        w, h = tiles[0].size
        w2, h2 = w // 2, h // 2
        per_row = 5
        board = Image.new("RGBA", (w2 * per_row, h2 * -(-len(tiles) // per_row)), (50, 80, 60, 255))
        for i, tile in enumerate(tiles):
            board.alpha_composite(tile.resize((w2, h2)), ((i % per_row) * w2, (i // per_row) * h2))
        board.convert("RGB").save(out_dir / "preview.png")
    return made


def main() -> int:
    parser = argparse.ArgumentParser(description="Cut expression sheets into Atom character pictures")
    parser.add_argument("--preview", action="store_true", help="also write preview.png to check the cut-outs")
    args = parser.parse_args()
    try:
        made = build(preview=args.preview)
    except FileNotFoundError as error:
        print(f"{error}\nSave your four sheet pictures as sheet1.jpg ... sheet4.jpg in:\n  {SHEETS_DIR}")
        return 1
    print(f"Made {len(made)} pictures in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
