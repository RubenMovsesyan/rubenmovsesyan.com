"""Put a rendered figure into its slot on a page.

    place.py pages/entries/kepler-earth-orbit.html fig-3 fig3
    place.py pages/entries/kepler-earth-orbit.html eq-2 eq2 --scale-like eq1

Replaces whatever art the <figure id="..."> holds now -- the "visual goes
here" placeholder, an earlier traced SVG, a hand-coded sketch -- with the
inline link to assets/figures/<name>.svg, and keeps its caption. The figure
element itself (id, classes) is left as it is.

--scale-like shows it at another figure's scale instead of the full column:
equations are traced at the pen's own size, so a short one stretched to the
column would look several times larger than eq. 1. The width is the ratio of
the two SVGs' viewBox widths.

Standard library only.
"""

import argparse
import pathlib
import re
import sys

WEBSITE = pathlib.Path(__file__).resolve().parents[4]
FIGURES = WEBSITE / "assets" / "figures"
INDENT = " " * 12


def viewbox_width(name):
    svg = (FIGURES / f"{name}.svg").read_text()
    m = re.search(r'viewBox="[-\d.]+ [-\d.]+ ([\d.]+) [\d.]+"', svg)
    if not m:
        raise SystemExit(f"{name}.svg has no viewBox")
    return float(m.group(1))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("page", help="the page file, e.g. pages/entries/<slug>.html")
    ap.add_argument("id", help="the figure's id, e.g. fig-3 or eq-2")
    ap.add_argument("name", help="the figure's name in tools/figures (assets/figures/<name>.svg)")
    ap.add_argument("--scale-like", metavar="NAME", help="size to this figure's scale (equations: eq1)")
    args = ap.parse_args()

    page = pathlib.Path(args.page)
    if not page.is_absolute() and not page.exists():
        page = WEBSITE / args.page
    svg = FIGURES / f"{args.name}.svg"
    if not svg.exists():
        raise SystemExit(f"{svg} doesn't exist; render it first: figure.py render {args.name}")

    lines = page.read_text().split("\n")
    open_re = re.compile(rf'<figure\b[^>]*\bid="{re.escape(args.id)}"')
    start = next((i for i, l in enumerate(lines) if open_re.search(l)), None)
    if start is None:
        ids = re.findall(r'<figure\b[^>]*\bid="([^"]+)"', page.read_text())
        raise SystemExit(f"no <figure id=\"{args.id}\"> in {page}; figures there: {', '.join(ids)}")
    cap = next((i for i in range(start + 1, len(lines)) if "<figcaption" in lines[i]), None)
    end = next((i for i in range(start + 1, len(lines)) if "</figure>" in lines[i]), None)
    if cap is None or end is None or cap > end:
        raise SystemExit(f"{args.id}: expected a <figcaption> before </figure>")

    copies = 'class="fig-copy"' in svg.read_text()
    what = f"copies as LaTeX (tools/figures/{args.name}/labels.json)" if copies \
        else "edit labels there, not here"
    new = [f"{INDENT}<!-- Built by tools/figures/figure.py; {what}. -->"]
    style = ""
    if args.scale_like:
        mine, theirs = viewbox_width(args.name), viewbox_width(args.scale_like)
        frac = mine / theirs
        if frac > 1:
            print(f"note: {args.name} is wider than {args.scale_like}; showing it at the full column")
        else:
            new.append(f"{INDENT}<!-- Sized to {args.scale_like}'s scale ({mine:.0f} of its "
                       f"{theirs:.0f} px), so the handwriting matches. -->")
            style = f' style="width: {frac:.1%}; margin-inline: auto"'
    new.append(f'{INDENT}<div class="plate-art"{style}><link data-trunk rel="inline" '
               f'href="assets/figures/{args.name}.svg"></div>')

    # A hand-coded <figure class="sketch"> becomes a plate like the others.
    lines[start] = lines[start].replace('class="sketch"', 'class="plate"')
    lines[start + 1:cap] = new
    page.write_text("\n".join(lines))
    print(f"{page.relative_to(WEBSITE) if page.is_relative_to(WEBSITE) else page}: "
          f"{args.id} now shows {args.name}.svg" + (f" at {style.split(':')[1].split(';')[0].strip()}"
                                                     if style else ""))


if __name__ == "__main__":
    sys.exit(main())
