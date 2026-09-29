"""Look at a notebook photo before tracing from it.

    photo.py find IMG_5288                    # each drawing on the sheet, as a --region box
    photo.py overview IMG_5288 -o page.png    # the whole sheet at 1/6 size
    photo.py crop IMG_5288 X0,Y0,X1,Y1 -o c.png [--scale 0.5]

A sheet often holds several drawings (earlier figures, an upside-down
equation at the bottom), so tracing needs a --region. `find` groups the ink
into separate drawings and prints each one's box in photo pixels, ready to
pass to `figure.py trace --region`. Photos are named as in assets/img
(IMG_5288, IMG_5288.DNG) or given as a path.

Run with tools/figures/.venv/bin/python (numpy, scipy, Pillow).
"""

import argparse
import pathlib
import sys

import numpy as np
from PIL import Image, ImageOps
from scipy import ndimage

WEBSITE = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(WEBSITE / "tools" / "handwriting"))
from segment import despeckle, load_ink  # noqa: E402

SEARCH = [WEBSITE / "assets" / "img", WEBSITE / "assets" / "tests"]


def locate(name):
    p = pathlib.Path(name)
    if p.exists():
        return p
    stem = p.name if p.suffix else p.name + ".DNG"
    for d in SEARCH:
        if (d / stem).exists():
            return d / stem
    raise SystemExit(
        f"{name}: not in the checkout. The photos live only on the server; fetch them with\n"
        f"  git sparse-checkout set --no-cone '/*'\n"
        f"and hide them again afterwards (see CLAUDE.md)."
    )


def cmd_find(args):
    flat, paper = load_ink(str(locate(args.photo)), 0, args.paper)
    ink = despeckle((flat < args.threshold) & paper, 40)
    # Work at 1/4 size: ink within ~--gap pixels becomes one drawing.
    k = 4
    h, w = ink.shape[0] // k * k, ink.shape[1] // k * k
    small = ink[:h, :w].reshape(h // k, k, w // k, k).any(axis=(1, 3))
    grown = ndimage.binary_dilation(small, iterations=max(1, args.gap // k))
    labels, n = ndimage.label(grown)
    found = []
    for i, (sy, sx) in enumerate(ndimage.find_objects(labels), start=1):
        count = int((small & (labels == i)).sum()) * k * k
        if count < args.min_ink:
            continue
        pad = args.pad
        box = (max(sx.start * k - pad, 0), max(sy.start * k - pad, 0),
               min(sx.stop * k + pad, ink.shape[1]), min(sy.stop * k + pad, ink.shape[0]))
        found.append((box, count))
    found.sort(key=lambda f: (f[0][1], f[0][0]))
    print(f"{len(found)} drawings on the sheet (top to bottom); pass one as --region:")
    H, W = ink.shape
    for (x0, y0, x1, y1), count in found:
        # The lowered paper threshold can take in the table past the sheet.
        edge = min(x0, y0, W - x1, H - y1) < 100
        note = "   <- at the photo's edge: probably the table, not a drawing" if edge else ""
        print(f"  --region {x0},{y0},{x1},{y1}   {x1 - x0}x{y1 - y0}px, ~{count} ink px{note}")
    print("Handwriting splits into more boxes than a drawing does; join neighbouring ones by hand.")


def load(photo):
    return ImageOps.exif_transpose(Image.open(locate(photo))).convert("L")


def cmd_overview(args):
    im = load(args.photo)
    im.resize((im.width // 6, im.height // 6)).save(args.out)
    print(f"wrote {args.out} at 1/6 size: multiply its pixel positions by 6 for --region")


def cmd_crop(args):
    x0, y0, x1, y1 = (int(v) for v in args.box.split(","))
    im = load(args.photo).crop((x0, y0, x1, y1))
    if args.scale != 1:
        im = im.resize((round(im.width * args.scale), round(im.height * args.scale)))
    im.save(args.out)
    print(f"wrote {args.out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find", help="list the drawings on a sheet as --region boxes")
    f.add_argument("photo")
    f.add_argument("--gap", type=int, default=60, help="ink closer than this is one drawing")
    f.add_argument("--pad", type=int, default=50, help="pixels added around each box")
    f.add_argument("--min-ink", type=int, default=3000, help="ignore groups with less ink")
    f.add_argument("--threshold", type=float, default=0.88)
    # 25, not trace's 50: the far end of a sheet is often in shadow, and a
    # drawing there must still be found. Pass the same --paper to trace.
    f.add_argument("--paper", type=int, default=25, help="brightness percentile that counts as paper")
    f.set_defaults(func=cmd_find)
    o = sub.add_parser("overview", help="the sheet at 1/6 size")
    o.add_argument("photo")
    o.add_argument("-o", "--out", required=True)
    o.set_defaults(func=cmd_overview)
    c = sub.add_parser("crop", help="part of the sheet at full resolution")
    c.add_argument("photo")
    c.add_argument("box", help="X0,Y0,X1,Y1 in photo pixels")
    c.add_argument("-o", "--out", required=True)
    c.add_argument("--scale", type=float, default=1.0)
    c.set_defaults(func=cmd_crop)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
