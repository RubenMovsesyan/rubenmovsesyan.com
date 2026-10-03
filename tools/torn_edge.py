"""Make the notebook's torn top edge mask from a torn-paper picture.

    tools/figures/.venv/bin/python tools/torn_edge.py

Reads assets/textures/torn-paper.png: white paper across the top, its torn
edge across the middle, a soft black drop shadow under the tear, transparent
below. Writes assets/textures/torn-edge-mask.png, which notebook.css uses as
the mask of the notebook's top edge:

  * only the paper, not its shadow: coverage = brightness x opacity, so the
    near-white paper counts, the black shadow doesn't, and the paper's own
    soft edge survives;
  * cropped to the strip around the tear;
  * flipped, because on the site the paper lies below its torn edge.

White with the coverage as alpha, so CSS masks with it as it is.
"""

import pathlib

import numpy as np
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
SOURCE = HERE.parent / "assets" / "textures" / "torn-paper.png"
OUT = HERE.parent / "assets" / "textures" / "torn-edge-mask.png"
# Solid paper kept below the deepest notch, so the strip ends in paper.
PAD = 6


def main():
    im = np.asarray(Image.open(SOURCE).convert("LA"), dtype=np.float32) / 255.0
    lum, alpha = im[..., 0], im[..., 1]
    # The paper's white varies a little (a soft gradient across it); its
    # darkest counts as full coverage, so all of it is solid.
    solid = alpha > 0.99
    paper_white = lum[solid].min()
    coverage = np.clip(lum * alpha / paper_white, 0.0, 1.0)

    # The tear: in each column, where the paper ends.
    covered = coverage > 0.5
    rows = np.arange(coverage.shape[0])[:, None]
    ends = np.where(covered, rows, -1).max(axis=0)       # last paper row per column
    starts = np.where(~covered, rows, coverage.shape[0]).min(axis=0)  # first gap per column
    top = max(int(starts.min()) - PAD, 0)                  # highest notch
    bottom = int(ends.max()) + 2                           # deepest tip, plus its soft edge

    strip = coverage[top:bottom][::-1]                     # flip: paper below the tear
    rgba = np.zeros(strip.shape + (4,), dtype=np.uint8)
    rgba[..., :3] = 255
    rgba[..., 3] = np.round(strip * 255).astype(np.uint8)
    Image.fromarray(rgba, "RGBA").save(OUT, optimize=True)
    print(f"tear spans rows {top}-{bottom} of {coverage.shape[0]}; "
          f"wrote {OUT.name}: {strip.shape[1]}x{strip.shape[0]}, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
