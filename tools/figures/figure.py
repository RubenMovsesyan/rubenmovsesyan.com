"""Turn a photographed drawing into a labelled SVG figure for the site.

Three steps, each a subcommand:

    python figure.py trace <photo> --name fig1     # photo -> drawing.svg
    python figure.py label fig1                    # place labels by hand
    python figure.py render fig1                   # drawing + labels -> site

`trace` finds the ink on the page, crops to it, and potraces it into filled
paths, so the strokes keep the wobble of the pen rather than being redrawn.
Everything a figure needs is kept in tools/figures/<name>/: drawing.svg,
the preview.png the labeller shows (same pixel grid as the SVG), meta.json,
and labels.json, which is hand work -- commit it.

`render` writes assets/figures/<name>.svg, which index.html inlines. Labels
are real <text>, not outlines: inlined, they pick up the page's own font
stack (the scanned hand, falling back to Kalam for digits and punctuation)
and its `calt` alternates, which a path export would freeze.
"""

import argparse
import html
import json
import pathlib
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = pathlib.Path(__file__).parent
WEBSITE = HERE.parent.parent
FONT = WEBSITE / "assets" / "fonts" / "hand.woff2"
OUT = WEBSITE / "assets" / "figures"

sys.path.insert(0, str(HERE.parent / "handwriting"))
from segment import despeckle, load_ink  # noqa: E402

# The figure is shown ~560px wide (the written column, measured in Chromium),
# and body text is ~17px. Labels default to that size, in drawing units.
COLUMN_PX = 560
BODY_PX = 17
# hand.woff2 is served with size-adjust: 140% (base.css); the width estimate
# used to keep leader lines clear of the text has to include it.
SIZE_ADJUST = 1.4
# Digits and punctuation fall back to Kalam; guess their width.
FALLBACK_ADVANCE = 0.5
# Space left between a label and the end of its leader line, in em.
LINE_GAP = 0.5


def fig_dir(name):
    return HERE / name


# ─── trace ──────────────────────────────────────────────────────────────────


def stroke_width(mask):
    """Typical pen width in pixels: twice the median distance to paper along
    the middle of the strokes. The median, so filled dots don't inflate it."""
    dist = ndimage.distance_transform_edt(mask)
    ridge = mask & (dist >= ndimage.maximum_filter(dist, size=3))
    return 2.0 * float(np.median(dist[ridge]))


def contours_to_path(path):
    """potrace output as SVG path data, in pixel coordinates (y down)."""
    def p(pt):
        return f"{pt.x:.1f} {pt.y:.1f}"

    parts = []
    for curve in path:
        parts.append(f"M{p(curve.start_point)}")
        for seg in curve:
            if seg.is_corner:
                parts.append(f"L{p(seg.c)}L{p(seg.end_point)}")
            else:
                parts.append(f"C{p(seg.c1)} {p(seg.c2)} {p(seg.end_point)}")
        parts.append("Z")
    return "".join(parts)


def cmd_trace(args):
    import potrace

    d = fig_dir(args.name)
    d.mkdir(parents=True, exist_ok=True)

    flat, paper = load_ink(args.photo, args.rotate)
    ink = despeckle((flat < args.threshold) & paper, args.min_area)
    # A sheet can hold more than one drawing; --region picks one out.
    if args.region:
        x0, y0, x1, y1 = (int(v) for v in args.region.split(","))
        keep = np.zeros_like(ink)
        keep[y0:y1, x0:x1] = True
        ink &= keep
    # Drops strokes thinner than 2 * --open pixels -- faint guide lines that
    # only half survive the threshold -- and keeps dots and solid marks.
    if args.open:
        r = args.open
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        ink = ndimage.binary_opening(ink, structure=xx * xx + yy * yy <= r * r)
    if not ink.any():
        raise SystemExit("no ink found; try a higher --threshold")

    # Grain and shadow along the page edge survive the threshold. The drawing
    # is one cluster -- its dashes sit within a few pen widths of each other --
    # so ink within --join pixels is grouped and only the largest group kept.
    if args.join > 0:
        near = ndimage.binary_dilation(ink, iterations=args.join)
        groups, n = ndimage.label(near)
        sizes = ndimage.sum(ink, groups, range(1, n + 1))
        ink &= groups == int(np.argmax(sizes)) + 1
        if n > 1:
            print(f"kept the largest of {n} ink clusters ({sizes.max() / sizes.sum():.0%} of the ink)")

    ys, xs = np.where(ink)
    m = args.margin
    x0, y0 = max(xs.min() - m, 0), max(ys.min() - m, 0)
    x1, y1 = min(xs.max() + m + 1, ink.shape[1]), min(ys.max() + m + 1, ink.shape[0])
    mask = ink[y0:y1, x0:x1]
    h, w = mask.shape

    # potrace reads dark pixels as the shape; the mask must stay boolean.
    path = potrace.Bitmap(~mask).trace(turdsize=args.min_area)
    # Rings (the orbits) come out as an outer and an inner contour; evenodd
    # leaves the inside of each ring empty.
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">\n'
        f'  <path class="fig-ink" fill="currentColor" fill-rule="evenodd" '
        f'd="{contours_to_path(path)}"/>\n'
        f"</svg>\n"
    )
    (d / "drawing.svg").write_text(svg)
    Image.fromarray(np.where(mask, 0, 255).astype(np.uint8)).save(d / "preview.png")

    meta = {
        "photo": str(pathlib.Path(args.photo).resolve().relative_to(WEBSITE)),
        "crop": [int(x0), int(y0), int(x1), int(y1)],
        "width": w,
        "height": h,
        "stroke": round(float(stroke_width(mask)), 2),
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=1))

    print(f"cropped to {w}x{h}px at {x0},{y0}; pen width ~{meta['stroke']}px")
    print(f"wrote {d / 'drawing.svg'} ({(d / 'drawing.svg').stat().st_size / 1024:.0f} KB)")
    print(f"next: python figure.py label {args.name}")


# ─── labels ─────────────────────────────────────────────────────────────────


def load_labels(d):
    f = d / "labels.json"
    return json.loads(f.read_text()) if f.exists() else []


def save_labels(d, labels):
    (d / "labels.json").write_text(json.dumps(labels, indent=1))


def default_size(meta):
    return round(meta["width"] * BODY_PX / COLUMN_PX, 1)


class Metrics:
    """Advance widths from hand.woff2, to estimate how wide a label is."""

    def __init__(self):
        from fontTools.ttLib import TTFont

        font = TTFont(FONT)
        self.upm = font["head"].unitsPerEm
        self.cmap = font.getBestCmap()
        self.hmtx = font["hmtx"].metrics

    def width(self, text, size):
        em = 0.0
        for ch in text:
            g = self.cmap.get(ord(ch))
            em += self.hmtx[g][0] / self.upm * SIZE_ADJUST if g else FALLBACK_ADVANCE
        return em * size


# How far along its width a label's x sits, per "align" (SVG text-anchor).
ALIGN_SHIFT = {"start": 0.0, "middle": 0.5, "end": 1.0}


def text_box(label, metrics):
    """(x0, y0, x1, y1) of a label. x, y is on its baseline: the left end,
    the middle or the right end, as its "align" says (start by default)."""
    s = label["size"]
    w = metrics.width(label["text"], s)
    x0 = label["x"] - w * ALIGN_SHIFT[label.get("align", "start")]
    # The hand's capitals reach ~0.7em, and the size-adjust lifts that.
    return x0, label["y"] - 0.75 * s * SIZE_ADJUST, x0 + w, label["y"] + 0.1 * s


# An X mark is this fraction of the default label size across.
MARK_FRACTION = 0.6


def kind(item):
    """labels.json holds text labels, X marks, legend entries (an X followed
    by its text), and copy boxes. Entries without a kind are text.

    A copy box is invisible text laid over part of the drawing -- the text
    layer of a scanned PDF, in effect. Selecting the handwriting selects it,
    so copying an equation yields its LaTeX rather than nothing."""
    return item.get("kind", "text")


def rotate_point(px, py, ox, oy, deg):
    """SVG rotate(deg) about (ox, oy). y points down, so -90 turns text to
    read from bottom to top."""
    t = np.radians(deg)
    dx, dy = px - ox, py - oy
    return ox + dx * np.cos(t) - dy * np.sin(t), oy + dx * np.sin(t) + dy * np.cos(t)


def legend_parts(item):
    """A legend entry's X (centre, span) and where its text starts."""
    s = item["size"]
    span = s * MARK_FRACTION
    centre = (item["x"] + span / 2, item["y"] - 0.35 * s * SIZE_ADJUST)
    return centre, span, item["x"] + span + 0.4 * s


def bounds(item, metrics):
    """Axis-aligned (x0, y0, x1, y1) of any entry, rotation included."""
    k = kind(item)
    if k == "mark":
        h = item["size"] / 2
        return item["x"] - h, item["y"] - h, item["x"] + h, item["y"] + h
    if k == "copy":
        return item["x"], item["y"], item["x"] + item["w"], item["y"] + item["h"]
    if k == "legend":
        (cx, cy), span, tx = legend_parts(item)
        _, y0, x1, y1 = text_box({**item, "x": tx, "align": "start"}, metrics)
        return item["x"], min(y0, cy - span / 2), x1, max(y1, cy + span / 2)
    x0, y0, x1, y1 = text_box(item, metrics)
    deg = item.get("rotate", 0)
    if not deg:
        return x0, y0, x1, y1
    xs, ys = zip(*(rotate_point(px, py, item["x"], item["y"], deg)
                   for px in (x0, x1) for py in (y0, y1)))
    return min(xs), min(ys), max(xs), max(ys)


def leader(label, metrics):
    """The leader line: from just outside the label's box to its target."""
    tx, ty = label["target"]
    x0, y0, x1, y1 = bounds(label, metrics)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = tx - cx, ty - cy
    dist = float(np.hypot(dx, dy))
    if dist == 0:
        return None
    # Where the ray from the centre leaves the box, then a small gap beyond.
    hw, hh = (x1 - x0) / 2, (y1 - y0) / 2
    t = min(hw / abs(dx) if dx else np.inf, hh / abs(dy) if dy else np.inf)
    start = t * dist + LINE_GAP * label["size"]
    if start >= dist:
        return None
    ux, uy = dx / dist, dy / dist
    return cx + ux * start, cy + uy * start, tx, ty


# ─── render ─────────────────────────────────────────────────────────────────


def x_path(cx, cy, span):
    h = span / 2
    return (f"M{cx - h:.1f} {cy - h:.1f}L{cx + h:.1f} {cy + h:.1f}"
            f"M{cx - h:.1f} {cy + h:.1f}L{cx + h:.1f} {cy - h:.1f}")


def render(name):
    d = fig_dir(name)
    meta = json.loads((d / "meta.json").read_text())
    labels = load_labels(d)
    metrics = Metrics()
    drawing = (d / "drawing.svg").read_text()

    stroke = meta["stroke"]
    # Marks and leaders are drawn at the pen's width, so they match the ink.
    pen = f'fill="none" stroke="currentColor" stroke-width="{stroke:.1f}" stroke-linecap="round"'
    parts = ['  <g class="fig-labels">']
    for lab in labels:
        k = kind(lab)
        if k == "mark":
            parts.append(f'    <path class="fig-mark" d="{x_path(lab["x"], lab["y"], lab["size"])}" {pen}/>')
            continue
        if k == "copy":
            # Stretched to fill its box, so the selection highlight covers
            # the handwriting it stands for. Font size is the box height;
            # most of an em sits above the baseline.
            parts.append(
                f'    <text class="fig-copy" x="{lab["x"]:.1f}" y="{lab["y"] + 0.8 * lab["h"]:.1f}" '
                f'font-size="{lab["h"]:.1f}" textLength="{lab["w"]:.1f}" '
                f'lengthAdjust="spacingAndGlyphs">{html.escape(lab["text"])}</text>'
            )
            continue
        x, align = lab["x"], lab.get("align", "start")
        if k == "legend":
            (cx, cy), span, x = legend_parts(lab)
            align = "start"
            parts.append(f'    <path class="fig-mark" d="{x_path(cx, cy, span)}" {pen}/>')
        if lab.get("target"):
            seg = leader(lab, metrics)
            if seg:
                parts.append(
                    f'    <line class="fig-leader" x1="{seg[0]:.1f}" y1="{seg[1]:.1f}" '
                    f'x2="{seg[2]:.1f}" y2="{seg[3]:.1f}" stroke="currentColor" '
                    f'stroke-width="{stroke:.1f}" stroke-linecap="round"/>'
                )
        rot = lab.get("rotate", 0)
        turn = f' transform="rotate({rot} {lab["x"]:.1f} {lab["y"]:.1f})"' if rot else ""
        parts.append(
            f'    <text class="fig-label" x="{x:.1f}" y="{lab["y"]:.1f}" '
            f'font-size="{lab["size"]:.1f}" text-anchor="{align}"{turn} '
            f'fill="currentColor">{html.escape(lab["text"])}</text>'
        )
    parts.append("  </g>")

    # Text can sit outside the drawing; widen the viewBox to take it in.
    x0, y0, x1, y1 = 0.0, 0.0, float(meta["width"]), float(meta["height"])
    for lab in labels:
        bx0, by0, bx1, by1 = bounds(lab, metrics)
        x0, y0, x1, y1 = min(x0, bx0), min(y0, by0), max(x1, bx1), max(y1, by1)
    pad = stroke * 2
    box = f"{x0 - pad:.0f} {y0 - pad:.0f} {x1 - x0 + 2 * pad:.0f} {y1 - y0 + 2 * pad:.0f}"

    body = drawing.split(">", 1)[1].rsplit("</svg>", 1)[0].rstrip()
    svg = (
        f'<svg class="fig-art" xmlns="http://www.w3.org/2000/svg" viewBox="{box}" '
        f'role="img" aria-labelledby="{name}-title">\n'
        f'  <title id="{name}-title">{html.escape(", ".join(l["text"] for l in labels if kind(l) != "mark"))}</title>'
        f"{body}\n" + "\n".join(parts) + "\n</svg>\n"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{name}.svg"
    out.write_text(svg)
    return out


def cmd_render(args):
    out = render(args.name)
    print(f"wrote {out}")


# ─── the labelling window ───────────────────────────────────────────────────


HELP = (
    "n new label  ·  m place X marks (Esc ends)  ·  g new legend entry  ·  "
    "click to select, drag to move\n"
    "t set target (then click)  ·  x remove target  ·  r rotate  ·  e edit text  ·  "
    "+ / - size  ·  arrows nudge  ·  d delete  ·  s save  ·  q save + quit"
)


def cmd_label(args):
    import tempfile

    import matplotlib.pyplot as plt
    from fontTools.ttLib import TTFont
    from matplotlib.font_manager import FontProperties
    from matplotlib.widgets import TextBox

    d = fig_dir(args.name)
    if not (d / "meta.json").exists():
        raise SystemExit(f"no traced drawing in {d}; run: python figure.py trace <photo> --name {args.name}")
    meta = json.loads((d / "meta.json").read_text())
    labels = load_labels(d)
    metrics = Metrics()

    # matplotlib's FreeType may lack woff2 support; hand it a plain OTF. The
    # preview has no `calt`, so every repeat of a letter shows the same variant.
    otf = pathlib.Path(tempfile.mkdtemp()) / "hand.otf"
    font = TTFont(FONT)
    font.flavor = None
    font.save(otf)
    hand = FontProperties(fname=str(otf))

    img = np.asarray(Image.open(d / "preview.png").convert("L"))
    W, H = meta["width"], meta["height"]

    fig, ax = plt.subplots(figsize=(9, 9 * H / W + 1.2))
    plt.subplots_adjust(left=0.02, right=0.98, top=0.88, bottom=0.1)
    ax.imshow(img, cmap="gray", vmin=0, vmax=255, alpha=0.9)
    # Room around the drawing for labels that sit outside it.
    pad = 0.25 * max(W, H)
    ax.set_xlim(-pad, W + pad)
    ax.set_ylim(H + pad, -pad)
    ax.set_aspect("equal")
    ax.set_xticks([]), ax.set_yticks([])
    fig.suptitle(HELP, fontsize=8)

    box_ax = plt.axes([0.12, 0.02, 0.76, 0.045])
    textbox = TextBox(box_ax, "text ")
    state = {"sel": None, "mode": None, "drag": None, "dirty": False}
    artists = []

    # The DPI the text is drawn at is not the SVG's, so size is set in data
    # units: points per data unit at the current zoom.
    def pt_per_unit():
        bbox = ax.get_window_extent()
        x_lo, x_hi = ax.get_xlim()
        return bbox.width / (x_hi - x_lo) * 72 / fig.dpi

    def status(msg):
        ax.set_title(msg, fontsize=9, loc="left")

    def redraw():
        for a in artists:
            a.remove()
        artists.clear()
        k = pt_per_unit()
        lw = max(meta["stroke"] * k, 0.8)
        for i, lab in enumerate(labels):
            colour = "#c0392b" if i == state["sel"] else "#2e1a0e"
            kd = kind(lab)
            if kd == "copy":
                artists.append(ax.add_patch(plt.Rectangle(
                    (lab["x"], lab["y"]), lab["w"], lab["h"], fill=False, ec=colour, ls="--", lw=0.8)))
                artists.append(ax.text(lab["x"], lab["y"] - 4, "copies as: " + lab["text"],
                                       fontsize=7, color=colour, va="bottom"))
                continue
            if kd != "text":
                (cx, cy), span = ((lab["x"], lab["y"]), lab["size"]) if kd == "mark" else legend_parts(lab)[:2]
                h = span / 2
                for ys in ([cy - h, cy + h], [cy + h, cy - h]):
                    artists.extend(ax.plot([cx - h, cx + h], ys, color=colour, lw=lw,
                                           solid_capstyle="round"))
            if kd != "mark":
                tx = legend_parts(lab)[2] if kd == "legend" else lab["x"]
                align = "start" if kd == "legend" else lab.get("align", "start")
                # matplotlib turns anticlockwise for positive angles, SVG
                # clockwise, so the sign flips.
                artists.append(ax.text(
                    tx, lab["y"], lab["text"], fontproperties=hand,
                    fontsize=lab["size"] * SIZE_ADJUST * k, color=colour, va="baseline",
                    ha={"start": "left", "middle": "center", "end": "right"}[align],
                    rotation=-lab.get("rotate", 0), rotation_mode="anchor",
                ))
            x0, y0, x1, y1 = bounds(lab, metrics)
            if i == state["sel"]:
                artists.append(ax.add_patch(plt.Rectangle(
                    (x0, y0), x1 - x0, y1 - y0, fill=False, ec=colour, ls=":", lw=0.8)))
            if lab.get("target"):
                seg = leader(lab, metrics)
                if seg:
                    artists.extend(ax.plot([seg[0], seg[2]], [seg[1], seg[3]], color=colour,
                                           lw=lw, solid_capstyle="round"))
        fig.canvas.draw_idle()

    def hit(x, y):
        """Index of the label under a point, if any."""
        for i in reversed(range(len(labels))):
            x0, y0, x1, y1 = bounds(labels[i], metrics)
            m = labels[i].get("size", 20) * 0.3
            if x0 - m <= x <= x1 + m and y0 - m <= y <= y1 + m:
                return i
        return None

    def save():
        save_labels(d, labels)
        out = render(args.name)
        state["dirty"] = False
        status(f"saved {len(labels)} labels -> {out.relative_to(WEBSITE)}")
        fig.canvas.draw_idle()

    def on_submit(text):
        text = text.strip()
        if state["mode"] in ("new", "new-legend") and text:
            what = "legend" if state["mode"] == "new-legend" else "text"
            state["mode"] = ("place", text, what)
            status(f"click where '{text}' goes (its baseline starts at the click)")
        elif state["mode"] == "edit" and text and state["sel"] is not None:
            labels[state["sel"]]["text"] = text
            state["mode"], state["dirty"] = None, True
            status("text changed")
            redraw()
        fig.canvas.draw_idle()

    def on_press(event):
        if event.inaxes is not ax or event.xdata is None:
            return
        x, y = float(event.xdata), float(event.ydata)
        mode = state["mode"]
        if isinstance(mode, tuple) and mode[0] == "place":
            item = {"text": mode[1], "x": round(x, 1), "y": round(y, 1),
                    "size": default_size(meta), "target": None}
            if mode[2] == "legend":
                item["kind"] = "legend"
            labels.append(item)
            state["sel"], state["dirty"] = len(labels) - 1, True
            textbox.set_val("")
            if mode[2] == "legend":
                state["mode"] = None
                status("legend entry placed")
            else:
                state["mode"] = "target"
                status("now click the point it refers to (or press Esc for no line)")
        elif mode == "mark":
            labels.append({"kind": "mark", "x": round(x, 1), "y": round(y, 1),
                           "size": round(default_size(meta) * MARK_FRACTION, 1)})
            state["sel"], state["dirty"] = len(labels) - 1, True
            n = sum(kind(l) == "mark" for l in labels)
            status(f"{n} marks. click for another, Esc to stop")
        elif mode == "target" and state["sel"] is not None:
            labels[state["sel"]]["target"] = [round(x, 1), round(y, 1)]
            state["mode"], state["dirty"] = None, True
            status("line set")
        else:
            i = hit(x, y)
            state["sel"] = i
            if i is not None:
                state["drag"] = (x - labels[i]["x"], y - labels[i]["y"])
                status(f"selected '{labels[i].get('text', 'X mark')}'")
        redraw()

    def on_motion(event):
        if state["drag"] is None or state["sel"] is None or event.xdata is None:
            return
        ox, oy = state["drag"]
        lab = labels[state["sel"]]
        lab["x"], lab["y"] = round(event.xdata - ox, 1), round(event.ydata - oy, 1)
        state["dirty"] = True
        redraw()

    def on_release(event):
        state["drag"] = None

    def on_key(event):
        # While the text box has focus, keys belong to it.
        if textbox.capturekeystrokes:
            if event.key == "escape":
                state["mode"] = None
                textbox.stop_typing()
                status("cancelled")
                fig.canvas.draw_idle()
            return
        sel = state["sel"]
        key = event.key
        if key == "n":
            state["mode"] = "new"
            textbox.set_val("")
            textbox.begin_typing()
            status("type the label, then Enter")
        elif key == "m":
            state["mode"] = "mark"
            status("click to place an X; keep clicking for more, Esc to stop")
        elif key == "g":
            state["mode"] = "new-legend"
            textbox.set_val("")
            textbox.begin_typing()
            status("type the legend text, then Enter")
        elif key == "escape":
            state["mode"] = None
            status("")
        elif key == "s":
            save()
        elif key == "q":
            save()
            plt.close(fig)
            return
        elif sel is None:
            return
        elif key in ("t", "e", "r") and kind(labels[sel]) == "mark":
            status("marks have no text or target; drag, resize or delete them")
            fig.canvas.draw_idle()
            return
        elif key in ("t", "r", "+", "=", "-") and kind(labels[sel]) == "copy":
            status("copy boxes can be dragged, edited (e) or deleted (d)")
            fig.canvas.draw_idle()
            return
        elif key == "r" and kind(labels[sel]) != "text":
            status("only text labels rotate")
            fig.canvas.draw_idle()
            return
        elif key == "r":
            labels[sel]["rotate"] = 0 if labels[sel].get("rotate") else -90
            if not labels[sel]["rotate"]:
                del labels[sel]["rotate"]
        elif key == "t":
            state["mode"] = "target"
            status("click the point this label refers to")
        elif key == "x":
            labels[sel]["target"] = None
        elif key == "e":
            state["mode"] = "edit"
            textbox.set_val(labels[sel]["text"])
            textbox.begin_typing()
            status("edit the text, then Enter")
        elif key == "d":
            labels.pop(sel)
            state["sel"] = None
        elif key in ("+", "=", "-"):
            f = 1.1 if key in "+=" else 1 / 1.1
            labels[sel]["size"] = round(labels[sel]["size"] * f, 1)
        elif key in ("left", "right", "up", "down", "shift+left", "shift+right", "shift+up", "shift+down"):
            step = 10 if key.startswith("shift") else 1
            dx = {"left": -1, "right": 1}.get(key.split("+")[-1], 0) * step
            dy = {"up": -1, "down": 1}.get(key.split("+")[-1], 0) * step
            labels[sel]["x"] += dx
            labels[sel]["y"] += dy
        else:
            return
        state["dirty"] = True
        redraw()

    textbox.on_submit(on_submit)
    fig.canvas.mpl_connect("button_press_event", on_press)
    fig.canvas.mpl_connect("motion_notify_event", on_motion)
    fig.canvas.mpl_connect("button_release_event", on_release)
    fig.canvas.mpl_connect("key_press_event", on_key)
    fig.canvas.mpl_connect("resize_event", lambda _: redraw())
    ax.callbacks.connect("xlim_changed", lambda _: redraw())

    status(f"{len(labels)} labels. press n to add one")
    redraw()
    plt.show()
    if state["dirty"]:
        save_labels(d, labels)
        render(args.name)
    print(f"{len(labels)} labels in {d / 'labels.json'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("trace", help="photo -> drawing.svg")
    t.add_argument("photo")
    t.add_argument("--name", required=True, help="figure name, e.g. fig1")
    t.add_argument("--rotate", type=float, default=0)
    t.add_argument("--threshold", type=float, default=0.88,
                   help="ink is darker than this fraction of the local paper")
    t.add_argument("--min-area", type=int, default=40, help="drop specks smaller than this")
    t.add_argument("--margin", type=int, default=30, help="pixels kept around the ink")
    t.add_argument("--region", default=None,
                   help="x0,y0,x1,y1 in photo pixels (after EXIF rotation): only ink inside is used")
    t.add_argument("--open", type=int, default=0,
                   help="erase strokes thinner than twice this many pixels (0 keeps all)")
    t.add_argument("--join", type=int, default=30,
                   help="ink this close is one drawing; the largest drawing is kept (0 keeps all)")
    t.set_defaults(func=cmd_trace)

    lab = sub.add_parser("label", help="place labels and leader lines")
    lab.add_argument("name")
    lab.set_defaults(func=cmd_label)

    r = sub.add_parser("render", help="drawing + labels -> assets/figures/<name>.svg")
    r.add_argument("name")
    r.set_defaults(func=cmd_render)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
