"""Placeholder for fig. 2: Sun-Mars angular separation over time, with the
detected oppositions marked. A reference to draw the real figure from; it is
the same plot as section 1 of experiments/reports/ephemeris_triangulation_
multi_bruteforce.html, from the same data and the same opposition detection.

    python fig2_placeholder.py        # -> tools/figures/fig2/reference.svg
"""

import ast
import csv
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent.parent.parent
DATA = ROOT / "experiments/data/derived/mars/ephemeris_mars_sun_sanitized.csv"
TOOL = ROOT / "experiments/tools/ephemeris_triangulation_multi_bruteforce.py"
# Written beside the figure, not over assets/figures/fig2.svg, which is now
# the hand-drawn version.
OUT = HERE / "fig2" / "reference.svg"

INK = "#2e1a0e"
JD_2000 = 2451544.5  # 2000 January 1, 0h


def find_oppositions():
    """The research tool's own find_oppositions, so the markers can't drift
    from it. Taken from its source because importing the tool pulls in plotly
    and runs nothing we need."""
    tree = ast.parse(TOOL.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "find_oppositions")
    ns = {}
    exec(compile(ast.Module([fn], []), str(TOOL), "exec"), ns)
    return ns["find_oppositions"]


def main():
    rows = list(csv.DictReader(DATA.open()))
    opps = find_oppositions()(rows)
    jd = [float(r["JulianDate"]) for r in rows]
    sep = [float(r["AngularSeparation"]) for r in rows]

    plt.rcParams.update({
        "svg.fonttype": "path", "font.size": 11, "text.color": INK,
        "axes.edgecolor": INK, "axes.labelcolor": INK,
        "xtick.color": INK, "ytick.color": INK,
    })
    fig, ax = plt.subplots(figsize=(8, 4))

    def year(j):
        # Decimal year; 365.25-day years are within a day of the calendar here.
        return 2000 + (j - JD_2000) / 365.25

    # Days with no row (Mars too close to the Sun to see) are left as gaps
    # rather than joined across.
    segs, cur = [], [(year(jd[0]), sep[0])]
    for a, b, s in zip(jd, jd[1:], sep[1:]):
        if b - a > 1.5:
            segs.append(cur)
            cur = []
        cur.append((year(b), s))
    segs.append(cur)
    for s in segs:
        ax.plot(*zip(*s), color=INK, lw=1)

    ax.plot([year(o[0]) for o in opps], [o[1] for o in opps], "o", color="#a0301c", ms=5)
    # Name the dots once, on the first, instead of a legend.
    ax.annotate("opposition", (year(opps[0][0]), opps[0][1]), xytext=(3, 6),
                textcoords="offset points", ha="right", va="bottom", fontsize=9, color=INK)
    # The gaps the text quotes ("764 to 810 days").
    for (a, _), (b, _) in zip(opps, opps[1:]):
        ax.annotate(f"{b - a:.0f} d", ((year(a) + year(b)) / 2, 186), ha="center", fontsize=8, color=INK)

    ax.set_ylabel("Angle between the Sun and Mars")
    ax.set_ylim(0, 195)
    ax.set_yticks([0, 90, 180], ["0°", "90°", "180°"])
    ax.set_xlim(1999.6, 2022.9)
    ax.set_xticks(range(2000, 2023, 2))
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)

    fig.tight_layout()
    fig.savefig(OUT, transparent=True)
    gaps = [b[0] - a[0] for a, b in zip(opps, opps[1:])]
    print(f"{len(opps)} oppositions, gaps {[round(g) for g in gaps]}, "
          f"mean {sum(gaps) / len(gaps):.1f} d -> {OUT}")


if __name__ == "__main__":
    main()
