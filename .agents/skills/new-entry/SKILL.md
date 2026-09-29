---
name: new-entry
description: >
  Start a new entry on the astronomy blog: a page in pages/entries/ that
  appears on the contents page automatically, optionally converted from an
  Obsidian draft in notes/blog-drafts/ with placeholders where the draft asks
  for visuals and equations. Use when asked to create a new post, entry or
  blog page, or to put a draft on the site.
---

# Start a new entry

Run from `website/`.

## How the site is put together

- **`layout.html`:** the shell every page shares (sky, telescope, notebook).
  Trunk builds only this file.
- **`crates/astronomy-pages`:** trunk's post_build hook. It fills the layout
  with each page in `pages/`, builds each entry's header (number, date, title)
  and lists the entries on the contents page (`pages/index.html` → `/`).
- **An entry:** `pages/entries/<slug>.html`, served at `/entries/<slug>/`.
  It is content only, after an opening comment of fields:

```html
<!--
title: Kepler's Mapping of Earth's Orbit
description: One sentence; shown on the contents page and in search results.
number: 1
date: 2026
-->
```

## Create it

```sh
python3 .agents/skills/new-entry/scripts/new_entry.py mars-orbit \
  --title "Kepler's Mapping of Mars' Orbit" --description "..." \
  --from-draft "../notes/blog-drafts/<draft>.md"
```

`--out /tmp/x.html` writes it elsewhere so you can look first. The number
defaults to the next free one, and the date to this year.

**Ask Ruben for the title and the description if he hasn't given them.**
They're his words, and the description is public. The slug is lowercase
words joined by hyphens.

With `--from-draft`, the draft's paragraphs become `<p>`s. Its markers follow
the conventions of the first entry:

| Draft says | Becomes |
|---|---|
| `{insert visual here}` (any marker mentioning a visual) | an in-text "fig. N" link, and a placeholder figure after the paragraph |
| a marker mentioning an equation, maths or algebra | the same, as "eq. N" |
| `{insert numbers here}` | `<span class="gap">`, a dashed blank still to fill |
| `[Editors Note: …]` | an editor's note box after the paragraph |

Placeholder captions read `TODO: <marker>`. Write real captions once you know
what each figure shows; the first entry's captions are the model.

## Then

1. Read the converted page against the draft. Paragraph breaks and wording
   must match the draft; the converter only restructures. Fix anything it
   misread.
2. Fill in the figures with the add-figure and add-equation skills, and
   remove any that don't suit the notebook with the remove-figure skill.
3. Check the contents page and the entry with the preview-page skill.
