"""Set the baseline by hand for the letters that hang below it.

Every other glyph can be seated automatically, because its lowest point *is*
the baseline. For g, j, p, q and y that is false -- the tail drops past it --
and there is no reliable way to guess how far. So those are set by eye here.

    python align.py --seg <dir> [--variants 4] [--chars gjpqy]

Drag the slider (or use the arrow keys) until the red line sits where the
letter rests on the page, then press Next. Progress is written to
alignment.json in the segment directory as you go, so it is safe to stop and
come back. Glyphs already set are skipped unless you pass --redo.
"""

import argparse
import json
import pathlib

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.widgets import Button, Slider
from PIL import Image

import glyphset

DEFAULT_CHARS = "gjpqy"


def seed_baseline(entry):
    """A first guess: the row's baseline, expressed inside this crop."""
    y0 = entry["box"][1]
    return float(entry["baseline"]) - y0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", required=True)
    ap.add_argument("--variants", type=int, default=4)
    ap.add_argument("--chars", default=DEFAULT_CHARS)
    ap.add_argument("--redo", action="store_true", help="revisit glyphs already set")
    args = ap.parse_args()

    seg = pathlib.Path(args.seg)
    store = seg / "alignment.json"
    saved = json.loads(store.read_text()) if store.exists() else {}

    chosen = glyphset.pick(glyphset.load(seg), args.variants, seg)
    queue = [g for ch in args.chars for g in chosen.get(ch, [])]
    if not args.redo:
        queue = [g for g in queue if g["file"] not in saved]

    if not queue:
        print(f"nothing to align ({len(saved)} already set in {store}).")
        print("pass --redo to go through them again.")
        return

    print(f"{len(queue)} glyphs to align. Arrow keys nudge, Enter accepts, q quits.")

    state = {"i": 0}
    fig, ax = plt.subplots(figsize=(6.5, 7))
    plt.subplots_adjust(left=0.08, right=0.97, top=0.9, bottom=0.26)

    img_artist = ax.imshow(np.zeros((10, 10)), cmap="gray_r", vmin=0, vmax=1)
    line = ax.axhline(0, color="#d03030", lw=2)

    slider_ax = plt.axes([0.12, 0.13, 0.76, 0.035])
    slider = Slider(slider_ax, "baseline", 0, 1, valinit=0)

    prev_ax = plt.axes([0.12, 0.04, 0.16, 0.06])
    next_ax = plt.axes([0.32, 0.04, 0.16, 0.06])
    skip_ax = plt.axes([0.52, 0.04, 0.16, 0.06])
    done_ax = plt.axes([0.72, 0.04, 0.16, 0.06])
    b_prev, b_next = Button(prev_ax, "< Prev"), Button(next_ax, "Next >")
    b_skip, b_done = Button(skip_ax, "Skip"), Button(done_ax, "Save + Quit")

    def persist():
        store.write_text(json.dumps(saved, indent=1))

    def show():
        g = queue[state["i"]]
        arr = np.asarray(Image.open(seg / "glyphs" / g["file"]).convert("L"))
        ink = 1.0 - arr / 255.0
        h = ink.shape[0]

        img_artist.set_data(ink)
        img_artist.set_extent([0, ink.shape[1], h, 0])
        ax.set_xlim(0, ink.shape[1])
        ax.set_ylim(h, 0)

        value = saved.get(g["file"], seed_baseline(g))
        value = float(np.clip(value, 0, h))

        slider.valmin, slider.valmax = 0, h
        slider.ax.set_xlim(0, h)
        slider.set_val(value)
        line.set_ydata([value, value])

        ax.set_title(
            f"[{state['i']+1}/{len(queue)}]  '{g['char']}'   {g['file']}\n"
            f"put the red line where the letter sits on the page",
            fontsize=10,
        )
        fig.canvas.draw_idle()

    def on_slide(v):
        line.set_ydata([v, v])
        saved[queue[state["i"]]["file"]] = float(v)
        fig.canvas.draw_idle()

    def step(delta):
        saved[queue[state["i"]]["file"]] = float(slider.val)
        persist()
        state["i"] = (state["i"] + delta) % len(queue)
        show()

    def on_key(event):
        if event.key in ("right", "enter"):
            step(1)
        elif event.key == "left":
            step(-1)
        elif event.key in ("up", "down"):
            slider.set_val(np.clip(slider.val + (-1 if event.key == "up" else 1), slider.valmin, slider.valmax))
        elif event.key in ("shift+up", "shift+down"):
            slider.set_val(np.clip(slider.val + (-10 if event.key == "shift+up" else 10), slider.valmin, slider.valmax))
        elif event.key == "q":
            persist()
            plt.close(fig)

    slider.on_changed(on_slide)
    b_next.on_clicked(lambda _: step(1))
    b_prev.on_clicked(lambda _: step(-1))
    b_skip.on_clicked(lambda _: (saved.pop(queue[state["i"]]["file"], None), step(1)))
    b_done.on_clicked(lambda _: (persist(), plt.close(fig)))
    fig.canvas.mpl_connect("key_press_event", on_key)

    show()
    plt.show()
    persist()
    print(f"saved {len(saved)} baselines -> {store}")


if __name__ == "__main__":
    main()
