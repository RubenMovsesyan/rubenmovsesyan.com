"""Build an OTF/WOFF2 from segmented handwriting, with cycling alternates.

Every letter gets several variants and a `calt` feature that walks a cycle
through them as the text runs, so repeated letters are not stamped copies.
`calt` is on by default in browsers, which is why it is used rather than the
`rand` feature, which is barely supported.

Glyphs are seated on the baseline two different ways. For almost every letter
the lowest point of the ink *is* where it rests on the page, so it is placed
there directly. For g, j, p, q and y the tail drops below the line, so the
baseline comes from alignment.json, set by eye with align.py.

    python build_font.py --seg <dir> --out <dir> [--variants 3]
"""

import argparse
import json
import os
import pathlib
import sys

import numpy as np
import potrace
from fontTools.feaLib.builder import addOpenTypeFeatures
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import glyphset  # noqa: E402

UPM = 1000
CAP_HEIGHT = 700          # where capitals land; sets the global scale
SIDEBEARING = 34          # breathing room each side of every glyph
SPACE_WIDTH = 260

DESCENDERS = glyphset.DESCENDERS


def glyph_name(ch):
    return f"{'upper' if ch.isupper() else 'lower'}{ch.upper()}"


def pt(p):
    return (p.x, p.y)


def trace(mask):
    """potrace a boolean ink mask into closed contours."""
    # potrace follows the image convention that dark pixels are the shape, so
    # the ink mask is inverted. It must stay boolean: an integer array is read
    # as 0-255 levels and collapses to one rectangle.
    path = potrace.Bitmap(~mask).trace()
    contours = []
    for curve in path:
        segs = []
        for seg in curve:
            if seg.is_corner:
                segs.append(("L", [pt(seg.c)]))
                segs.append(("L", [pt(seg.end_point)]))
            else:
                segs.append(("C", [pt(seg.c1), pt(seg.c2), pt(seg.end_point)]))
        contours.append((pt(curve.start_point), segs))
    return contours


def draw(pen, contours, dx, baseline, scale):
    """Emit contours in font units: x from the left sidebearing, y up from the
    baseline, which is a row index inside the crop."""
    def P(p):
        return (p[0] * scale + dx, (baseline - p[1]) * scale)

    for start, segs in contours:
        pen.moveTo(P(start))
        for kind, pts in segs:
            pen.lineTo(P(pts[-1])) if kind == "L" else pen.curveTo(*map(P, pts))
        pen.closePath()


def load_mask(seg, entry):
    arr = np.asarray(Image.open(seg / "glyphs" / entry["file"]).convert("L"))
    return arr < 128


def feature_code(letters, variants):
    base = " ".join(glyph_name(c) for c in letters)
    classes = [f"@base = [{base}];"]
    for v in range(1, variants):
        classes.append(
            f"@alt{v} = [" + " ".join(f"{glyph_name(c)}.alt{v}" for c in letters) + "];"
        )

    names = ["@base"] + [f"@alt{v}" for v in range(1, variants)]
    rules = []
    for i, prev in enumerate(names):
        nxt = names[(i + 1) % len(names)]
        rules.append(f"    sub {prev} @base' by {nxt};")
    for i, prev in enumerate(names):
        nxt = names[(i + 1) % len(names)]
        # Across a word break, so the cycle keeps its phase instead of
        # resetting to the base form at the start of every word.
        rules.append(f"    sub {prev} space @base' by {nxt};")

    return "\n".join(classes) + "\n\nfeature calt {\n" + "\n".join(rules) + "\n} calt;\n"


def validate(*paths):
    """Run OTS, the sanitiser browsers use, over the built files.

    A font can render perfectly through FreeType and still be refused by every
    browser, which shows up only as a silent fallback to a default face.
    """
    try:
        import ots
    except ImportError:
        print("\n! opentype-sanitizer not installed; skipping validation")
        return
    for path in paths:
        r = ots.sanitize(str(path), os.devnull, check=False, capture_output=True)
        msg = ((r.stdout or b"") + (r.stderr or b"")).decode(errors="replace").strip()
        if r.returncode != 0:
            raise SystemExit(f"\nOTS rejected {path.name}:\n{msg}")
        print(f"OTS ok: {path.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--variants", type=int, default=3)
    ap.add_argument("--name", default="Hand Scan")
    args = ap.parse_args()

    seg = pathlib.Path(args.seg)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    manifest = glyphset.load(seg)
    chosen = glyphset.pick(manifest, args.variants, seg)

    align_file = seg / "alignment.json"
    aligned = json.loads(align_file.read_text()) if align_file.exists() else {}
    print(f"{len(aligned)} hand-set baselines loaded" if aligned
          else "no alignment.json; descenders will use the row baseline")

    letters = sorted(chosen)
    masks, baselines = {}, {}
    unaligned = []

    for ch in letters:
        for v in range(args.variants):
            picks = chosen[ch]
            entry = picks[v % len(picks)]
            mask = load_mask(seg, entry)
            name = glyph_name(ch) + ("" if v == 0 else f".alt{v}")

            if ch in DESCENDERS:
                if entry["file"] in aligned:
                    base = float(aligned[entry["file"]])
                else:
                    base = float(entry["baseline"]) - entry["box"][1]
                    unaligned.append(entry["file"])
            else:
                # Its lowest point is where it sits on the page.
                base = float(mask.shape[0])

            masks[name] = mask
            baselines[name] = base

    # One global scale, pinned to capital height.
    caps = [baselines[glyph_name(c)] for c in letters if c.isupper()]
    scale = CAP_HEIGHT / float(np.median(caps))
    print(f"cap height {np.median(caps):.1f}px -> {CAP_HEIGHT} units (scale {scale:.2f})")
    if unaligned:
        print(f"! {len(unaligned)} descender glyphs have no hand-set baseline; "
              f"run align.py --seg {seg}")

    glyph_order = [".notdef", "space"]
    charstrings, advances = {}, {}
    fb = FontBuilder(UPM, isTTF=False)

    for name, mask in masks.items():
        pen = T2CharStringPen(None, None)
        draw(pen, trace(mask), SIDEBEARING, baselines[name], scale)
        width = int(round(mask.shape[1] * scale)) + 2 * SIDEBEARING
        cs = pen.getCharString()
        cs.width = width
        charstrings[name] = cs
        advances[name] = width
        glyph_order.append(name)

    for name, w in ((".notdef", SPACE_WIDTH), ("space", SPACE_WIDTH)):
        cs = T2CharStringPen(None, None).getCharString()
        cs.width = w
        charstrings[name] = cs
        advances[name] = w

    # The CFF name is a PostScript name: no spaces, or OTS rejects the font
    # and every browser silently falls back to a default face.
    ps_name = args.name.replace(" ", "")

    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap({ord(c): glyph_name(c) for c in letters} | {32: "space"})
    fb.setupCFF(ps_name, {"FullName": args.name}, charstrings, {})
    fb.setupHorizontalMetrics({n: (advances[n], 0) for n in glyph_order})
    fb.setupHorizontalHeader(ascent=800, descent=-300)
    fb.setupNameTable({"familyName": args.name, "styleName": "Regular", "psName": ps_name})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-300, usWinAscent=950,
                usWinDescent=400, sxHeight=410, sCapHeight=CAP_HEIGHT)
    fb.setupPost()

    fea = out / "features.fea"
    fea.write_text(feature_code(letters, args.variants))
    addOpenTypeFeatures(fb.font, str(fea))

    otf = out / "hand.otf"
    fb.save(str(otf))
    fb.font.flavor = "woff2"
    woff = out / "hand.woff2"
    fb.font.save(str(woff))

    validate(otf, woff)
    print(f"\n{len(glyph_order)} glyphs ({len(letters)} letters x {args.variants} variants)")
    print(f"wrote {woff}  ({woff.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
