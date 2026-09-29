---
name: label-figure
description: >
  Label a traced figure for the blog: text labels in Ruben's handwriting font
  with leader lines to what they point at, X marks, legend entries, rotated
  axis titles, tick labels. Opens figure.py's labelling window for Ruben, or
  writes labels directly for mechanical ones like axis ticks. Use when asked
  to "label", "run through the labeler", "add labels/marks/a legend" to a
  figure, or to relabel an existing one.
---

# Label a figure

Run from `website/`. The figure must already be traced
(`tools/figures/<name>/drawing.svg`, via add-figure).

## Open the window for Ruben

Start it in the background and wait for it to close. **Don't poll**: you're
notified when it exits.

```sh
MPLBACKEND=QtAgg tools/figures/.venv/bin/python tools/figures/figure.py label <name> 2>&1 \
  | grep -v "missing from font\|plt.show()\|draw_idle"
```

(The system Python has no Tk, so the venv has PyQt6 and needs `MPLBACKEND=QtAgg`.)
Tell Ruben the keys and what you suggest labelling, then stop:

| Key | Does |
|---|---|
| **n** | new label: type it, Enter, click where it goes, then click what it points at (Esc for no line) |
| click / drag | select / move a label |
| **t** / **x** | set / remove the selected label's target (the leader line) |
| **m** | place X marks: each click drops one, Esc ends |
| **g** | legend entry: an X followed by text |
| **r** | rotate the selected label to read bottom to top (y-axis titles) |
| **e** · **+ / -** · arrows · **d** | edit text · resize · nudge (Shift: 10 px) · delete |
| **s** · **q** | save · save and quit |

Saving writes `tools/figures/<name>/labels.json` and re-renders
`assets/figures/<name>.svg`.

The preview can't show digits and punctuation, which fall back to Kalam on the
site, and shows every repeat of a letter the same, because the handwriting
font's alternates only appear in the browser. Tell Ruben so he doesn't
fight it.

## When it closes

1. Read `labels.json` and list what was placed.
2. **Check that the labels are right.** For example, perihelion must be the end
   of the line of apsides nearest the Sun, and a year axis must agree with the
   data. Accuracy matters on this blog; say so if something is off.
3. Put the figure on the page, or rebuild if it's already there, then check it
   with the preview-page skill.
4. **Leader lines:** a label placed right beside its target leaves only a stub
   after the gap before the text. The stub reads as a mark on the drawing
   (this happened on fig. 4). If you see stubs, suggest dragging the label
   further out, or pressing **x** to drop the line.

## Writing labels directly

For mechanical labels (tick values, axis titles), write the entries into
`labels.json` yourself, then run `figure.py render <name>`. Coordinates are
in `preview.png` pixels, and `y` is the text baseline.

```json
{"text": "2004", "x": 380.8, "y": 878.9, "size": 41.5, "align": "middle", "target": null}
{"text": "Angle between the Sun and Mars", "x": -60, "y": 426, "size": 41.5, "align": "middle", "rotate": -90, "target": null}
{"kind": "mark", "x": 209.4, "y": 59.2, "size": 25}
{"kind": "legend", "text": "Opposition", "x": 1100, "y": -22, "size": 41.5, "target": null}
```

- **`align`:** `start`, `middle` or `end`.
- **`rotate`:** `-90` reads bottom to top.
- **Outside the drawing:** labels can sit there (negative coordinates); the SVG grows to fit them.
- **Size:** the default is about 17 px on screen. Tick labels look right at that size, not smaller.

To find where tick marks are, measure `preview.png` (numpy: the axis row has
the most ink; the notches are ink just past it). When hand-drawn ticks and
the data disagree, fit the data to what the drawing shows. For fig. 2, year
labels went where a fit of the X marks to the real opposition dates put each
year, and the caption says "not to scale".
