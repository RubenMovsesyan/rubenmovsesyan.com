"""Cut a photographed pangram sheet into one PNG per letter.

No OCR: the text written on the sheet is supplied up front, so every ink blob
found on a line is matched positionally against a known string. Recognition
error is therefore zero; the only thing that can go wrong is segmentation,
which the debug overlay is there to show.

    python segment.py <image> --out <dir> [--rotate -90]
"""

import argparse
import json
import pathlib

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from scipy import ndimage

# What is on the sheet, one entry per written line, top to bottom.
LINES = [
    "THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG",
    "the quick brown fox jumps over the lazy dog",
    "THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG",
    "the quick brown fox jumps over the lazy dog",
]


def find_paper(gray, percentile=50, inset=20):
    """Mask off everything that is not the sheet of paper.

    The page is the large bright region in the frame. Its edge is ragged
    wherever the sheet falls into shadow, so the region is squared off row by
    row and column by column before being pulled inward -- eroding the raw
    threshold instead eats whole shadowed rows, which silently truncates the
    bottom of the page and loses the letters written there.
    """
    g = np.asarray(gray, dtype=np.float32)
    bright = g > np.percentile(g, percentile)

    labels, n = ndimage.label(bright)
    if n == 0:
        return np.ones_like(bright, dtype=bool)
    sizes = ndimage.sum(bright, labels, range(1, n + 1))
    paper = ndimage.binary_fill_holes(labels == (int(np.argmax(sizes)) + 1))

    # Fill each row, then each column, between its first and last paper pixel.
    solid = np.zeros_like(paper)
    cols = np.arange(paper.shape[1])
    for y in np.where(paper.any(axis=1))[0]:
        c = cols[paper[y]]
        solid[y, c[0] : c[-1] + 1] = True
    rows = np.arange(paper.shape[0])
    for x in np.where(solid.any(axis=0))[0]:
        r = rows[solid[:, x]]
        solid[r[0] : r[-1] + 1, x] = True

    # Pull the edge in, so the page border and its shadow are not read as ink.
    solid = ndimage.binary_erosion(solid, np.ones((1, 2 * inset + 1), bool))
    solid = ndimage.binary_erosion(solid, np.ones((2 * inset + 1, 1), bool))
    return solid


def load_ink(path, rotate):
    """Return the flattened image and the mask of where the paper is."""
    im = Image.open(path)
    # Phone photos carry their rotation in EXIF; apply it before anything else.
    im = ImageOps.exif_transpose(im)
    if rotate:
        im = im.rotate(rotate, expand=True)
    gray = im.convert("L")

    paper = find_paper(gray)

    # An uneven lighting gradient across the page would defeat a single global
    # threshold. Dividing by a heavily blurred copy of itself flattens it.
    background = gray.filter(ImageFilter.GaussianBlur(radius=60))
    g = np.asarray(gray, dtype=np.float32)
    b = np.asarray(background, dtype=np.float32)
    flat = g / np.maximum(b, 1.0)
    return flat, paper


def despeckle(ink, min_area):
    """Drop blobs too small to be part of a letter: paper grain, pen spatter."""
    labels, n = ndimage.label(ink)
    if n == 0:
        return ink
    sizes = ndimage.sum(ink, labels, range(1, n + 1))
    keep = np.concatenate([[False], sizes >= min_area])
    return keep[labels]


def find_lines(ink, min_gap_frac=0.4):
    """Split the page into text lines by horizontal ink projection."""
    rows = ink.sum(axis=1)
    active = rows > rows.max() * 0.02

    spans, start = [], None
    for i, on in enumerate(active):
        if on and start is None:
            start = i
        elif not on and start is not None:
            spans.append((start, i))
            start = None
    if start is not None:
        spans.append((start, len(active)))

    # Drop slivers (stray marks, paper edge).
    heights = [b - a for a, b in spans]
    if not heights:
        return []
    typical = np.median(heights)
    return [s for s, h in zip(spans, heights) if h > typical * min_gap_frac]


def components(band):
    """Label ink blobs in one line, returned left to right as bounding boxes."""
    labels, n = ndimage.label(band)
    boxes = []
    for sl_y, sl_x in ndimage.find_objects(labels):
        boxes.append([sl_x.start, sl_y.start, sl_x.stop, sl_y.stop])
    boxes.sort(key=lambda b: b[0])
    return labels, boxes


def merge_marks(boxes, overlap=0.55):
    """Join a glyph with its own detached marks — the dot over an i or a j.

    Two boxes merge when one sits above the other and their horizontal spans
    overlap by more than `overlap` of the narrower box.
    """
    merged, used = [], [False] * len(boxes)
    for i, a in enumerate(boxes):
        if used[i]:
            continue
        x0, y0, x1, y1 = a
        for j in range(i + 1, len(boxes)):
            if used[j]:
                continue
            bx0, by0, bx1, by1 = boxes[j]
            lo, hi = max(x0, bx0), min(x1, bx1)
            if hi <= lo:
                continue
            narrow = min(x1 - x0, bx1 - bx0)
            if (hi - lo) / max(narrow, 1) >= overlap:
                x0, y0, x1, y1 = min(x0, bx0), min(y0, by0), max(x1, bx1), max(y1, by1)
                used[j] = True
        used[i] = True
        merged.append([x0, y0, x1, y1])
    merged.sort(key=lambda b: b[0])
    return merged


def reconcile(boxes, target, verbose=True):
    """Fix up blob boundaries until there is exactly one box per letter.

    Two things go wrong when reading free-form handwriting. A capital drawn
    with a lifted pen (the arms of a K, the two stems of an H) lands as two
    blobs, and neighbouring letters written too close together fuse into one.
    Both happen on the same line, so simply merging until the count matches is
    not enough -- it stops as soon as the numbers agree, leaving one split
    unmerged and one fusion unsplit.

    So the two problems are handled separately. A split is recognised by its
    *combined* width staying within a normal letter's width; two real letters
    that happen to touch are far too wide to qualify. Anything still missing
    afterwards is a fusion, and gets cut at its thinnest column.

    Knowing the expected count comes from the sheet's text, not from
    recognising anything, so no OCR is involved.
    """
    boxes = [list(b) for b in boxes]
    med = float(np.median([b[2] - b[0] for b in boxes]))

    # Pass 1: rejoin strokes of a single letter.
    while len(boxes) > 1:
        cands = []
        for i in range(len(boxes) - 1):
            a, b = boxes[i], boxes[i + 1]
            gap = b[0] - a[2]
            combined = max(a[2], b[2]) - min(a[0], b[0])
            # Strokes of one letter genuinely overlap in x; letters written
            # close together still leave a non-negative gap.
            if gap < 0 and combined <= med * 1.45:
                cands.append((combined, i))
        if not cands:
            break
        _, i = min(cands)
        a, b = boxes[i], boxes[i + 1]
        if verbose:
            print(f"      joined split stroke at x={min(a[0],b[0])}-{max(a[2],b[2])}")
        boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
        del boxes[i + 1]

    # Pass 2: anything still short of the target is two letters run together.
    guard = 0
    while len(boxes) < target and guard < target:
        guard += 1
        i = max(range(len(boxes)), key=lambda k: boxes[k][2] - boxes[k][0])
        box = boxes[i]
        if verbose:
            print(f"      split fused pair at x={box[0]}-{box[2]}")
        left, right = split_box(box)
        boxes[i : i + 1] = [left, right]
        boxes.sort(key=lambda b: b[0])

    # Pass 3: still too many, so merge the narrowest remaining neighbours.
    while len(boxes) > target:
        widths = [
            max(boxes[i][2], boxes[i + 1][2]) - min(boxes[i][0], boxes[i + 1][0])
            for i in range(len(boxes) - 1)
        ]
        i = int(np.argmin(widths))
        a, b = boxes[i], boxes[i + 1]
        if verbose:
            print(f"      merged surplus at x={min(a[0],b[0])}-{max(a[2],b[2])}")
        boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
        del boxes[i + 1]

    return boxes


# Filled in by main() so split_box can see the page's ink.
_INK = None


def split_box(box):
    """Cut one box in two at its thinnest column of ink."""
    x0, y0, x1, y1 = box
    col = _INK[y0:y1, x0:x1].sum(axis=0)
    lo, hi = int(len(col) * 0.25), int(len(col) * 0.75)
    cut = x0 + lo + int(np.argmin(col[lo:hi])) if hi > lo else (x0 + x1) // 2
    return [x0, y0, cut, y1], [cut, y0, x1, y1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--out", required=True)
    ap.add_argument("--rotate", type=float, default=0)
    ap.add_argument("--threshold", type=float, default=0.88)
    ap.add_argument("--min-area", type=int, default=60)
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    (out / "glyphs").mkdir(parents=True, exist_ok=True)

    flat, paper = load_ink(args.image, args.rotate)
    ink = (flat < args.threshold) & paper

    ink = despeckle(ink, args.min_area)

    global _INK
    _INK = ink

    bands = find_lines(ink)
    print(f"found {len(bands)} text lines, expected {len(LINES)}")

    overlay = Image.fromarray(((1 - ink) * 255).astype(np.uint8)).convert("RGB")
    draw = ImageDraw.Draw(overlay)

    manifest = []
    for idx, (y0, y1) in enumerate(bands):
        if idx >= len(LINES):
            print(f"  line {idx}: unexpected extra line, skipped")
            continue

        expected = LINES[idx].replace(" ", "")
        band = ink[y0:y1]
        _, boxes = components(band)
        boxes = [b for b in boxes if (b[2] - b[0]) * (b[3] - b[1]) > args.min_area]
        boxes = merge_marks(boxes)
        boxes = reconcile(boxes, len(expected))

        status = "ok" if len(boxes) == len(expected) else "MISMATCH"
        print(f"  line {idx}: {len(boxes)} blobs vs {len(expected)} letters  [{status}]")

        colour = (40, 140, 60) if status == "ok" else (200, 40, 40)
        for k, (x0, by0, x1, by1) in enumerate(boxes):
            draw.rectangle([x0, y0 + by0, x1, y0 + by1], outline=colour, width=3)
            if len(boxes) != len(expected):
                continue
            ch = expected[k]
            pad = 6
            crop = ink[
                max(y0 + by0 - pad, 0) : y0 + by1 + pad,
                max(x0 - pad, 0) : x1 + pad,
            ]
            name = f"{idx}_{k:02d}_{'upper' if ch.isupper() else 'lower'}_{ch}.png"
            Image.fromarray(((1 - crop) * 255).astype(np.uint8)).save(out / "glyphs" / name)
            manifest.append(
                {
                    "file": name,
                    "char": ch,
                    "line": idx,
                    "index": k,
                    # Position of the crop on the page, needed later to work out
                    # the baseline and how far the glyph sits above or below it.
                    "box": [int(x0), int(y0 + by0), int(x1), int(y0 + by1)],
                    "line_band": [int(y0), int(y1)],
                }
            )

    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    overlay.save(out / "overlay.png")
    print(f"\nwrote {len(manifest)} glyphs -> {out/'glyphs'}")
    print(f"check {out/'overlay.png'}")


if __name__ == "__main__":
    main()
