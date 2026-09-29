"""Remove a figure from a page and renumber the rest, or just renumber.

    renumber.py pages/entries/kepler-earth-orbit.html --remove fig-4
    renumber.py pages/entries/kepler-earth-orbit.html          # after adding one

Figures (fig-N) and equations (eq-N) are numbered separately, in the order
they appear on the page. Each figure's id, its caption number ("fig. 3")
and every in-text reference (<a class="figref" href="#fig-3">fig. 3</a>)
change together. A reference to a removed figure can't be renumbered: its
link becomes #removed-fig-N (so it can't quietly point at the figure that
took over the number) and is reported, for the sentence to be rewritten.

The files in assets/figures and tools/figures keep their names: fig6.svg may
end up as fig. 5. Names are only names.

Standard library only.
"""

import argparse
import pathlib
import re

WEBSITE = pathlib.Path(__file__).resolve().parents[4]
FIGURE_RE = re.compile(r'<figure\b[^>]*\bid="((fig|eq)-(\d+))"')


def remove(text, fid):
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines) if re.search(rf'<figure\b[^>]*\bid="{fid}"', l)), None)
    if start is None:
        raise SystemExit(f"no <figure id=\"{fid}\">")
    end = next(i for i in range(start, len(lines)) if "</figure>" in lines[i])
    # Take one blank line with it, so the paragraphs close up.
    if end + 1 < len(lines) and not lines[end + 1].strip():
        end += 1
    del lines[start:end + 1]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("page")
    ap.add_argument("--remove", metavar="ID", help="the figure to delete, e.g. fig-4 or eq-2")
    ap.add_argument("--dry-run", action="store_true", help="print what would change, write nothing")
    args = ap.parse_args()

    page = pathlib.Path(args.page)
    if not page.exists():
        page = WEBSITE / args.page
    text = page.read_text()

    if args.remove:
        text = remove(text, args.remove)
        print(f"removed {args.remove}")

    # Old id -> new number, per series, in page order.
    mapping, counts = {}, {"fig": 0, "eq": 0}
    for m in FIGURE_RE.finditer(text):
        kind = m.group(2)
        counts[kind] += 1
        mapping[m.group(1)] = (kind, counts[kind])

    # One pass over every number at once -- ids, links, and the "fig. 3" text
    # of captions and links -- so fig-4 -> fig-3 can't collide with the old
    # fig-3 being renamed in the same run.
    orphans = []

    def renumber(m):
        kind = m.group("k1") or m.group("k2") or m.group("k3")
        n = m.group("n1") or m.group("n2") or m.group("n3")
        if f"{kind}-{n}" not in mapping:
            # A reference to a figure that's gone. Left alone it would now
            # point at whichever figure took over its number, so it is
            # marked broken instead, for the sentence to be rewritten.
            if m.group("k2"):
                orphans.append(f"{kind}-{n}")
                return f'href="#removed-{kind}-{n}"'
            return m.group(0)
        new = mapping[f"{kind}-{n}"][1]
        if m.group("k1"):
            return f'id="{kind}-{new}"'
        if m.group("k2"):
            return f'href="#{kind}-{new}"'
        return f">{kind}. {new}<"

    text = re.sub(r'id="(?P<k1>fig|eq)-(?P<n1>\d+)"'
                  r'|href="#(?P<k2>fig|eq)-(?P<n2>\d+)"'
                  r'|>(?P<k3>fig|eq)\. (?P<n3>\d+)<', renumber, text)

    changed = {old: f"{k}-{n}" for old, (k, n) in mapping.items() if old != f"{k}-{n}"}
    for old, new in changed.items():
        print(f"  {old} -> {new}")
    if not changed:
        print("  numbering already in order")

    for d in sorted(set(orphans)):
        print(f"  ! the text still refers to the removed {d}: its link is now #removed-{d}; "
              f"rewrite that sentence")

    if args.dry_run:
        print("(dry run: nothing written)")
    else:
        page.write_text(text)


if __name__ == "__main__":
    main()
