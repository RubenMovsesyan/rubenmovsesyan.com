---
name: add-equation
description: >
  Put a handwritten equation from a notebook photo on a blog page as traced
  handwriting that copies as LaTeX: selecting it copies $$...$$ that pastes
  as an equation on sites that render maths. Sized to match eq. 1's
  handwriting. Use when asked to add, extract or put in an equation ("eq. N")
  from an IMG_xxxx photo, or to fix what an equation copies as.
---

# Add an equation

Run from `website/`, with `PY=tools/figures/.venv/bin/python`. This follows
the add-figure skill for the photo and tracing steps, with these differences.

## 1. Find and trace it

```sh
$PY .agents/skills/add-figure/scripts/photo.py find IMG_5287
$PY tools/figures/figure.py trace assets/img/IMG_5287.DNG --name eq3 --region X0,Y0,X1,Y1 --join 0
```

- **Always `--join 0`:** handwriting is many separate pieces of ink, and the
  default keeps only the biggest.
- **Which lines to take:** a new photo is often the previous sheet plus new
  lines. Compare it with the earlier photo and take only what's new. Earlier
  lines are earlier equations.
- **Check the trace:** look at `tools/figures/<name>/preview.png`.

## 2. Read the maths

Transcribe each written line into LaTeX from the photo at full resolution
(`photo.py crop`). Then **check that it's correct**: derive it, or check it
against the equation before it. For example, eq. 3's k₁ = 2x_c follows from
expanding eq. 2. Report the check. If something is wrong, tell Ruben; don't
fix his maths quietly.

Where the handwriting is ambiguous (k or K, a subscript or not), make the
sensible choice and say which you chose.

## 3. Make it copyable

One copy box per written line, top to bottom:

```sh
$PY .agents/skills/add-equation/scripts/copy_boxes.py eq3 \
  'x^2 + y^2 = k_1 x + k_2 y + k_3' \
  'A = \begin{bmatrix} x_1 & y_1 & 1 \\ x_2 & y_2 & 1 \\ x_3 & y_3 & 1 \end{bmatrix}, \quad k = A^{-1} B'
```

It splits the trace at the widest blank rows, writes the boxes into
`labels.json`, wraps each string in `$$…$$`, and renders.

- **Side-by-side parts on one line:** use `--columns`.
- **Lines that touch:** when there's no blank row between them (eq. 1's
  definitions sit right above the equation), write the boxes into
  `labels.json` by hand as `{"kind": "copy", "text", "x", "y", "w", "h"}` in
  preview pixels.
- **Definitions:** prose with symbols, like `$T_M$ = Orbital period of Mars`,
  gets single `$`.

The copy text is invisible: `.fig-copy` is set in `assets/fonts/blank.woff2`, a
font with no visible glyphs. A transparent fill alone isn't enough, because
Chrome paints selected text regardless. Don't change that CSS.

## 4. Put it on the page, at eq. 1's scale

```sh
python3 .agents/skills/add-figure/scripts/place.py pages/entries/<slug>.html eq-3 eq3 --scale-like eq1
```

Every equation is written with the same pen at the same camera distance. At
eq. 1's scale the handwriting matches; stretched to the column, a short
equation looks several times larger. The width is recorded in the page as a
percentage, so if eq. 1 is ever re-traced, re-place the others.

## 5. Check the copy text

```sh
python3 .agents/skills/preview-page/scripts/preview.py /entries/<slug>/ --figure eq-3 --copy eq-3 --out /tmp/eq3.png
```

The printed copy text must be exactly the LaTeX. The DOM shows `&` in
matrices as `&amp;`, but the text a reader copies has a plain `&`.
