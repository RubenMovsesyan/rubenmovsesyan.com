"""Start a new blog entry in pages/entries/, optionally from an Obsidian draft.

    new_entry.py mars-orbit --title "Kepler's Mapping of Mars' Orbit" \\
        --description "..." [--date 2026] [--number 2]
    new_entry.py mars-orbit --title "..." --description "..." \\
        --from-draft "../notes/blog-drafts/Mars orbit.md"

Writes pages/entries/<slug>.html with its fields (number defaults to the
next free one, date to this year). The page is then at /entries/<slug>/ and
on the contents page at the next build.

--from-draft turns the draft's paragraphs into the entry's <p>s, following
the conventions the first entry settled on:

  {insert visual here}, {... visual ...}    -> "fig. N" link in the sentence,
                                              placeholder figure after the paragraph
  {show equation here}, {... math ...},
  {... algebra ...}                         -> the same, as "eq. N"
  {insert numbers here}                     -> a ruled blank: <span class="gap">
  [Editors Note: ...]                       -> an editor's note after the paragraph

Placeholder captions start "TODO:" with the marker's text, to be replaced
when the figure is drawn (see the add-figure and add-equation skills).

Standard library only.
"""

import argparse
import datetime
import html
import pathlib
import re

WEBSITE = pathlib.Path(__file__).resolve().parents[4]
ENTRIES = WEBSITE / "pages" / "entries"

P = " " * 10
MARKER = re.compile(r"\{([^}]*)\}")
NOTE = re.compile(r"\[\s*Editor'?s\s+Note:\s*(.*?)\]", re.I | re.S)


def kind_of(marker):
    m = marker.lower()
    if "number" in m:
        return "gap"
    if any(w in m for w in ("equation", "math", "algebra", "formula")):
        return "eq"
    return "fig"


def placeholder(kind, n, marker):
    mark = "equation goes here" if kind == "eq" else "visual goes here"
    cls = "plate plate--math" if kind == "eq" else "plate"
    return (f'{P}<figure class="{cls}" id="{kind}-{n}" data-reveal>\n'
            f'{P}  <div class="plate-frame"><span class="plate-mark">{mark}</span></div>\n'
            f'{P}  <figcaption><span class="plate-num">{kind}. {n}</span> TODO: {html.escape(marker)}</figcaption>\n'
            f'{P}</figure>')


def convert(draft):
    counts = {"fig": 0, "eq": 0}
    blocks = []
    for para in re.split(r"\n\s*\n", draft.strip()):
        para = " ".join(para.split())
        if not para:
            continue
        notes = [n.strip() for n in NOTE.findall(para)]
        para = NOTE.sub("", para)
        after = []

        def mark(text):
            k = kind_of(text)
            if k == "gap":
                return '<span class="gap">number goes here</span>'
            counts[k] += 1
            n = counts[k]
            after.append(placeholder(k, n, text))
            return f'<a class="figref" href="#{k}-{n}">{k}. {n}</a>'

        # split() alternates prose and marker text: escape the prose, turn
        # each marker into its markup.
        parts = MARKER.split(para)
        body = "".join(html.escape(part, quote=False) if i % 2 == 0 else mark(part.strip())
                       for i, part in enumerate(parts))
        body = re.sub(r"\s+([.,;:])", r"\1", body).strip()
        blocks.append(f"{P}<p>\n{P}  {body}\n{P}</p>")
        for n in notes:
            blocks.append(f'{P}<aside class="note">\n{P}  <span class="note-label">Editor\'s note</span>\n'
                          f"{P}  {html.escape(n, quote=False)}\n{P}</aside>")
        blocks += after
    return "\n\n".join(blocks), counts


def next_number():
    numbers = [int(m.group(1)) for f in ENTRIES.glob("*.html")
               if (m := re.search(r"^number:\s*(\d+)", f.read_text(), re.M))]
    return max(numbers, default=0) + 1


def roman(n):
    out = ""
    for v, s in [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                 (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]:
        while n >= v:
            out, n = out + s, n - v
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("slug", help="URL name: lowercase words joined by hyphens, e.g. mars-orbit")
    ap.add_argument("--title", required=True)
    ap.add_argument("--description", required=True, help="one sentence: the contents page and search results show it")
    ap.add_argument("--date", default=str(datetime.date.today().year))
    ap.add_argument("--number", type=int, help="entry number (default: the next free one)")
    ap.add_argument("--from-draft", metavar="MD", help="an Obsidian draft to convert")
    ap.add_argument("--out", help="write here instead of pages/entries/<slug>.html (to look first)")
    args = ap.parse_args()

    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", args.slug):
        raise SystemExit("slug: lowercase letters and digits joined by single hyphens")
    target = pathlib.Path(args.out) if args.out else ENTRIES / f"{args.slug}.html"
    if target.exists():
        raise SystemExit(f"{target} already exists")
    number = args.number or next_number()
    for field in (args.title, args.description, args.date):
        if "-->" in field:
            raise SystemExit("fields can't contain -->")

    if args.from_draft:
        body, counts = convert(pathlib.Path(args.from_draft).read_text())
        made = f"{counts['fig']} placeholder figures, {counts['eq']} placeholder equations"
    else:
        body = f"{P}<p>\n{P}  \n{P}</p>"
        made = "an empty first paragraph"

    target.write_text(f"""<!--
Entry {roman(number)} of the astronomy blog. crates/astronomy-pages wraps this in the entry
header (number, date, title), the page layout, and lists it on the contents
page. The fields below are what it uses.

title: {args.title}
description: {args.description}
number: {number}
date: {args.date}
-->

{body}
""")
    print(f"wrote {target}: entry {roman(number)}, {made}")
    print(f"it will be at /entries/{args.slug}/ and on the contents page after the next build")


if __name__ == "__main__":
    main()
