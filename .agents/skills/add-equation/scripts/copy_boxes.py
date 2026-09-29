"""Give a traced equation its copyable LaTeX: one copy box per written line.

    copy_boxes.py eq4 'x^2 + y^2 = r^2'
    copy_boxes.py eq3 'x^2 + y^2 = k_1 x + k_2 y + k_3' 'k = A^{-1} B'

Splits tools/figures/<name>/preview.png into as many text lines as LaTeX
strings are given, at the widest blank rows, and lays an invisible copy box
over each line's ink (figure.py's "copy" kind). Selecting the handwriting
then copies the LaTeX. Each string is wrapped in $$...$$ unless it already
starts with $. Existing copy boxes are replaced; any labels are kept. Then
renders assets/figures/<name>.svg.

For parts side by side on one line (eq. 1's three definitions), write the
boxes into labels.json by hand -- {"kind": "copy", "text", "x", "y", "w", "h"}
in preview pixels -- or split them with --columns.

Run with tools/figures/.venv/bin/python (numpy, Pillow).
"""

import argparse
import json
import pathlib
import subprocess
import sys

import numpy as np
from PIL import Image

WEBSITE = pathlib.Path(__file__).resolve().parents[4]
FIGURES = WEBSITE / "tools" / "figures"


def runs(mask_1d):
    """(start, stop) of each run of False in a 1-D boolean array."""
    out, start = [], None
    for i, on in enumerate(mask_1d):
        if not on and start is None:
            start = i
        if on and start is not None:
            out.append((start, i))
            start = None
    return out


def split(ink, n, axis):
    """Cut ink into n bands along an axis (0 = rows, 1 = columns) at the n-1
    widest blank gaps between its first and last inked line."""
    used = ink.any(axis=1 - axis)
    lo, hi = np.flatnonzero(used)[[0, -1]]
    gaps = [(b - a, (a + b) // 2) for a, b in runs(used) if a > lo and b <= hi]
    if len(gaps) < n - 1:
        raise SystemExit(f"found {len(gaps) + 1} separate {'lines' if axis == 0 else 'columns'}, "
                         f"but {n} strings were given")
    cuts = sorted(c for _, c in sorted(gaps, reverse=True)[: n - 1])
    return list(zip([0] + cuts, cuts + [ink.shape[axis]]))


def ink_box(ink, y0, y1, x0, x1):
    ys, xs = np.nonzero(ink[y0:y1, x0:x1])
    if not len(ys):
        raise SystemExit(f"no ink between rows {y0}-{y1}, columns {x0}-{x1}")
    return int(x0 + xs.min()), int(y0 + ys.min()), int(x0 + xs.max()), int(y0 + ys.max())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("name", help="the equation's name in tools/figures, e.g. eq4")
    ap.add_argument("latex", nargs="+", help="LaTeX for each line, top to bottom")
    ap.add_argument("--columns", action="store_true",
                    help="the strings are side-by-side parts of one line, left to right")
    args = ap.parse_args()

    d = FIGURES / args.name
    if not (d / "preview.png").exists():
        raise SystemExit(f"no trace in {d}; run figure.py trace ... --name {args.name} --join 0 first")
    ink = np.asarray(Image.open(d / "preview.png").convert("L")) < 128

    n = len(args.latex)
    boxes = []
    if args.columns:
        for x0, x1 in split(ink, n, axis=1):
            boxes.append(ink_box(ink, 0, ink.shape[0], x0, x1))
    else:
        for y0, y1 in split(ink, n, axis=0):
            boxes.append(ink_box(ink, y0, y1, 0, ink.shape[1]))

    labels_path = d / "labels.json"
    kept = [l for l in json.loads(labels_path.read_text()) if l.get("kind") != "copy"] \
        if labels_path.exists() else []
    copies = []
    for text, (x0, y0, x1, y1) in zip(args.latex, boxes):
        text = text if text.startswith("$") else f"$${text}$$"
        copies.append({"kind": "copy", "text": text, "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})
        print(f"  {x0},{y0} {x1 - x0}x{y1 - y0}: {text}")
    labels_path.write_text(json.dumps(copies + kept, indent=1))

    figure = FIGURES / "figure.py"
    subprocess.run([sys.executable, str(figure), "render", args.name], check=True)


if __name__ == "__main__":
    main()
