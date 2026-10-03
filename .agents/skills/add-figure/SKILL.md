---
name: add-figure
description: >
  Turn a hand-drawn figure photographed in Ruben's notebook (a DNG in
  ../website-sources/img) into a traced SVG figure on a blog page: find the drawing on the
  sheet, trace it, optionally label it, put it in its <figure> slot, and check
  it. Use when asked to "extract", "trace", "add" or "put in" a figure or
  drawing from an IMG_xxxx photo, to replace a "visual goes here" placeholder,
  or to swap a sketch for a drawn one. For handwritten equations use
  add-equation; for labelling alone use label-figure.
---

# Add a figure from a notebook photo

Run everything from `website/`. The Python tools need the figures venv:

```sh
PY=tools/figures/.venv/bin/python        # create it if missing:
# python3 -m venv tools/figures/.venv && tools/figures/.venv/bin/pip install -r tools/figures/requirements.txt
SK=.agents/skills/add-figure/scripts
```

## 1. Get the photo

The site is a submodule of Ruben's Astronomy repo, and the notebook photos
are not in it: they live beside it, in the main repo's `website-sources/img/`
(`../website-sources/img/` from here), committed there but left out of that
checkout (see the DNG note in the main repo's CLAUDE.md). If a photo isn't
there, fetch them in the main repo:

```sh
git -C .. sparse-checkout set --no-cone '/*'                       # git fetches them
# ... trace ...
git -C .. sparse-checkout set --no-cone '/*' '!*.DNG' '!*.dng'     # hide them again
```

A new photo Ruben just added belongs in `../website-sources/img/`; commit it in
the main repo, not here.

## 2. Find the drawing on the sheet

A sheet usually holds several drawings: earlier figures, an upside-down
equation at the bottom. Get each one's box in photo pixels:

```sh
$PY $SK/photo.py find IMG_5288          # boxes, top to bottom, as --region
$PY $SK/photo.py overview IMG_5288 -o /tmp/page.png    # look at the whole sheet
```

Look at the overview to match boxes to drawings. Handwriting and dotted
drawings split into several boxes; join them by hand. Boxes flagged at the
photo's edge are the table, not ink.

## 3. Trace it

Name the figure after its number on the page (`fig3`, `eq2`). Names are only
names; they don't change if figures are renumbered later.

```sh
$PY tools/figures/figure.py trace ../website-sources/img/IMG_5288.DNG --name fig6 --region X0,Y0,X1,Y1
```

Then **look at `tools/figures/<name>/preview.png`** and compare it with the
photo at full resolution, using the crop from `tools/figures/<name>/meta.json`:
`$PY $SK/photo.py crop IMG_5288 X0,Y0,X1,Y1 -o /tmp/photo.png --scale 0.5`.
Check that nothing is missing and nothing extra came along.

Flags for what goes wrong:

| Problem | Fix |
|---|---|
| Parts missing: text, dots, dashed marks | `--join 0`. By default only the largest cluster of ink is kept, which drops pieces that stand apart. |
| Specks from the page edge or shadow | keep the default `--join 30`, or tighten `--region` |
| Faint pencil guide lines leave tails on dots | `--open 4` erases strokes thinner than ~8 px and keeps solid marks |
| Light grey strokes you don't want | lower `--threshold` (0.75) so only dark ink counts |
| A drawing low on the sheet is cut off or missing | `--paper 25`: the shadowed end of the page isn't being counted as paper |

`meta.json`'s `stroke` sets how thick leader lines and X marks are drawn. It is
measured from the ink. If the drawing is mostly solid dots, or `--open` was used,
the measurement comes out too thick. Copy `stroke` from a figure traced off the
same sheet instead; the pen is the same.

## 4. Label it, or don't

- To label it, follow the **label-figure** skill. It opens a window for Ruben.
- Without labels: `$PY tools/figures/figure.py render <name>`.

Either way, `assets/figures/<name>.svg` is what the page shows.

## 5. Put it on the page

```sh
python3 $SK/place.py pages/entries/<slug>.html fig-6 fig6
```

This replaces whatever the `<figure id="fig-6">` holds (placeholder, older
SVG, coded sketch) and keeps the caption. If the page has no slot for it yet,
add a placeholder where the figure belongs:

```html
          <figure class="plate" id="fig-9">
            <div class="plate-frame"><span class="plate-mark">visual goes here</span></div>
            <figcaption><span class="plate-num">fig. 9</span> Caption.</figcaption>
          </figure>
```

Then run the **remove-figure** skill's `renumber.py` (without `--remove`) to
number it in page order.

**Read the caption against the drawing.** Several captions were written
before their drawings existed and no longer matched them. When they differ,
suggest a caption; don't change it without asking.

## 6. Check it

```sh
python3 .agents/skills/preview-page/scripts/preview.py /entries/<slug>/ --figure fig-6 --out /tmp/fig6.png
```

Look at the screenshot. Don't `trunk build` into `dist/`: Ruben usually has
`./scripts/serve.sh` running, and it rewrites `dist/` on every change.

## Commit

The photo, `tools/figures/<name>/` (drawing, preview, meta, labels),
`assets/figures/<name>.svg` and the page. After committing a new photo, hide
it again (step 1).
