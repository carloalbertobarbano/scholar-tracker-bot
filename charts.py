"""Summary cards sent to Telegram as PNGs.

Three cards, each a rounded panel on a darker canvas:
  1. Overview: hero total, year-end forecast, stat tiles, total-citations chart
  2. Fastest-growing papers: one row per paper with a sparkline (small multiples)
  3. Citation pace: ranked bars on tracks

Every chart uses a single accent hue; papers are identified by their row and
label, never by color. Marks follow a fixed spec: 2px lines, >=8px markers
with a 2px surface ring, solid hairline grid, 4px rounded bar ends, dashed
projections with a soft wash for the 80% range. Rendered at 2x (200 dpi
against a 100 px/inch layout), so 1 layout px = 0.72 pt.
"""
import datetime as dt

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import to_rgb  # noqa: E402
from matplotlib.patches import FancyBboxPatch, PathPatch  # noqa: E402
from matplotlib.path import Path  # noqa: E402

THEMES = {
    "dark": {
        "canvas": "#0d0d0d", "card": "#1a1a19", "raised": "#222221",
        "border": (1, 1, 1, 0.10), "ink": "#f0efec", "ink2": "#c3c2b7",
        "muted": "#898781", "grid": "#2c2c2a", "axis": "#383835",
        "track": "#262625", "accent": "#3987e5", "good": "#0ca30c",
    },
    "light": {
        "canvas": "#f9f9f7", "card": "#fcfcfb", "raised": "#f3f2ee",
        "border": (11 / 255, 11 / 255, 11 / 255, 0.10), "ink": "#0b0b0b", "ink2": "#52514e",
        "muted": "#898781", "grid": "#e1e0d9", "axis": "#c3c2b7",
        "track": "#eeede8", "accent": "#2a78d6", "good": "#006300",
    },
}

DPI = 200
PX = 0.72            # points per layout px
INCH_PX = 100        # layout px per inch
WIDTH = 8.0          # inches -> 1600 px wide
DASH = (0, (3, 2))
TREND = {"up": ("↗", "accelerating"), "flat": ("→", "steady"),
         "down": ("↘", "slowing"), None: ("", "too early to tell")}

plt.rcParams.update({
    "font.family": ["Lato", "DejaVu Sans"],   # DejaVu fills glyphs Lato lacks (arrows)
    "font.size": 10,
    "axes.unicode_minus": False,
})


def short(title, n):
    title = " ".join(title.split())
    return title if len(title) <= n else title[: n - 1].rstrip(" ,:;-") + "…"


# --- building blocks -------------------------------------------------------

class Card:
    """A figure with a rounded card panel. Positions are in inches from the top-left."""

    def __init__(self, t, height):
        self.t, self.h = t, height
        self.fig = plt.figure(figsize=(WIDTH, height), dpi=DPI, facecolor=t["canvas"])
        m = 0.16
        self.fig.add_artist(FancyBboxPatch(
            (m / WIDTH, m / height), 1 - 2 * m / WIDTH, 1 - 2 * m / height,
            boxstyle=f"round,pad=0,rounding_size={0.16 / WIDTH}",
            transform=self.fig.transFigure, facecolor=t["card"],
            edgecolor=t["border"], linewidth=1 * PX, zorder=0,
            mutation_aspect=WIDTH / height))

    def xy(self, x_in, y_in):
        return x_in / WIDTH, 1 - y_in / self.h

    def text(self, x_in, y_in, s, size=10, color=None, weight="normal", **kw):
        kw.setdefault("va", "baseline")
        return self.fig.text(*self.xy(x_in, y_in), s, fontsize=size, fontweight=weight,
                             color=color or self.t["ink"], **kw)

    def box(self, x_in, y_in, w_in, h_in, color, radius=0.08):
        x, y = self.xy(x_in, y_in + h_in)
        self.fig.add_artist(FancyBboxPatch(
            (x, y), w_in / WIDTH, h_in / self.h,
            boxstyle=f"round,pad=0,rounding_size={radius / WIDTH}",
            transform=self.fig.transFigure, facecolor=color, edgecolor="none",
            mutation_aspect=WIDTH / self.h, zorder=1))

    def hline(self, x0_in, x1_in, y_in):
        (x0, y), (x1, _) = self.xy(x0_in, y_in), self.xy(x1_in, y_in)
        self.fig.add_artist(plt.Line2D([x0, x1], [y, y], transform=self.fig.transFigure,
                                       color=self.t["grid"], linewidth=1 * PX))

    def axes(self, x_in, y_in, w_in, h_in):
        ax = self.fig.add_axes([x_in / WIDTH, 1 - (y_in + h_in) / self.h, w_in / WIDTH, h_in / self.h])
        ax.set_facecolor("none")
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(length=0, colors=self.t["muted"], labelcolor=self.t["muted"], labelsize=9)
        ax.set_axisbelow(True)
        return ax

    def header(self, title, subtitle, date):
        self.text(0.5, 0.62, title, size=17, weight="bold")
        self.text(WIDTH - 0.5, 0.62, f"{date:%d %b %Y}", size=9.5, color=self.t["muted"], ha="right")
        if subtitle:
            self.text(0.5, 0.92, subtitle, size=10, color=self.t["ink2"])

    def save(self, path):
        self.fig.savefig(path, dpi=DPI, facecolor=self.t["canvas"])
        plt.close(self.fig)
        return path


def _text_width(card, artist):
    card.fig.canvas.draw()
    bb = artist.get_window_extent()
    return bb.width / DPI


def _gradient_fill(ax, x, y, color, floor, top_alpha=0.30):
    """Area under a line, fading from `top_alpha` at the line to 0 at `floor`."""
    xn = mdates.date2num(x) if isinstance(x[0], dt.date) else np.asarray(x, float)
    poly = ax.fill_between(xn, y, floor, facecolor="none", edgecolor="none")
    grad = np.zeros((256, 1, 4))
    grad[..., :3] = to_rgb(color)
    grad[..., 3] = np.linspace(0, top_alpha, 256)[:, None] ** 1.4 / top_alpha ** 0.4
    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    im = ax.imshow(grad, aspect="auto", origin="lower", zorder=1, interpolation="bicubic",
                   extent=[xn.min(), xn.max(), floor, max(y)])
    im.set_clip_path(poly.get_paths()[0], transform=ax.transData)
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)


def _dot(ax, x, y, t, hollow=False, halo=False):
    c = t["accent"]
    if halo:
        ax.plot([x], [y], marker="o", markersize=20 * PX, color=c, alpha=0.22,
                linestyle="none", zorder=5, clip_on=False)
    ax.plot([x], [y], marker="o", markersize=9 * PX, linestyle="none", zorder=6,
            markerfacecolor=t["card"] if hollow else c,
            markeredgecolor=c if hollow else t["card"], markeredgewidth=2 * PX,
            clip_on=False)


def _rounded_bar(ax, y, length, thickness, color, r_frac=0.5):
    """Horizontal bar, square at the baseline, rounded data-end (call after limits are set)."""
    if length <= 0:
        return
    fig = ax.figure
    pos = ax.get_position()
    w_px = pos.width * fig.get_figwidth() * INCH_PX
    h_px = pos.height * fig.get_figheight() * INCH_PX
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    r_px = 4
    rx = min(r_px * (x1 - x0) / w_px, length)
    ry = min(r_px * abs(y1 - y0) / h_px, thickness * r_frac)
    b0, b1, k = y - thickness / 2, y + thickness / 2, 0.5523
    pts = [(0, b0), (length - rx, b0),
           (length - rx + k * rx, b0), (length, b0 + ry - k * ry), (length, b0 + ry),
           (length, b1 - ry),
           (length, b1 - ry + k * ry), (length - rx + k * rx, b1), (length - rx, b1),
           (0, b1), (0, b0)]
    codes = [Path.MOVETO, Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4, Path.LINETO,
             Path.CURVE4, Path.CURVE4, Path.CURVE4, Path.LINETO, Path.CLOSEPOLY]
    ax.add_patch(PathPatch(Path(pts, codes), facecolor=color, edgecolor="none", zorder=3))


def _trend_label(card, x_in, y_in, trend, size=9.5, ha="left"):
    arrow, word = TREND[trend]
    color = card.t["good"] if trend == "up" else card.t["ink2"]
    return card.text(x_in, y_in, f"{arrow} {word}".strip(), size=size, color=color, ha=ha)


# --- card 1: overview ------------------------------------------------------

def overview(report, path, t):
    a = report.author
    if not a.history:
        return None
    card = Card(t, 7.6)
    end = report.year_end - dt.timedelta(days=1)
    card.text(0.5, 0.62, "Citation report", size=11, weight="bold", color=t["muted"])
    card.text(WIDTH - 0.5, 0.62, f"{report.today:%d %b %Y}", size=9.5, color=t["muted"], ha="right")

    # hero
    hero = card.text(0.46, 1.62, f"{a.citedby:,}", size=58, weight="black")
    hw = _text_width(card, hero)
    card.text(0.5 + hw + 0.12, 1.62, "citations", size=13, color=t["ink2"])
    card.text(0.5, 2.02, f"About {a.total_year_end:,.0f} expected by {end:%b %d}", size=12.5)
    card.text(0.5, 2.27, f"80% range {a.citedby + a.lo:,.0f}–{a.citedby + a.hi:,.0f}",
              size=9.5, color=t["muted"])

    # stat tiles
    tiles = [("h-index", f"{a.hindex}", None),
             ("i10-index", f"{a.i10index}", None)]
    if a.year_count is not None:
        tiles.append((f"Citations in {report.today.year}", f"{a.year_count:,}", None))
    if a.fit:
        tiles.append(("Pace now", f"{a.fit.rate:,.0f}/yr", a.fit.trend))
    gap, x0, top, h = 0.14, 0.5, 2.6, 0.95
    w = (WIDTH - 1.0 - gap * (len(tiles) - 1)) / len(tiles)
    for i, (label, value, trend) in enumerate(tiles):
        x = x0 + i * (w + gap)
        card.box(x, top, w, h, t["raised"])
        card.text(x + 0.18, top + 0.32, label, size=9.5, color=t["muted"])
        card.text(x + 0.18, top + 0.72, value, size=21, weight="bold")
        if trend:
            arrow, _ = TREND[trend]
            card.text(x + w - 0.18, top + 0.72, arrow, size=17,
                      color=t["good"] if trend == "up" else t["ink2"], ha="right")

    # chart
    card.text(0.5, 4.08, "Total citations over time", size=11, weight="bold")
    ax = card.axes(0.95, 4.35, WIDTH - 1.85, 2.45)
    proj = a.projection(report.today, report.year_end)
    ds = [d for d, _, _ in a.history]
    vs = [v for _, v, _ in a.history]
    pd_, pm, plo, phi = zip(*proj)
    floor = min(vs) - (phi[-1] - min(vs)) * 0.08
    ax.set_ylim(floor, phi[-1] + (phi[-1] - floor) * 0.06)
    ax.set_xlim(mdates.date2num(ds[0] - dt.timedelta(days=15)),
                mdates.date2num(report.year_end + dt.timedelta(days=45)))
    ax.grid(axis="y", color=t["grid"], linewidth=1 * PX)
    ax.yaxis.set_major_locator(plt.MaxNLocator(4))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    loc = mdates.AutoDateLocator(minticks=3, maxticks=6)
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc, show_offset=False))

    _gradient_fill(ax, ds, vs, t["accent"], floor)
    ax.plot(ds, vs, color=t["accent"], linewidth=2.5 * PX, solid_capstyle="round",
            solid_joinstyle="round", zorder=4)
    ax.fill_between(pd_, plo, phi, color=t["accent"], alpha=0.16, linewidth=0, zorder=3)
    ax.plot(pd_, pm, color=t["accent"], linewidth=2 * PX, linestyle=DASH, zorder=4)
    for d, v, est in a.history[:-1]:
        _dot(ax, d, v, t, hollow=est)
    _dot(ax, report.today, a.citedby, t, halo=True)
    _dot(ax, report.year_end, pm[-1], t, hollow=True)
    ax.annotate(f"~{pm[-1]:,.0f}", xy=(report.year_end, pm[-1]), xytext=(10, 0),
                textcoords="offset points", va="center", fontsize=11, fontweight="bold",
                color=t["ink"], annotation_clip=False)
    ax.annotate("today", xy=(report.today, a.citedby), xytext=(-10, 8),
                textcoords="offset points", ha="right", fontsize=9, color=t["ink2"])
    if any(e for _, _, e in a.history):
        card.text(0.5, 7.25, "Hollow points: Jan 1 totals from Scholar's yearly counts, other "
                  "estimates from paper counts · shaded: 80% range",
                  size=8.5, color=t["muted"])
    return card.save(path)


# --- card 2: fastest-growing papers ------------------------------------------

def top_papers(report, path, t, n=5):
    papers = [p for p in sorted(report.papers, key=lambda p: p.expected_gain, reverse=True)
              if len(p.history) >= 2][:n]
    if not papers:
        return None
    row_h, top = 1.18, 1.45
    card = Card(t, top + row_h * len(papers) + 0.45)
    end = report.year_end - dt.timedelta(days=1)
    card.header("Fastest-growing papers",
                f"Citations today → expected by {end:%b %d}, ranked by expected gain", report.today)
    x_min = min(p.history[0][0] for p in papers)
    for i, p in enumerate(papers):
        y = top + i * row_h
        if i:
            card.hline(0.5, WIDTH - 0.5, y - 0.12)
        card.text(0.5, y + 0.3, f"{i + 1:02d}", size=10, color=t["muted"], weight="bold")
        card.text(0.9, y + 0.3, short(p.title, 46), size=11.5, weight="bold")
        meta = [str(p.year) if p.year else None,
                f"+{p.recent_gain} in the last {p.recent_days} days" if p.recent_gain else None]
        card.text(0.9, y + 0.6, " · ".join(m for m in meta if m), size=9.5, color=t["muted"])
        if p.trend:
            _trend_label(card, 0.9, y + 0.88, p.trend, size=9.5)

        # sparkline
        ax = card.axes(4.55, y + 0.08, 1.85, 0.82)
        ds = [d for d, _ in p.history]
        vs = [v for _, v in p.history]
        lo, hi = 0, max(p.citations + p.hi, 1)
        ax.set_ylim(lo - hi * 0.06, hi * 1.08)
        ax.set_xlim(mdates.date2num(x_min), mdates.date2num(report.year_end))
        ax.set_xticks([])
        ax.set_yticks([])
        _gradient_fill(ax, ds, vs, t["accent"], lo - hi * 0.06, top_alpha=0.28)
        ax.plot(ds, vs, color=t["accent"], linewidth=2 * PX, solid_capstyle="round", zorder=4)
        ax.plot([report.today, report.year_end], [p.citations, p.year_end],
                color=t["accent"], linewidth=2 * PX, linestyle=DASH, zorder=4)
        _dot(ax, report.today, p.citations, t)

        # numbers
        right = WIDTH - 0.5
        card.text(right, y + 0.44, f"{p.citations:,} → {p.year_end:,.0f}", size=16,
                  weight="bold", ha="right")
        card.text(right, y + 0.76, f"{p.rate:.0f} citations/yr", size=9.5,
                  color=t["ink2"], ha="right")
    card.text(0.5, card.h - 0.3, "Sparklines: citations at each check, dashed to the "
              f"expected count on {end:%b %d}", size=8.5, color=t["muted"])
    return card.save(path)


# --- card 3: pace leaderboard ------------------------------------------------

def pace(report, path, t, n=8):
    papers = [p for p in report.papers if p.fit and p.rate >= 0.5][:n]
    if not papers:
        return None
    row_h, top = 0.62, 1.4
    card = Card(t, top + row_h * len(papers) + 0.55)
    card.header("Citation pace", "Citations per year at today's pace", report.today)
    xmax = max(p.rate for p in papers)
    bar_w = WIDTH - 1.0 - 0.85
    for i, p in enumerate(papers):
        y = top + i * row_h
        card.text(0.5, y + 0.12, short(p.title, 64), size=10, color=t["ink2"])
        ax = card.axes(0.5, y + 0.2, bar_w, 0.17)
        ax.set_xlim(0, xmax)
        ax.set_ylim(-0.5, 0.5)
        ax.set_xticks([])
        ax.set_yticks([])
        _rounded_bar(ax, 0, xmax, 1.0, t["track"])
        _rounded_bar(ax, 0, p.rate, 1.0, t["accent"])
        arrow, _ = TREND[p.trend]
        num_x = 0.5 + bar_w + 0.2
        card.text(num_x, y + 0.36, f"{p.rate:.0f}", size=13, weight="bold")
        if arrow:
            card.text(num_x + 0.42, y + 0.36, arrow, size=12,
                      color=t["good"] if p.trend == "up" else t["ink2"])
    card.text(0.5, card.h - 0.32, "↗ accelerating   → steady   ↘ slowing   (no arrow: too early to tell)",
              size=8.5, color=t["muted"])
    return card.save(path)


def render_all(report, out_dir, theme="dark"):
    t = THEMES.get(theme, THEMES["dark"])
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.today.isoformat()
    paths = [
        overview(report, out_dir / f"{stamp}-overview.png", t),
        top_papers(report, out_dir / f"{stamp}-top-papers.png", t),
        pace(report, out_dir / f"{stamp}-pace.png", t),
    ]
    return [p for p in paths if p]
