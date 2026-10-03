---
name: preview-page
description: >
  Build the astronomy blog into a scratch directory and look at it in
  headless Chromium: screenshot a page or one figure, or print what selecting
  a figure copies. Use to check any change to the site (a new figure,
  labels, captions, an entry, CSS) before reporting it done, or when asked
  to preview, screenshot or verify a page.
---

# Preview a page

Run from `website/`:

```sh
P=.agents/skills/preview-page/scripts/preview.py
python3 $P                                                   # contents page, top
python3 $P /entries/<slug>/ --figure fig-3 --out /tmp/f3.png  # one figure
python3 $P /entries/<slug>/ --copy eq-2                       # what selecting eq. 2 copies
python3 $P /entries/<slug>/ --figure eq-1 --work /tmp/pv --no-build   # reuse the last build
```

Then **read the screenshot**. Output from the command alone isn't a check.

## Why it works this way

- **Scratch directory, not `dist/`:** Ruben usually has `./scripts/serve.sh`
  running, and it rewrites `dist/` whenever a file changes. A build into
  `dist/` races it and can leave `dist/` empty. For the same reason, don't put
  test files in `dist/`.
- **Telescope entrance switched off:** it slides in on load, so a screenshot
  could catch it mid-slide.
- **Figure shots shift the page, not the scroll:** headless Chromium takes
  screenshots from the top of the page whatever a script scrolls to, and
  doesn't animate smooth scrolling. So nothing here relies on scrolling.
- **`--copy` selects only the figure's art,** not the caption.

## Other checks

- **Several pages at once:** to check links or several elements, write a small
  probe script into a copy of the built page (the way `preview.py` does) and
  read it back with `chromium --headless=new --dump-dom`. Chromium serialises
  boolean attributes as `hidden=""`.
- **Killing the test server:** use its PID (`kill $P`), never `pkill -f` with a
  pattern. The pattern also matches the shell running the command, and kills it.
