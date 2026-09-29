---
name: remove-figure
description: >
  Remove a figure or equation from a blog page and renumber the rest, or
  renumber after adding one: ids, caption numbers ("fig. 3") and in-text
  links move together, and links to a removed figure are flagged. Use when
  asked to "get rid of", "remove" or "drop" fig./eq. N, when a figure doesn't
  suit the notebook style, or when numbering is out of order after an insert.
---

# Remove a figure and renumber

Run from `website/`:

```sh
python3 .agents/skills/remove-figure/scripts/renumber.py pages/entries/<slug>.html --remove fig-5
python3 .agents/skills/remove-figure/scripts/renumber.py pages/entries/<slug>.html   # renumber only
```

Add `--dry-run` to see the changes first.

Figures (`fig-N`) and equations (`eq-N`) are separate series, numbered in
page order. The script prints each renaming (`fig-6 -> fig-5`).

**If it reports a reference to the removed figure,** the text still pointed at
it. Its link is now `#removed-fig-N`, so it can't quietly point at whichever
figure took over the number. Rewrite or delete that part of the sentence.
Show Ruben the sentence; it's his prose.

Asset names stay the same: `fig6.svg` can end up as fig. 5.

## Check

1. The blog draft in `notes/blog-drafts/` may still refer to the figure (a
   `{insert … visual …}` marker). Mention that; the draft is Ruben's.
2. Check the page with the preview-page skill.
