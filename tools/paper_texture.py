"""Make the notebook's paper background from the paper photo.

    tools/figures/.venv/bin/python tools/paper_texture.py [--inset 100] [--width 2560] [--quality 80]

Reads assets/textures/paper-texture.jpg and writes
assets/textures/paper-mirrored.webp: the photo, less --inset pixels on every
side (its own edges and borders would show at the joins), scaled to --width, with a
vertically flipped copy beneath it. notebook.css spans it across the page
and repeats it downward; since each copy meets its own mirror image, the
repeats join without a seam all the way down. (CSS can repeat a background
but not mirror it, hence the doubled image.)

The page multiplies it over its golden parchment gradient, so it is first
levelled: each colour channel scaled so the paper's typical tone sits at
--level (just under white). Multiplied, that leaves the page's colour as it
was and adds only the photo's stains and grain, without its own cream cast
or its overall darkness.
"""

import argparse
import pathlib

import numpy as np
from PIL import Image, ImageOps

TEXTURES = pathlib.Path(__file__).resolve().parent.parent / "assets" / "textures"
SOURCE = TEXTURES / "paper-texture.jpg"
OUT = TEXTURES / "paper-mirrored.webp"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--inset", type=int, default=100, help="pixels cropped off every side of the photo first")
    ap.add_argument("--width", type=int, default=2560, help="width of the result in pixels")
    ap.add_argument("--quality", type=int, default=80, help="WebP quality (0-100)")
    ap.add_argument("--level", type=float, default=248, help="where the paper's median tone is put (0-255)")
    args = ap.parse_args()

    photo = Image.open(SOURCE).convert("RGB")
    i = args.inset
    photo = photo.crop((i, i, photo.width - i, photo.height - i))
    height = round(photo.height * args.width / photo.width)
    photo = photo.resize((args.width, height), Image.Resampling.LANCZOS)
    pixels = np.asarray(photo, dtype=np.float32)
    median = np.median(pixels.reshape(-1, 3), axis=0)
    photo = Image.fromarray(np.clip(pixels * (args.level / median), 0, 255).astype(np.uint8))
    doubled = Image.new("RGB", (args.width, height * 2))
    doubled.paste(photo, (0, 0))
    doubled.paste(ImageOps.flip(photo), (0, height))
    doubled.save(OUT, quality=args.quality, method=6)
    print(f"wrote {OUT.name}: {doubled.width}x{doubled.height}, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
