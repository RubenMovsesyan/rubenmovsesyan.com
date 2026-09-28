"""Build assets/fonts/blank.woff2: a font whose every glyph is empty.

The copy boxes in figure.py are invisible text over the handwriting. A
transparent fill is not enough: Chrome paints selected text in the selection
colour whatever its fill, so highlighting an equation showed the LaTeX behind
it. Set in this font there is nothing to paint, but the text still selects
and copies. It covers Basic Latin through Latin Extended-B plus the Greek
block, which is everything a label or equation's LaTeX is written in.

    python blank_font.py
"""

import pathlib

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen

OUT = pathlib.Path(__file__).parent.parent.parent / "assets" / "fonts" / "blank.woff2"
RANGES = [(0x20, 0x24F), (0x370, 0x3FF)]


def main():
    # CFF outlines: OTS rejects a TrueType font whose glyf table is empty,
    # but takes empty CFF charstrings (hand.woff2's space is one).
    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder([".notdef", "blank"])
    # Every codepoint maps to the one empty glyph.
    fb.setupCharacterMap({cp: "blank" for lo, hi in RANGES for cp in range(lo, hi + 1)})
    fb.setupCFF("CopyBlank", {"FullName": "Copy Blank"},
                {g: T2CharStringPen(500, None).getCharString() for g in (".notdef", "blank")}, {})
    fb.setupHorizontalMetrics({".notdef": (500, 0), "blank": (500, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Copy Blank", "styleName": "Regular", "psName": "CopyBlank"})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    fb.setupPost()
    fb.font.flavor = "woff2"
    fb.save(str(OUT))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
