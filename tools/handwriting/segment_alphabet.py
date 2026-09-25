"""Cut the alphabet sheet into one clean PNG per letter instance.

The sheet is 26 rows, one per letter, each row a run of "Aa Aa Aa ..." pairs.
That structure does all the identification work: row N is letter N, and within
a row the glyphs alternate uppercase, lowercase. Nothing is recognised, so
there is no recognition error to worry about -- only segmentation, which the
overlay is there to let you check.

Two filters are applied to every glyph, per the font's requirements:

  * only the largest connected stroke is kept (two for lowercase i and j, so
    the dot survives). This drops specks and slivers of neighbouring letters.
  * the row's baseline is recorded, so the builder can sit each glyph on it.

Groups that do not resolve cleanly into exactly two glyphs are discarded
rather than guessed at: there are a dozen or more instances of every letter
and only a handful are needed, so throwing away the doubtful ones is free.

    python segment_alphabet.py <image> --out <dir>
"""

import argparse
import json
import pathlib
import string

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.cluster.vq import kmeans2

from segment import despeckle, load_ink

ROWS = 26
# Lowercase letters that legitimately have a second, detached stroke.
TWO_PART = {"i", "j"}
# Lowercase letters whose tail drops below the baseline; aligned by hand.
DESCENDERS = set("gjpqy")


def row_bands(ink, rows=ROWS):
    """Find the horizontal band each written row occupies.

    Smearing the ink sideways fuses a row into one wide blob while leaving
    the rows separate, which survives the uneven hand-ruled spacing that
    defeats a plain projection profile. Any band still holding two rows is
    cut at its thinnest line of ink until the expected count is reached.
    """
    width = ink.shape[1]
    smeared = ndimage.binary_dilation(ink, np.ones((1, 101), bool))
    labels, _ = ndimage.label(smeared)
    bands = sorted(
        [sy.start, sy.stop]
        for sy, sx in ndimage.find_objects(labels)
        if (sx.stop - sx.start) > width * 0.5
    )

    profile = ink.sum(axis=1).astype(float)
    guard = 0
    while len(bands) < rows and guard < rows * 2:
        guard += 1
        i = int(np.argmax([b[1] - b[0] for b in bands]))
        y0, y1 = bands[i]
        h = y1 - y0
        lo, hi = y0 + int(h * 0.3), y0 + int(h * 0.7)
        cut = lo + int(np.argmin(profile[lo:hi])) if hi > lo else (y0 + y1) // 2
        bands[i : i + 1] = [[y0, cut], [cut, y1]]
        bands.sort()
    return bands


def union(a, b):
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def split_at_valley(box, ink):
    """Cut a box in two where the least ink crosses it."""
    x0, y0, x1, y1 = box
    col = ink[y0:y1, x0:x1].sum(axis=0)
    lo, hi = int(len(col) * 0.3), int(len(col) * 0.7)
    cut = x0 + lo + int(np.argmin(col[lo:hi])) if hi > lo else (x0 + x1) // 2
    return [x0, y0, cut, y1], [cut, y0, x1, y1]


def _fold(boxes):
    out = boxes[0]
    for b in boxes[1:]:
        out = union(out, b)
    return out


def two_letters(group, ink):
    """Resolve one "Aa" group into exactly two letter boxes.

    A group may hold more than two blobs, because this hand leaves strokes
    unjoined -- the dot of an i, the bar of an E, the cross of a t. Splitting
    the group by x into two clusters puts every loose stroke with the letter
    it sits over, without having to tell a stroke from a letter by size: at
    this size they are indistinguishable, since a lowercase letter is no
    bigger than an i's dot.
    """
    if len(group) == 1:
        return list(split_at_valley(group[0], ink))
    if len(group) == 2:
        return list(group)

    xs = np.array([[(b[0] + b[2]) / 2] for b in group], dtype=float)
    centres, _ = kmeans2(
        xs, np.array([[xs.min()], [xs.max()]]), minit="matrix", iter=40
    )
    left_centre = float(centres.min())
    side = [abs(float(x) - left_centre) > abs(float(x) - float(centres.max()))
            for x in xs.ravel()]
    left = [b for b, right in zip(group, side) if not right]
    right = [b for b, r in zip(group, side) if r]

    if not left or not right:
        gaps = [group[k + 1][0] - group[k][2] for k in range(len(group) - 1)]
        k = int(np.argmax(gaps))
        left, right = group[: k + 1], group[k + 1 :]
    return [_fold(left), _fold(right)]


def _alternating(boxes):
    """True when the row reads as a clean run of "tight gap, wide gap"."""
    if len(boxes) < 4 or len(boxes) % 2:
        return False
    gaps = np.array(
        [boxes[k + 1][0] - boxes[k][2] for k in range(len(boxes) - 1)], dtype=float
    )
    inside = float(np.median(gaps[0::2]))
    between = float(np.median(gaps[1::2]))
    return between > max(inside, 1.0) * 1.4


def join_overlapping(boxes):
    """Rejoin strokes of one letter, most overlapping first.

    A stroke the pen left unjoined sits over the letter it belongs to, so the
    two boxes overlap in x. The next letter along never does -- however tight
    the writing, it still starts after the previous one ends. Overlap is
    therefore the one signal that separates them, and size is not: a lowercase
    letter is no bigger than an i's dot.
    """
    boxes = [list(b) for b in boxes]
    while len(boxes) > 1:
        overlaps = [
            min(boxes[k][2], boxes[k + 1][2]) - max(boxes[k][0], boxes[k + 1][0])
            for k in range(len(boxes) - 1)
        ]
        k = int(np.argmax(overlaps))
        if overlaps[k] <= 0:
            break
        boxes[k : k + 2] = [union(boxes[k], boxes[k + 1])]
    return boxes


def pairs_by_height(boxes):
    """Pair letters by size when the spacing gives nothing away.

    Some rows are written so evenly that the gap inside a pair matches the gap
    between pairs, and no amount of looking at spacing will separate them. But
    a capital still stands taller than its lowercase, so a new pair can be
    started at every tall blob. Rows where the lowercase has an ascender (b, d,
    h, k, l, t) are the exception, and those are also the rows that the spacing
    already resolves.
    """
    heights = np.array([b[3] - b[1] for b in boxes], dtype=float)
    if len(heights) < 4:
        return None
    centres, _ = kmeans2(
        heights.reshape(-1, 1),
        np.array([[heights.min()], [heights.max()]]),
        minit="matrix",
        iter=40,
    )
    lo, hi = float(centres.min()), float(centres.max())
    if hi < lo * 1.35:
        return None  # the two cases are the same height; this tells us nothing

    tall = [abs(h - hi) <= abs(h - lo) for h in heights]
    if not tall[0]:
        return None  # a row must open with a capital

    groups = []
    for box, is_tall in zip(boxes, tall):
        groups.append([box]) if is_tall else (groups[-1].append(box) if groups else None)
    groups = [g for g in groups if g]

    # A row holds about as many pairs as it has blobs, halved. Straying far
    # from that means the split by height found something other than case --
    # in rows where the lowercase carries an ascender it is as tall as the
    # capital, and every blob reads as the start of a pair.
    if not 0.75 <= len(groups) / max(len(boxes) / 2, 1) <= 1.25:
        return None
    return groups


def _consecutive(boxes):
    return [[boxes[k], boxes[k + 1]] for k in range(0, len(boxes) - 1, 2)]


def _by_gap(boxes, ink):
    """Group on the assumption that gaps between pairs exceed gaps inside."""
    gaps = np.array(
        [boxes[k + 1][0] - boxes[k][2] for k in range(len(boxes) - 1)], dtype=float
    )
    if len(gaps) < 2:
        return None
    centres, _ = kmeans2(
        gaps.reshape(-1, 1),
        np.array([[gaps.min()], [gaps.max()]]),
        minit="matrix",
        iter=40,
    )
    cut = float(np.mean(centres))
    groups = [[boxes[0]]]
    for k, gap in enumerate(gaps):
        groups.append([boxes[k + 1]]) if gap > cut else groups[-1].append(boxes[k + 1])
    return [two_letters(g, ink) for g in groups]


def _spread(values):
    values = np.asarray(values, dtype=float)
    return float(np.std(values) / max(np.mean(values), 1.0))


def score_pairing(pairs):
    """Lower is better. A pairing is judged on being boring.

    Every pair in a row holds the same two letters, so a correct pairing puts
    glyphs of one size in the first slot and one size in the second. A wrong
    one mixes capitals and lowercase into the same slot, or chops letters in
    half, and either way the sizes scatter. Measuring that scatter picks the
    right answer without knowing which strategy produced it.
    """
    if not pairs or len(pairs) < 3:
        return float("inf")
    first = [p[0] for p in pairs]
    second = [p[1] for p in pairs]
    return (
        _spread([b[3] - b[1] for b in first])
        + _spread([b[3] - b[1] for b in second])
        + _spread([b[2] - b[0] for b in first])
        + _spread([b[2] - b[0] for b in second])
    )


def to_pairs(boxes, ink):
    """Split a row's blobs into "Aa" pairs.

    Three different assumptions can each resolve a row, and which one holds
    depends on how the row happens to be written -- spacing separates most
    rows, size separates the evenly spaced ones, and neither works where the
    pen was lifted mid-letter. Rather than guess, every strategy is run and
    the most self-consistent result wins.
    """
    if len(boxes) < 4:
        return []

    joined = join_overlapping(boxes)
    candidates = []
    for source in (boxes, joined):
        if _alternating(source):
            candidates.append(_consecutive(source))
        groups = pairs_by_height(source)
        if groups:
            candidates.append([two_letters(g, ink) for g in groups])
        by_gap = _by_gap(source, ink)
        if by_gap:
            candidates.append(by_gap)

    candidates = [c for c in candidates if c]
    if not candidates:
        return []
    return min(candidates, key=score_pairing)


def assign_to_anchors(comps, row_ids, anchors):
    """Give every stroke in the row to the letter it belongs to.

    Each stroke goes to the letter whose centre it is nearest. Splitting the
    row at the midpoints between letters looks equivalent but is not: a
    detached stroke is not centred on its letter -- the bar of an E reaches
    out to the right, far enough that its centre can land past the midpoint
    and be handed to the next letter along, which is how E lost its bar.
    """
    centres = [ (box[0] + box[2]) / 2 for box in anchors ]
    owned = [[] for _ in anchors]
    for cid in row_ids:
        cx = comps[cid]["cx"]
        # Compare centre to centre. Testing whether the stroke falls inside a
        # letter's box instead would tie wherever two boxes overlap -- and
        # they do overlap, because a capital's reach (the top bar of a J)
        # extends over the lowercase beside it. Every tie then went to
        # whichever letter came first, leaving the other with nothing.
        owned[int(np.argmin([abs(cx - c) for c in centres]))].append(cid)
    return owned


def claim(labels, comps, mine, share, max_paths=None):
    """Build one glyph from the strokes assigned to it.

    `share` clears specks and slivers. `max_paths` caps how many separate
    strokes a character may keep, which has to be per-character because this
    hand is not consistent about it: an E is a body plus a detached middle
    bar, an uppercase I is a stem between two bars, while most letters are a
    single stroke and anything extra is debris.
    """
    if not mine:
        return None, 0.0, 0

    areas = np.array([comps[c]["area"] for c in mine], dtype=float)
    if max_paths is None:
        keep = [c for c, a in zip(mine, areas) if a >= areas.max() * share]
    else:
        # A cap states that this character really does have that many strokes,
        # so the share floor drops out of the way -- a bar or a dot can be a
        # very small part of the letter's ink and still be what makes it
        # readable. Only specks are excluded.
        ranked = sorted(mine, key=lambda c: comps[c]["area"], reverse=True)
        keep = [c for c in ranked[:max_paths] if comps[c]["area"] >= areas.max() * 0.02]

    if not keep:
        return None, 0.0, 0

    x0 = min(comps[c]["box"][0] for c in keep)
    y0 = min(comps[c]["box"][1] for c in keep)
    x1 = max(comps[c]["box"][2] for c in keep)
    y1 = max(comps[c]["box"][3] for c in keep)

    mask = np.isin(labels[y0:y1, x0:x1], keep)
    dropped = 1.0 - len(keep) / len(mine)
    return (mask, [x0, y0, x1, y1]), float(dropped), len(keep)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--out", required=True)
    ap.add_argument("--rotate", type=float, default=0)
    ap.add_argument("--threshold", type=float, default=0.88)
    # The dot over an i is about 35 pixels of ink in this hand, so a despeckle
    # floor of 60 silently deleted every one of them before anything else ran.
    # Sensor noise sits at 1-5 pixels, leaving plenty of room below 25.
    ap.add_argument("--min-area", type=int, default=25)
    ap.add_argument("--strict-paths", action="store_true",
                    help="keep exactly one stroke per glyph (two for i and j)")
    ap.add_argument("--paths", default=None,
                    help="per-character stroke cap, e.g. 'E=2,i=2,j=2'; "
                         "overrides paths.json")
    ap.add_argument("--paths-file", default=str(pathlib.Path(__file__).parent / "paths.json"),
                    help="JSON map of character to stroke cap")
    ap.add_argument("--stroke-share", type=float, default=0.08,
                    help="keep strokes holding at least this share of the largest")
    ap.add_argument("--warn-dropped", type=float, default=0.15,
                    help="flag a glyph if this much of its ink was discarded")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    (out / "glyphs").mkdir(parents=True, exist_ok=True)

    path_limits = {}
    if args.paths_file and pathlib.Path(args.paths_file).exists():
        path_limits = {
            k: int(v)
            for k, v in json.loads(pathlib.Path(args.paths_file).read_text()).items()
            if not k.startswith("_")
        }
    if args.paths:
        for item in args.paths.split(","):
            key, _, value = item.partition("=")
            path_limits[key.strip()] = int(value)
    if path_limits:
        print("stroke caps: " + " ".join(f"{k}={v}" for k, v in sorted(path_limits.items())))

    flat, paper = load_ink(args.image, args.rotate)
    ink = despeckle((flat < args.threshold) & paper, args.min_area)

    bands = row_bands(ink)
    centres = np.array([(y0 + y1) / 2 for y0, y1 in bands])
    print(f"{len(bands)} rows")

    # Label once over the whole page. Slicing per row would cut a descender
    # from the row above into a fragment and count it as another letter.
    page_labels, n_comp = ndimage.label(ink)
    slices = ndimage.find_objects(page_labels)
    areas = ndimage.sum(ink, page_labels, range(1, n_comp + 1))

    comps = {}
    for i, (sy, sx) in enumerate(slices, start=1):
        box = [sx.start, sy.start, sx.stop, sy.stop]
        if (box[2] - box[0]) * (box[3] - box[1]) <= args.min_area:
            continue
        comps[i] = {
            "box": box,
            "cx": (box[0] + box[2]) / 2,
            "cy": (box[1] + box[3]) / 2,
            "area": float(areas[i - 1]),
            "row": int(np.argmin(np.abs(centres - (box[1] + box[3]) / 2))),
        }

    median_h = float(np.median([c["box"][3] - c["box"][1] for c in comps.values()]))

    per_row = [[] for _ in bands]
    per_row_ids = [[] for _ in bands]
    for cid, c in comps.items():
        per_row[c["row"]].append(c["box"])
        per_row_ids[c["row"]].append(cid)

    overlay = Image.fromarray(((~ink) * 255).astype(np.uint8)).convert("RGB")
    draw = ImageDraw.Draw(overlay)

    manifest, suspect = [], []
    for row, (y0, y1) in enumerate(bands):
        if row >= ROWS:
            break
        letter = string.ascii_uppercase[row]

        row_ids = per_row_ids[row]
        if len(row_ids) < 4:
            print(f"  {letter}: only {len(row_ids)} blobs, skipped")
            continue

        # Work out the pairing from letter bodies alone. A detached bar or dot
        # counted as a letter shifts every anchor after it, which is what cost
        # E its middle bar. The fragments are put back below, by proximity.
        # A fragment is both short and light. Judging on ink alone loses a
        # thin descender like j, which covers little ink but is clearly a
        # letter; judging on height alone loses nothing but keeps long bars.
        row_area = float(np.median([comps[c]["area"] for c in row_ids]))
        row_height = float(np.median([comps[c]["box"][3] - comps[c]["box"][1]
                                      for c in row_ids]))
        bodies = sorted(
            (comps[c]["box"] for c in row_ids
             if not (comps[c]["box"][3] - comps[c]["box"][1] < row_height * 0.45
                     and comps[c]["area"] < row_area * 0.4)),
            key=lambda b: b[0],
        )
        if len(bodies) < 4:
            print(f"  {letter}: only {len(bodies)} letter bodies, skipped")
            continue

        pairs = to_pairs(bodies, ink)
        pairs = [p for p in pairs if len(p) == 2]

        # The row's baseline: where its glyphs sit. Descender rows still have
        # their capitals and non-descending letters to define it.
        bottoms = [g[3] for p in pairs for g in p]
        baseline = float(np.median(bottoms))
        if letter.lower() in DESCENDERS:
            upper = [p[0][3] for p in pairs]
            if upper:
                baseline = float(np.median(upper))

        # "Aa": the capital comes first. If the leading glyphs are the shorter
        # ones the row has slipped by one, which would mislabel every glyph.
        first_h = np.median([p[0][3] - p[0][1] for p in pairs]) if pairs else 0
        second_h = np.median([p[1][3] - p[1][1] for p in pairs]) if pairs else 0
        slipped = first_h < second_h * 0.8
        if slipped:
            print(f"  {letter}: leading glyphs are shorter "
                  f"({first_h:.0f} vs {second_h:.0f}px) -- row skipped as misaligned")
            continue

        # Each stroke in the row goes to the letter nearest it.
        anchors = [b for pair in pairs for b in pair]
        owned = assign_to_anchors(comps, row_ids, anchors)

        kept = 0
        for index, (up, lo) in enumerate(pairs):
            for slot, (box, ch) in enumerate(((up, letter), (lo, letter.lower()))):
                claimed, dropped, strokes = claim(
                    page_labels, comps, owned[index * 2 + slot],
                    args.stroke_share, path_limits.get(ch),
                )
                if claimed is None:
                    continue
                mask, box = claimed
                if not mask.any():
                    continue
                name = f"{ch if ch.isupper() else ch+'_'}_{row:02d}_{index:02d}.png"
                name = f"{'upper' if ch.isupper() else 'lower'}{ch.upper()}_{index:02d}.png"
                Image.fromarray(((~mask) * 255).astype(np.uint8)).save(out / "glyphs" / name)
                manifest.append({
                    "file": name,
                    "char": ch,
                    "row": row,
                    "index": index,
                    "box": [int(v) for v in box],
                    "baseline": baseline,
                    "dropped": round(dropped, 4),
                    "strokes": strokes,
                })
                if dropped > args.warn_dropped:
                    suspect.append((name, dropped))
                kept += 1
                draw.rectangle(box, outline=(40, 140, 60) if ch.isupper() else (30, 90, 200), width=3)

        draw.line([2, baseline, ink.shape[1] - 3, baseline], fill=(220, 60, 60), width=2)
        draw.text((12, y0 + 4), letter, fill=(20, 120, 200))
        print(f"  {letter}: {len(pairs):2d} pairs -> {kept:2d} glyphs")

    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    overlay.save(out / "overlay.png")

    counts = {}
    for g in manifest:
        counts[g["char"]] = counts.get(g["char"], 0) + 1
    thin = {c: n for c, n in counts.items() if n < 4}

    print(f"\n{len(manifest)} glyphs, {len(counts)} distinct characters")
    print(f"instances per character: min {min(counts.values())} max {max(counts.values())}")
    if thin:
        print(f"  few instances: {thin}")
    multi = {}
    for g in manifest:
        if g["strokes"] > 1:
            multi[g["char"]] = multi.get(g["char"], 0) + 1
    if multi and not args.strict_paths:
        shown = ", ".join(f"{c}x{n}" for c, n in sorted(multi.items(), key=lambda t: -t[1])[:14])
        print(f"\nletters written with more than one stroke: {shown}")

    if suspect:
        print(f"\n{len(suspect)} glyphs lost more than "
              f"{args.warn_dropped:.0%} of their ink to stroke filtering:")
        for name, frac in sorted(suspect, key=lambda t: -t[1])[:12]:
            print(f"    {name}  -{frac:.0%}")
    print(f"\ncheck {out/'overlay.png'}")


if __name__ == "__main__":
    main()
