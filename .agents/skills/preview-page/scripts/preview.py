"""See a page of the blog the way a reader will, without touching dist/.

    preview.py                                         # the contents page, top
    preview.py /entries/kepler-earth-orbit/ --figure fig-3
    preview.py /entries/kepler-earth-orbit/ --copy eq-2   # what selecting it copies
    preview.py /entries/kepler-earth-orbit/ --figure eq-1 --copy eq-1 --no-build

Builds the site with trunk into a scratch directory (a `trunk serve` may be
running on dist/, and a build there would race it), serves that directory
on a free port, and drives headless Chromium:

  --figure ID  scrolls that figure into view and screenshots it
  --copy ID    selects that figure's art (or the whole element, if it isn't
               a figure) and prints what a reader copying it would get --
               the LaTeX of an equation, for one

Fade-ins and the telescope's entrance are switched off first, so a figure is
never caught half-faded. Headless Chromium doesn't animate smooth scrolling,
so nothing here depends on it.

Standard library only; needs trunk and chromium (or google-chrome).
"""

import argparse
import html as html_lib
import json
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

WEBSITE = pathlib.Path(__file__).resolve().parents[4]

STILL = """<style>
  html { scroll-behavior: auto !important; }
  [data-reveal], .telescope { opacity: 1 !important; transform: none !important;
                              transition: none !important; animation: none !important; }
</style>"""

PROBE = """<pre id="__probe" hidden></pre><script>
document.fonts.ready.then(() => setTimeout(() => {
  const out = {height: document.documentElement.scrollHeight};
  const fig = %(figure)s && document.getElementById(%(figure)s);
  if (fig) {
    const r = fig.getBoundingClientRect();
    out.figure = {top: r.top + scrollY, height: r.height};
  }
  const el = %(copy)s && document.getElementById(%(copy)s);
  // A figure's art only, not its caption: that is what the check is for.
  const sel = el && (el.querySelector(".plate-art") || el);
  if (sel) {
    const range = document.createRange();
    range.selectNodeContents(sel);
    getSelection().removeAllRanges();
    getSelection().addRange(range);
    out.copy = getSelection().toString();
  }
  document.getElementById("__probe").textContent = JSON.stringify(out);
}, 300));
</script>"""


SHIFT = """<script>
document.fonts.ready.then(() => setTimeout(() => {
  const r = document.getElementById(%(figure)s).getBoundingClientRect();
  document.body.style.transform = `translateY(${-Math.max(0, r.top + scrollY - 40)}px)`;
}, 300));
</script>"""


def chromium():
    for name in ("chromium", "chromium-browser", "google-chrome-stable", "google-chrome"):
        if shutil.which(name):
            return name
    raise SystemExit("no chromium or google-chrome on PATH")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("page", nargs="?", default="/", help="URL path, e.g. /entries/<slug>/")
    ap.add_argument("--figure", metavar="ID", help="screenshot this figure (fig-3, eq-1)")
    ap.add_argument("--copy", metavar="ID", help="print what selecting this element copies")
    ap.add_argument("--out", help="screenshot path (default: <work>/preview.png)")
    ap.add_argument("--width", type=int, default=900)
    ap.add_argument("--height", type=int, default=1400, help="window height for a whole-page shot")
    ap.add_argument("--work", help="scratch directory (default: a new temp dir)")
    ap.add_argument("--no-build", action="store_true", help="reuse <work>/site from an earlier run")
    args = ap.parse_args()

    work = pathlib.Path(args.work or tempfile.mkdtemp(prefix="astro-preview-"))
    site = work / "site"
    if not args.no_build:
        shutil.rmtree(site, ignore_errors=True)
        build = subprocess.run(["trunk", "build", "--dist", str(site)], cwd=WEBSITE,
                               capture_output=True, text=True)
        if build.returncode != 0:
            sys.stderr.write(build.stdout[-3000:] + build.stderr[-3000:])
            raise SystemExit("trunk build failed")
    page_dir = site / args.page.strip("/")
    source = page_dir / "index.html"
    if not source.exists():
        pages = sorted("/" + str(p.parent.relative_to(site)).replace(".", "") for p in site.rglob("index.html"))
        raise SystemExit(f"no page at {args.page}; pages: {', '.join(p if p.endswith('/') else p + '/' for p in pages)}")

    html = source.read_text()
    html = html.replace("</head>", STILL + "</head>", 1)
    html = html.replace("</body>", PROBE % {"figure": json.dumps(args.figure),
                                            "copy": json.dumps(args.copy)} + "</body>", 1)
    probe_file = page_dir / "__preview.html"
    shot_file = page_dir / "__shot.html"
    probe_file.write_text(html)

    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
                               "--directory", str(site)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url = f"http://127.0.0.1:{port}/{args.page.strip('/')}/__preview.html".replace("//__", "/__")
        for _ in range(50):
            try:
                urllib.request.urlopen(url, timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        browser = chromium()
        common = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--virtual-time-budget=8000"]

        dom = subprocess.run(common + [f"--window-size={args.width},{args.height}", "--dump-dom", url],
                             capture_output=True, text=True).stdout
        # Chromium serialises the attribute as hidden="", so match up to the id.
        start = dom.find('<pre id="__probe"')
        raw = dom[start:].split(">", 1)[1].split("</pre>", 1)[0] if start >= 0 else ""
        result = json.loads(html_lib.unescape(raw)) if raw else {}
        if args.figure and "figure" not in result:
            raise SystemExit(f"no element with id {args.figure} on {args.page}")
        if args.copy and "copy" not in result:
            raise SystemExit(f"no element with id {args.copy} on {args.page}")

        height, shot_url = args.height, url
        if args.figure:
            # Headless screenshots are taken from the top of the page whatever
            # a script scrolls to, so the page is shifted up to the figure
            # instead. It is measured in the screenshot's own window: the sky
            # above the notebook is sized to the window, so the figure's
            # distance down the page depends on it. A transform leaves the
            # layout itself alone.
            height = max(400, int(result["figure"]["height"]) + 100)
            shift = SHIFT % {"figure": json.dumps(args.figure)}
            shot_file.write_text(html.replace("</body>", shift + "</body>", 1))
            shot_url = url.replace("__preview.html", "__shot.html")
        out = pathlib.Path(args.out) if args.out else work / "preview.png"
        subprocess.run(common + [f"--window-size={args.width},{height}", f"--screenshot={out}", shot_url],
                       capture_output=True)
        print(f"screenshot: {out}")
        if "figure" in result:
            print(f"{args.figure}: {result['figure']['height']:.0f}px tall, "
                  f"{result['figure']['top']:.0f}px down a {result['height']}px page")
        if "copy" in result:
            print(f"selecting {args.copy} copies:\n{result['copy']}")
        print(f"built site kept in {site} (pass --work {work} --no-build to reuse it)")
    finally:
        server.terminate()
        probe_file.unlink(missing_ok=True)
        shot_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
