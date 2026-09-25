"""Choosing which scanned instances of a letter actually go into the font.

The sheet holds a dozen or more of every letter and the font needs only a
handful, so the job is picking good ones rather than salvaging every one.

Ranking by how much ink the stroke filter discarded does not work: a stray
sliver sitting alone in its box discards nothing and so scores perfectly. What
separates a good instance from a bad one is being ordinary -- a fragment is too
small, and a capital that drifted into a lowercase slot is too big. So
instances are scored on how close they are to the median size for that
character, which quietly rejects both.
"""

import json
import pathlib

import numpy as np
from PIL import Image

DESCENDERS = set("gjpqy")


def load(seg_dir):
    seg_dir = pathlib.Path(seg_dir)
    manifest = json.loads((seg_dir / "manifest.json").read_text())
    for g in manifest:
        x0, y0, x1, y1 = g["box"]
        g["w"], g["h"] = x1 - x0, y1 - y0
    return manifest


def by_char(manifest):
    out = {}
    for g in manifest:
        out.setdefault(g["char"], []).append(g)
    return out


def _raster(seg, entry, size=18):
    """A small normalised picture of one glyph, for comparing shapes."""
    img = Image.open(seg / "glyphs" / entry["file"]).convert("L").resize((size, size))
    ink = 1.0 - np.asarray(img, dtype=np.float32) / 255.0
    return ink / max(float(ink.sum()), 1e-6)


def reject_outliers(seg, instances, cutoff=1.8):
    """Drop instances that are not the same shape as the rest.

    Pairing can misread a row and file a capital in the lowercase slot -- a D
    among the d's. Size will not catch it: in this hand D and d are the same
    height and within a few pixels of the same width, because the d's ascender
    is as tall as the capital. What differs is the shape, the bowl sitting on
    the other side of the stem, so the glyphs are compared as pictures against
    the median for that character and the ones that do not match are dropped.
    """
    if seg is None or len(instances) < 6:
        return list(instances)

    try:
        rasters = [_raster(seg, g) for g in instances]
    except (OSError, ValueError):
        return list(instances)

    median = np.median(np.stack(rasters), axis=0)
    distances = np.array([np.abs(r - median).sum() for r in rasters])
    typical = float(np.median(distances))
    kept = [g for g, d in zip(instances, distances) if d <= typical * cutoff]

    # Never strip a character down to too few to build variants from.
    return kept if len(kept) >= 4 else list(instances)


def rank(instances, seg=None):
    """Most ordinary first."""
    if len(instances) < 3:
        return list(instances)

    instances = reject_outliers(seg, instances)
    mw = float(np.median([g["w"] for g in instances]))
    mh = float(np.median([g["h"] for g in instances]))

    def score(g):
        return (
            abs(g["w"] - mw) / max(mw, 1)
            + abs(g["h"] - mh) / max(mh, 1)
            # Among equally typical shapes, prefer the one that needed the
            # least filtering.
            + g.get("dropped", 0.0) * 0.5
        )

    return sorted(instances, key=score)


def pick(manifest, count, seg=None):
    """{char: [chosen instances]} -- up to `count` of each, best first."""
    seg = pathlib.Path(seg) if seg else None
    return {ch: rank(v, seg)[:count] for ch, v in by_char(manifest).items()}
