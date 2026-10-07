"""Shared drafting helpers for the Stage-1 fixture shop drawings.

Every drawing in this folder is built on one :class:`Sheet` (a 16.5 x 10.5 inch
page, rendered at 200 dpi = 3300 x 2100 px).  The page uses "paper millimeters"
as its coordinate system, so a 10 pt font is always 3.53 mm tall regardless of
the drawing scale.  A :class:`View` maps part coordinates ("model millimeters")
to paper millimeters through an origin and a scale factor, and offers the usual
drafting primitives: outlines, hidden lines, centerlines, hatching, linear
dimensions with arrows and extension lines, leader notes, feature control
frames, datum symbols, cutting-plane lines, a title block and a notes block.

Conventions used throughout
---------------------------
* Black lines on white.  Red is reserved for datum symbols and critical notes.
* Dimension offsets are given in PAPER millimeters (distance from the feature
  to the dimension line) so that text spacing does not depend on the scale.
* Every text and every line is registered, and :meth:`Sheet.check_overlaps`
  reports text that touches other text or crosses a line.  This is the
  automatic part of the drawing QA; the PNGs are still inspected by eye.

No dimension of a part lives here; this module holds only drafting standards.
"""

from __future__ import annotations

import math
import textwrap  # noqa: F401  (kept for callers that want to pre-wrap text)
from dataclasses import dataclass
from typing import Iterable, Sequence

import matplotlib

matplotlib.use("Agg")  # file output only, no display needed
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Polygon  # noqa: E402

Point = tuple[float, float]

# --------------------------------------------------------------------------
# Sheet and output
# --------------------------------------------------------------------------
OUTPUT_DPI = 200  # raster resolution of the PNG files
SHEET_WIDTH_IN = 16.5  # page width, inches -> 3300 px at 200 dpi
SHEET_HEIGHT_IN = 10.5  # page height, inches -> 2100 px at 200 dpi
MM_PER_IN = 25.4  # unit conversion
PT_PER_MM = 72.0 / MM_PER_IN  # points per millimeter (for line widths)
SHEET_W = SHEET_WIDTH_IN * MM_PER_IN  # page width in paper mm
SHEET_H = SHEET_HEIGHT_IN * MM_PER_IN  # page height in paper mm
SHEET_MARGIN = 8.0  # distance from page edge to the border frame, paper mm
FRAME_LEFT = SHEET_MARGIN  # border frame, left x
FRAME_RIGHT = SHEET_W - SHEET_MARGIN  # border frame, right x
FRAME_BOTTOM = SHEET_MARGIN  # border frame, bottom y
FRAME_TOP = SHEET_H - SHEET_MARGIN  # border frame, top y

# --------------------------------------------------------------------------
# Colors
# --------------------------------------------------------------------------
BLACK = "#000000"  # all geometry and ordinary text
RED = "#cc0000"  # datum symbols and critical notes only
WHITE = "#ffffff"  # page background and masking fills

# --------------------------------------------------------------------------
# Fonts (points at the 200 dpi output size; never below 9 pt)
# --------------------------------------------------------------------------
FONT_FAMILY = "DejaVu Sans"  # has the diameter sign and multiplication sign
FONT_MIN = 9.0  # smallest permitted text, pt
FONT_DIM = 10.0  # dimension text, pt
FONT_NOTE = 10.0  # notes and leader text, pt
FONT_LABEL = 12.0  # view labels, pt
FONT_TITLE = 15.0  # part name in the title block, pt
FONT_FRAME = 10.0  # text inside feature control frames, pt
FONT_DATUM = 11.0  # datum letters, pt
LINE_SPACING = 1.18  # multi-line text spacing factor

# --------------------------------------------------------------------------
# Line widths (points) and dash patterns (points on / off)
# --------------------------------------------------------------------------
LW_OUTLINE = 1.5  # visible outlines and cut edges
LW_THIN = 0.6  # extension lines, dimension lines, leaders, thread minor lines
LW_HIDDEN = 0.9  # hidden lines
LW_CENTER = 0.6  # centerlines
LW_PHANTOM = 0.8  # phantom lines (mating parts, board, spheres)
LW_HATCH = 0.45  # section hatching
LW_FRAME = 0.9  # feature control frame boxes
LW_BORDER = 1.8  # sheet border
LW_TITLE = 1.0  # title block grid and note boxes
HIDDEN_DASH = (4.5, 2.5)  # hidden-line dash, on/off
CENTER_DASH = (16.0, 3.0, 2.5, 3.0)  # centerline: long, gap, short, gap
PHANTOM_DASH = (14.0, 3.0, 2.5, 3.0, 2.5, 3.0)  # phantom: long, gap, 2 short

STYLES = {
    "outline": (LW_OUTLINE, "-"),
    "thin": (LW_THIN, "-"),
    "hidden": (LW_HIDDEN, (0, HIDDEN_DASH)),
    "center": (LW_CENTER, (0, CENTER_DASH)),
    "phantom": (LW_PHANTOM, (0, PHANTOM_DASH)),
    "frame": (LW_FRAME, "-"),
    "title": (LW_TITLE, "-"),
    "border": (LW_BORDER, "-"),
}

# --------------------------------------------------------------------------
# Dimensioning standards (paper mm)
# --------------------------------------------------------------------------
ARROW_LEN = 3.0  # arrow head length
ARROW_HALF_W = 0.55  # arrow head half width
EXT_GAP = 1.0  # gap between feature and start of an extension line
EXT_OVERSHOOT = 1.8  # extension line runs this far past the dimension line
TEXT_GAP = 0.9  # gap between a dimension line and its text baseline
TEXT_PAD = 1.2  # clearance on each side of text inside a dimension
OUTSIDE_TAIL = 5.0  # tail length of arrows placed outside a short dimension
LEADER_SHOULDER = 4.0  # horizontal shoulder between a leader and its text
LEADER_TEXT_GAP = 1.0  # gap between the shoulder end and the leader text
CENTER_EXT = 4.0  # centerlines extend this far beyond the feature
CENTER_CROSS_EXT = 2.5  # small cross marks extend this far beyond a circle
ARC_STEP_DEG = 2.0  # angular step used to draw circles as polylines
BREAK_AMPLITUDE = 1.0  # freehand break line amplitude
BREAK_WAVELENGTH = 7.0  # freehand break line wavelength

# --------------------------------------------------------------------------
# Hatching
# --------------------------------------------------------------------------
HATCH_SPACING = 1.9  # distance between hatch lines (paper mm)
HATCH_ANGLE = 45.0  # primary hatch angle (degrees)
HATCH_ANGLE_OTHER = 135.0  # hatch angle for a second, different material
HATCH_SPACING_OTHER = 1.5  # spacing used for the second material

# --------------------------------------------------------------------------
# Feature control frames and datum symbols (paper mm)
# --------------------------------------------------------------------------
FCF_H = 6.0  # frame height (and symbol cell width)
FCF_PAD = 1.6  # padding left and right of the text in a frame cell
DATUM_TRI_W = 3.2  # datum triangle base
DATUM_TRI_H = 2.8  # datum triangle height
DATUM_STEM = 5.0  # line from the triangle apex to the letter box
DATUM_BOX = 5.6  # side of the datum letter box
SYMBOL_MARGIN = 1.3  # margin between a frame symbol and its cell edge

# --------------------------------------------------------------------------
# Title block (paper mm)
# --------------------------------------------------------------------------
TB_WIDTH = 170.0  # title block width
TB_ROW_H = 7.6  # standard row height
TB_NAME_ROW_H = 11.5  # part-name row height
TB_LABEL_W = 30.0  # width of the label part of a row
TB_PAD = 1.8  # text padding inside cells
TB_ROWS = 6  # number of standard rows below the part-name row
TB_HEIGHT = TB_NAME_ROW_H + TB_ROWS * TB_ROW_H  # total height
TB_LEFT = FRAME_RIGHT - TB_WIDTH  # left x of the title block
TB_BOTTOM = FRAME_BOTTOM  # bottom y of the title block
TB_TOP = TB_BOTTOM + TB_HEIGHT  # top y of the title block

# Fixed title block texts required on every sheet
TEXT_UNITS = "Dimensions in mm"
TEXT_TOLERANCES = "General tolerances ISO 2768-mK unless stated"
TEXT_PROJECTION = "Third-angle projection"
TEXT_DATE = "2026-10-07"
TEXT_PROJECT = "Stage-1 calibration fixtures"
TEXT_FLANGE_NOTE = (
    "Flange interface per ISO 9409-1-50-4-M6. Confirm against the chosen "
    "robot's flange drawing before machining."
)

# --------------------------------------------------------------------------
# Metric thread helpers
# --------------------------------------------------------------------------
THREAD_MINOR_FACTOR = 1.0825  # minor diameter = d - 1.0825 * pitch (ISO 262)


def thread_minor_diameter(nominal: float, pitch: float) -> float:
    """Return the basic minor diameter of a metric thread (mm)."""
    return nominal - THREAD_MINOR_FACTOR * pitch


# --------------------------------------------------------------------------
# Small geometry helpers
# --------------------------------------------------------------------------
def polar(center: Point, radius: float, angle_deg: float) -> Point:
    """Return the point at ``angle_deg`` (counterclockwise from +x) on a circle."""
    a = math.radians(angle_deg)
    return (center[0] + radius * math.cos(a), center[1] + radius * math.sin(a))


def _segment_hits_rect(p0: Point, p1: Point, rect: tuple[float, float, float, float]) -> bool:
    """Liang-Barsky test: does segment p0-p1 intersect the rectangle?"""
    x0, y0 = p0
    dx, dy = p1[0] - x0, p1[1] - y0
    xmin, ymin, xmax, ymax = rect
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - xmin), (dx, xmax - x0), (-dy, y0 - ymin), (dy, ymax - y0)):
        if p == 0:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


# --------------------------------------------------------------------------
# Sheet
# --------------------------------------------------------------------------
@dataclass
class TitleInfo:
    """Values that change from sheet to sheet in the title block."""

    number: str  # drawing number, e.g. "SC1-01"
    name: str  # part name
    quantity: str  # quantity required
    material: str  # material line
    finish: str  # finish line
    scale: str  # scale text, e.g. "2:1"


class Sheet:
    """One drawing sheet: a matplotlib figure with paper-millimeter axes."""

    TEXT_SHRINK = 0.25  # shrink text boxes by this much before overlap tests

    def __init__(self, title: str):
        self.title = title
        self.fig = plt.figure(
            figsize=(SHEET_WIDTH_IN, SHEET_HEIGHT_IN), dpi=OUTPUT_DPI, facecolor=WHITE
        )
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, SHEET_W)
        self.ax.set_ylim(0, SHEET_H)
        self.ax.axis("off")
        self._renderer = self.fig.canvas.get_renderer()
        self.text_boxes: list[tuple[str, tuple[float, float, float, float]]] = []
        self.segments: list[tuple[Point, Point, str]] = []

    # ---- low-level drawing in paper coordinates --------------------------
    def line(self, pts: Sequence[Point], style: str = "outline", color: str = BLACK,
             register: bool = True, zorder: float = 3) -> None:
        """Draw a polyline in paper mm using a named line style."""
        lw, ls = STYLES[style]
        xs, ys = zip(*pts)
        self.ax.plot(xs, ys, color=color, lw=lw, ls=ls, solid_capstyle="butt",
                     dash_capstyle="butt", solid_joinstyle="miter", zorder=zorder)
        if register:
            for a, b in zip(pts[:-1], pts[1:]):
                self.segments.append((a, b, style))

    def polygon_fill(self, pts: Sequence[Point], color: str, zorder: float = 4) -> None:
        """Draw a filled polygon (arrow heads, datum triangles, masks)."""
        self.ax.add_patch(Polygon(pts, closed=True, facecolor=color, edgecolor=color,
                                  lw=0, zorder=zorder))

    def arrow(self, tip: Point, direction: Point, color: str = BLACK) -> None:
        """Draw a filled arrow head with its tip at ``tip`` and its axis along
        ``direction`` (pointing from the tail toward the tip)."""
        n = math.hypot(*direction)
        dx, dy = direction[0] / n, direction[1] / n
        base = (tip[0] - ARROW_LEN * dx, tip[1] - ARROW_LEN * dy)
        nx, ny = -dy, dx
        self.polygon_fill([tip, (base[0] + ARROW_HALF_W * nx, base[1] + ARROW_HALF_W * ny),
                           (base[0] - ARROW_HALF_W * nx, base[1] - ARROW_HALF_W * ny)], color)

    def circle(self, c: Point, r: float, style: str = "outline", a0: float = 0.0,
               a1: float = 360.0, color: str = BLACK) -> None:
        """Draw a circle or arc (paper mm, angles in degrees)."""
        n = max(2, int(abs(a1 - a0) / ARC_STEP_DEG) + 1)
        pts = [polar(c, r, a) for a in np.linspace(a0, a1, n)]
        self.line(pts, style, color)

    def hatch(self, poly: Sequence[Point], spacing: float = HATCH_SPACING,
              angle: float = HATCH_ANGLE) -> None:
        """Hatch a closed polygon (paper mm) with parallel lines clipped to it."""
        clip = Polygon(poly, closed=True, transform=self.ax.transData)
        xs, ys = zip(*poly)
        xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
        a = math.radians(angle)
        ux, uy = math.cos(a), math.sin(a)  # hatch direction
        nx, ny = -uy, ux  # normal to the hatch lines
        # Project the bounding-box corners on the normal to get the offset range.
        offs = [nx * x + ny * y for x in (xmin, xmax) for y in (ymin, ymax)]
        diag = math.hypot(xmax - xmin, ymax - ymin) + 2.0
        k0, k1 = math.floor(min(offs) / spacing), math.ceil(max(offs) / spacing)
        cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
        for k in range(k0, k1 + 1):
            d = k * spacing
            # point on the line closest to the box center
            t = d - (nx * cx + ny * cy)
            px, py = cx + nx * t, cy + ny * t
            ln, = self.ax.plot([px - ux * diag, px + ux * diag], [py - uy * diag, py + uy * diag],
                               color=BLACK, lw=LW_HATCH, solid_capstyle="butt", zorder=1)
            ln.set_clip_path(clip)

    def wavy(self, p0: Point, p1: Point, style: str = "thin") -> None:
        """Draw a freehand-looking break line between two paper points."""
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        n = max(8, int(length / BREAK_WAVELENGTH * 12))
        ux, uy = (p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length
        pts = []
        for i in range(n + 1):
            s = i / n
            off = BREAK_AMPLITUDE * math.sin(2 * math.pi * s * length / BREAK_WAVELENGTH)
            pts.append((p0[0] + ux * s * length - uy * off, p0[1] + uy * s * length + ux * off))
        self.line(pts, style)

    # ---- text -----------------------------------------------------------
    def measure(self, s: str, size: float = FONT_NOTE, weight: str = "normal") -> tuple[float, float]:
        """Return (width, height) of a text in paper mm."""
        t = self.ax.text(0, 0, s, fontsize=size, fontweight=weight, family=FONT_FAMILY,
                         linespacing=LINE_SPACING)
        bb = t.get_window_extent(self._renderer)
        t.remove()
        return bb.width * MM_PER_IN / OUTPUT_DPI, bb.height * MM_PER_IN / OUTPUT_DPI

    def text(self, x: float, y: float, s: str, size: float = FONT_NOTE, ha: str = "left",
             va: str = "baseline", rotation: float = 0.0, color: str = BLACK,
             weight: str = "normal", check: bool = True, zorder: float = 10) -> tuple[float, float, float, float]:
        """Place text (paper mm).  Returns its bounding box (x0, y0, x1, y1)."""
        if size < FONT_MIN:
            raise ValueError(f"text '{s}' is smaller than {FONT_MIN} pt")
        t = self.ax.text(x, y, s, fontsize=size, ha=ha, va=va, rotation=rotation,
                         rotation_mode="anchor", color=color, fontweight=weight,
                         family=FONT_FAMILY, linespacing=LINE_SPACING, zorder=zorder)
        bb = t.get_window_extent(self._renderer)
        k = MM_PER_IN / OUTPUT_DPI
        box = (bb.x0 * k, bb.y0 * k, bb.x1 * k, bb.y1 * k)
        if check:
            self.text_boxes.append((s.replace("\n", " / "), box))
        return box

    def wrap(self, s: str, width: float, size: float = FONT_NOTE) -> list[str]:
        """Greedy word wrap of ``s`` to ``width`` paper mm using measured widths."""
        lines: list[str] = []
        cur = ""
        for word in s.split():
            trial = word if not cur else cur + " " + word
            if self.measure(trial, size)[0] <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    # ---- QA ----------------------------------------------------------------
    def check_overlaps(self) -> list[str]:
        """Return a list of text/text and text/line collisions found on the sheet."""
        issues: list[str] = []
        shrunk = []
        for label, (x0, y0, x1, y1) in self.text_boxes:
            s = self.TEXT_SHRINK
            shrunk.append((label, (x0 + s, y0 + s, x1 - s, y1 - s)))
        for i, (la, a) in enumerate(shrunk):
            for lb, b in shrunk[i + 1:]:
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    issues.append(f"text/text: '{la}' vs '{lb}'")
            for p0, p1, style in self.segments:
                if _segment_hits_rect(p0, p1, a):
                    issues.append(f"text/line({style}): '{la}' at ({a[0]:.0f},{a[1]:.0f})")
                    break
        for label, (x0, y0, x1, y1) in self.text_boxes:
            if x0 < FRAME_LEFT or x1 > FRAME_RIGHT or y0 < FRAME_BOTTOM or y1 > FRAME_TOP:
                issues.append(f"outside frame: '{label}'")
        return issues

    # ---- frame and finishing ----------------------------------------------
    def border(self) -> None:
        """Draw the sheet border frame."""
        self.line([(FRAME_LEFT, FRAME_BOTTOM), (FRAME_RIGHT, FRAME_BOTTOM),
                   (FRAME_RIGHT, FRAME_TOP), (FRAME_LEFT, FRAME_TOP),
                   (FRAME_LEFT, FRAME_BOTTOM)], "border", register=False)

    def save(self, path: str) -> list[str]:
        """Write the PNG (exactly 3300 x 2100 px) and return overlap issues."""
        self.fig.savefig(path, dpi=OUTPUT_DPI, facecolor=WHITE)
        plt.close(self.fig)
        return self.check_overlaps()

    # ---- title block -------------------------------------------------------
    def title_block(self, info: TitleInfo) -> None:
        """Draw the title block in the bottom right corner."""
        x0, y0, x1, y1 = TB_LEFT, TB_BOTTOM, FRAME_RIGHT, TB_TOP
        self.line([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], "title", register=False)
        # part name row (top)
        yn = y1 - TB_NAME_ROW_H
        self.line([(x0, yn), (x1, yn)], "title", register=False)
        self.text(x0 + TB_PAD, y1 - TB_NAME_ROW_H / 2, f"{info.number}  {info.name}",
                  size=FONT_TITLE, va="center", weight="bold", check=False)
        rows = [
            [("Drawing no.", info.number, 0.5), ("Quantity", info.quantity, 0.5)],
            [("Material", info.material, 1.0)],
            [("Finish", info.finish, 1.0)],
            [("Scale", info.scale, 0.5), ("Date", TEXT_DATE, 0.5)],
            [(None, TEXT_UNITS, 0.5), (None, TEXT_PROJECTION, 0.5)],
            [(None, TEXT_TOLERANCES, 0.62), (None, TEXT_PROJECT, 0.38)],
        ]
        y = yn
        for row in rows:
            y_next = y - TB_ROW_H
            self.line([(x0, y_next), (x1, y_next)], "title", register=False)
            x = x0
            for label, value, frac in row:
                w = TB_WIDTH * frac
                if x > x0:
                    self.line([(x, y), (x, y_next)], "title", register=False)
                tx = x + TB_PAD
                if label:
                    self.text(tx, (y + y_next) / 2, label, size=FONT_MIN, va="center",
                              check=False)
                    tx = x + (TB_LABEL_W if frac >= 1.0 else TB_LABEL_W * 0.75)
                self.text(tx, (y + y_next) / 2, value, size=FONT_NOTE, va="center",
                          weight="bold" if label else "normal", check=False)
                x += w
            y = y_next

    # ---- notes -------------------------------------------------------------
    def notes_block(self, x: float, y_top: float, width: float, items: Iterable[str],
                    title: str = "NOTES", size: float = FONT_NOTE) -> float:
        """Draw a numbered notes list; returns the y of the bottom of the block."""
        self.text(x, y_top - 3.4, title, size=FONT_LABEL, weight="bold", check=False)
        y = y_top - 3.4 - 5.4
        indent = 6.0
        line_h = size * 0.3528 * LINE_SPACING * 1.05  # pt -> mm with spacing
        for i, item in enumerate(items, start=1):
            lines = self.wrap(item, width - indent, size)
            self.text(x, y, f"{i}.", size=size, check=False)
            for ln in lines:
                self.text(x + indent, y, ln, size=size, check=False)
                y -= line_h
            y -= line_h * 0.25
        return y

    def boxed_note(self, x: float, y_top: float, width: float, text: str,
                   color: str = RED, size: float = FONT_NOTE, weight: str = "bold") -> float:
        """Draw a boxed critical note; returns the y of the bottom of the box."""
        pad = 2.0
        lines = self.wrap(text, width - 2 * pad, size)
        line_h = size * 0.3528 * LINE_SPACING * 1.05
        height = 2 * pad + line_h * len(lines)
        self.line([(x, y_top), (x + width, y_top), (x + width, y_top - height),
                   (x, y_top - height), (x, y_top)], "title", color=color, register=False)
        y = y_top - pad - line_h * 0.78
        for ln in lines:
            self.text(x + pad, y, ln, size=size, color=color, weight=weight, check=False)
            y -= line_h
        return y_top - height

    # ---- feature control frame & datum -------------------------------------
    def _frame_symbol(self, kind: str, cx: float, cy: float, color: str) -> None:
        """Draw a geometric-tolerance symbol centered at (cx, cy)."""
        h = FCF_H / 2 - SYMBOL_MARGIN  # half size of the symbol
        s = "frame"
        if kind == "perp":  # perpendicularity
            self.line([(cx - h, cy - h), (cx + h, cy - h)], s, color, False)
            self.line([(cx, cy - h), (cx, cy + h)], s, color, False)
        elif kind == "flat":  # flatness: a parallelogram
            k = h * 0.55
            self.line([(cx - h, cy - k), (cx + h * 0.55, cy - k), (cx + h, cy + k),
                       (cx - h * 0.55, cy + k), (cx - h, cy - k)], s, color, False)
        elif kind == "para":  # parallelism: two slanted lines
            for dx in (-h * 0.35, h * 0.35):
                self.line([(cx + dx - h * 0.45, cy - h), (cx + dx + h * 0.45, cy + h)], s, color, False)
        elif kind == "coax":  # coaxiality: two concentric circles
            self.circle((cx, cy), h, s, color=color)
            self.circle((cx, cy), h * 0.55, s, color=color)
        elif kind == "straight":  # straightness: a horizontal line
            self.line([(cx - h, cy), (cx + h, cy)], s, color, False)
        elif kind == "position":  # true position: circle with crosshair
            self.circle((cx, cy), h * 0.7, s, color=color)
            self.line([(cx - h, cy), (cx + h, cy)], s, color, False)
            self.line([(cx, cy - h), (cx, cy + h)], s, color, False)
        else:
            raise ValueError(kind)

    def fcf(self, x: float, y: float, kind: str, tol: str, datums: Sequence[str] = (),
            color: str = BLACK) -> dict[str, Point]:
        """Draw a feature control frame with its left edge middle at (x, y).

        Returns the frame's connection points ('left', 'right', 'top', 'bottom').
        """
        tw, _ = self.measure(tol, FONT_FRAME)
        cells = [FCF_H, tw + 2 * FCF_PAD] + [FCF_H] * len(datums)
        total = sum(cells)
        yb, yt = y - FCF_H / 2, y + FCF_H / 2
        self.line([(x, yb), (x + total, yb), (x + total, yt), (x, yt), (x, yb)], "frame", color)
        xc = x
        for w in cells[:-1]:
            xc += w
            self.line([(xc, yb), (xc, yt)], "frame", color)
        self._frame_symbol(kind, x + cells[0] / 2, y, color)
        self.text(x + cells[0] + cells[1] / 2, y, tol, size=FONT_FRAME, ha="center", va="center",
                  color=color, check=False)
        xc = x + cells[0] + cells[1]
        for d in datums:
            self.text(xc + FCF_H / 2, y, d, size=FONT_FRAME, ha="center", va="center",
                      color=color, check=False)
            xc += FCF_H
        return {"left": (x, y), "right": (x + total, y), "top": (x + total / 2, yt),
                "bottom": (x + total / 2, yb)}

    def datum_feature(self, base: Point, outward: Point, letter: str, color: str = RED) -> Point:
        """Draw a datum feature symbol: filled triangle on the feature at ``base``,
        a stem along ``outward`` (unit vector away from the feature) and a boxed letter.
        Returns the center of the letter box."""
        ox, oy = outward
        nx, ny = -oy, ox
        apex = (base[0] + ox * DATUM_TRI_H, base[1] + oy * DATUM_TRI_H)
        self.polygon_fill([(base[0] + nx * DATUM_TRI_W / 2, base[1] + ny * DATUM_TRI_W / 2),
                           (base[0] - nx * DATUM_TRI_W / 2, base[1] - ny * DATUM_TRI_W / 2), apex], color)
        box_c = (apex[0] + ox * (DATUM_STEM + DATUM_BOX / 2), apex[1] + oy * (DATUM_STEM + DATUM_BOX / 2))
        self.line([apex, (apex[0] + ox * DATUM_STEM, apex[1] + oy * DATUM_STEM)], "thin", color)
        b = DATUM_BOX / 2
        self.line([(box_c[0] - b, box_c[1] - b), (box_c[0] + b, box_c[1] - b),
                   (box_c[0] + b, box_c[1] + b), (box_c[0] - b, box_c[1] + b),
                   (box_c[0] - b, box_c[1] - b)], "frame", color)
        self.text(box_c[0], box_c[1], letter, size=FONT_DATUM, ha="center", va="center",
                  color=color, weight="bold", check=False)
        return box_c

    def frame_leader(self, frame_pt: Point, target: Point, color: str = BLACK) -> None:
        """Straight leader with an arrow from a control frame to a feature."""
        self.line([frame_pt, target], "thin", color)
        d = (target[0] - frame_pt[0], target[1] - frame_pt[1])
        self.arrow(target, d, color)


# --------------------------------------------------------------------------
# View: model coordinates -> paper
# --------------------------------------------------------------------------
class View:
    """A drawing view with an origin (paper mm) and a scale (paper mm / model mm)."""

    def __init__(self, sheet: Sheet, origin: Point, scale: float):
        self.sheet = sheet
        self.origin = origin
        self.scale = scale

    def P(self, u: float, v: float) -> Point:
        """Model (u, v) -> paper (x, y)."""
        return (self.origin[0] + self.scale * u, self.origin[1] + self.scale * v)

    # ---- geometry -------------------------------------------------------
    def line(self, p0: Point, p1: Point, style: str = "outline", color: str = BLACK) -> None:
        self.sheet.line([self.P(*p0), self.P(*p1)], style, color)

    def polyline(self, pts: Sequence[Point], style: str = "outline", closed: bool = False,
                 color: str = BLACK) -> None:
        paper = [self.P(*p) for p in pts]
        if closed:
            paper.append(paper[0])
        self.sheet.line(paper, style, color)

    def circle(self, c: Point, r: float, style: str = "outline", a0: float = 0.0,
               a1: float = 360.0, color: str = BLACK) -> None:
        self.sheet.circle(self.P(*c), r * self.scale, style, a0, a1, color)

    def hatch(self, pts: Sequence[Point], other: bool = False) -> None:
        """Hatch a model-space polygon (``other`` selects the second material hatch)."""
        paper = [self.P(*p) for p in pts]
        if other:
            self.sheet.hatch(paper, HATCH_SPACING_OTHER, HATCH_ANGLE_OTHER)
        else:
            self.sheet.hatch(paper)

    def section_region(self, pts: Sequence[Point], other: bool = False, outline: bool = True) -> None:
        """Hatch and outline one closed cut-material polygon."""
        self.hatch(pts, other)
        if outline:
            self.polyline(pts, "outline", closed=True)

    def center_h(self, u0: float, u1: float, v: float) -> None:
        """Horizontal centerline between model u0 and u1 at height v."""
        self.line((u0, v), (u1, v), "center")

    def center_v(self, v0: float, v1: float, u: float) -> None:
        """Vertical centerline between model v0 and v1 at u."""
        self.line((u, v0), (u, v1), "center")

    def center_cross(self, c: Point, r: float) -> None:
        """Centerline cross through center ``c`` extending CENTER_CROSS_EXT past radius r."""
        ext = r + CENTER_CROSS_EXT / self.scale
        self.line((c[0] - ext, c[1]), (c[0] + ext, c[1]), "center")
        self.line((c[0], c[1] - ext), (c[0], c[1] + ext), "center")

    # ---- linear dimensions ---------------------------------------------------
    def dim_h(self, u0: float, u1: float, v0: float, v1: float, offset: float, text: str,
              text_pos: float = 0.5, outside: str | None = None, ext0: bool = True,
              ext1: bool = True) -> None:
        """Horizontal dimension between (u0, v0) and (u1, v1).

        ``offset`` is the paper-mm distance from the outermost feature point to the
        dimension line (positive = above, negative = below).  ``outside`` forces
        outside arrows ('left' or 'right' selects which side the text goes).
        """
        sh = self.sheet
        x0, y0 = self.P(u0, v0)
        x1, y1 = self.P(u1, v1)
        sgn = 1.0 if offset >= 0 else -1.0
        yd = (max(y0, y1) if sgn > 0 else min(y0, y1)) + offset
        for x, y, on in ((x0, y0, ext0), (x1, y1, ext1)):
            if on:
                sh.line([(x, y + sgn * EXT_GAP), (x, yd + sgn * EXT_OVERSHOOT)], "thin")
        xa, xb = (x0, x1) if x0 <= x1 else (x1, x0)
        tw, _ = sh.measure(text, FONT_DIM)
        fits = (xb - xa) >= tw + 2 * TEXT_PAD + 2 * ARROW_LEN
        if outside is None and fits:
            sh.line([(xa, yd), (xb, yd)], "thin")
            sh.arrow((xa, yd), (-1, 0))
            sh.arrow((xb, yd), (1, 0))
            cx = xa + (xb - xa) * text_pos
            sh.text(cx, yd + TEXT_GAP, text, size=FONT_DIM, ha="center")
        else:
            side = outside or "right"
            sh.line([(xa - OUTSIDE_TAIL, yd), (xb + OUTSIDE_TAIL, yd)], "thin")
            sh.arrow((xa, yd), (1, 0))
            sh.arrow((xb, yd), (-1, 0))
            if side == "right":
                sh.text(xb + OUTSIDE_TAIL + TEXT_GAP, yd + TEXT_GAP, text, size=FONT_DIM, ha="left")
            else:
                sh.text(xa - OUTSIDE_TAIL - TEXT_GAP, yd + TEXT_GAP, text, size=FONT_DIM, ha="right")

    def dim_v(self, u0: float, u1: float, v0: float, v1: float, offset: float, text: str,
              text_pos: float = 0.5, outside: str | None = None, ext0: bool = True,
              ext1: bool = True) -> None:
        """Vertical dimension between (u0, v0) and (u1, v1).

        ``offset`` is the paper-mm distance from the outermost feature point to the
        dimension line (positive = to the right, negative = to the left).  The text
        is rotated 90 degrees and sits left of the dimension line.  ``outside``
        forces outside arrows ('up' or 'down' selects which end the text goes to).
        """
        sh = self.sheet
        x0, y0 = self.P(u0, v0)
        x1, y1 = self.P(u1, v1)
        sgn = 1.0 if offset >= 0 else -1.0
        xd = (max(x0, x1) if sgn > 0 else min(x0, x1)) + offset
        for x, y, on in ((x0, y0, ext0), (x1, y1, ext1)):
            if on:
                sh.line([(x + sgn * EXT_GAP, y), (xd + sgn * EXT_OVERSHOOT, y)], "thin")
        ya, yb = (y0, y1) if y0 <= y1 else (y1, y0)
        tw, _ = sh.measure(text, FONT_DIM)
        fits = (yb - ya) >= tw + 2 * TEXT_PAD + 2 * ARROW_LEN
        if outside is None and fits:
            sh.line([(xd, ya), (xd, yb)], "thin")
            sh.arrow((xd, ya), (0, -1))
            sh.arrow((xd, yb), (0, 1))
            cy = ya + (yb - ya) * text_pos
            sh.text(xd - TEXT_GAP, cy, text, size=FONT_DIM, ha="center", rotation=90)
        else:
            side = outside or "up"
            sh.line([(xd, ya - OUTSIDE_TAIL), (xd, yb + OUTSIDE_TAIL)], "thin")
            sh.arrow((xd, ya), (0, 1))
            sh.arrow((xd, yb), (0, -1))
            if side == "up":
                sh.text(xd - TEXT_GAP, yb + OUTSIDE_TAIL + TEXT_GAP, text, size=FONT_DIM,
                        ha="left", rotation=90)
            else:
                sh.text(xd - TEXT_GAP, ya - OUTSIDE_TAIL - TEXT_GAP, text, size=FONT_DIM,
                        ha="right", rotation=90)

    def dim_angle(self, center: Point, a0: float, a1: float, radius_paper: float, text: str,
                  text_dx: float = 0.0, text_dy: float = 0.0) -> None:
        """Angular dimension: an arc of ``radius_paper`` between a0 and a1 (degrees)."""
        sh = self.sheet
        c = self.P(*center)
        sh.circle(c, radius_paper, "thin", a0, a1)
        for a, sgn in ((a0, -1.0), (a1, 1.0)):
            tip = polar(c, radius_paper, a)
            ar = math.radians(a)
            tangent = (-math.sin(ar) * sgn, math.cos(ar) * sgn)
            sh.arrow(tip, tangent)
        mid = polar(c, radius_paper, (a0 + a1) / 2)
        sh.text(mid[0] + text_dx, mid[1] + text_dy, text, size=FONT_DIM, ha="center")

    # ---- leaders -------------------------------------------------------------
    def leader(self, target: Point, text: str, dx: float, dy: float, terminator: str = "arrow",
               color: str = BLACK, size: float = FONT_NOTE, weight: str = "normal") -> tuple[float, float, float, float]:
        """Leader note: line from ``target`` (model) to an elbow offset (dx, dy) paper
        mm away, a short shoulder, and the text.  Returns the text box."""
        sh = self.sheet
        t = self.P(*target)
        e = (t[0] + dx, t[1] + dy)
        sgn = 1.0 if dx >= 0 else -1.0
        s_end = (e[0] + sgn * LEADER_SHOULDER, e[1])
        sh.line([t, e, s_end], "thin", color)
        if terminator == "arrow":
            sh.arrow(t, (t[0] - e[0], t[1] - e[1]), color)
        elif terminator == "dot":
            sh.circle(t, 0.5, "thin", color=color)
            sh.polygon_fill([(t[0] + 0.5 * math.cos(a), t[1] + 0.5 * math.sin(a))
                             for a in np.linspace(0, 2 * math.pi, 16)], color)
        return sh.text(s_end[0] + sgn * LEADER_TEXT_GAP, s_end[1], text, size=size,
                       ha="left" if sgn > 0 else "right", va="center", color=color, weight=weight)

    def leader_circle(self, c: Point, r: float, angle: float, text: str, dx: float, dy: float,
                      **kw) -> tuple[float, float, float, float]:
        """Leader whose arrow touches the circle (center c, radius r) at ``angle``."""
        return self.leader(polar(c, r, angle), text, dx, dy, **kw)

    def label(self, x: float, y: float, text: str, size: float = FONT_LABEL, ha: str = "left") -> None:
        """Bold view label at paper position (x, y)."""
        self.sheet.text(x, y, text, size=size, ha=ha, weight="bold")

    # ---- cutting plane --------------------------------------------------------
    def cutting_plane(self, pts: Sequence[Point], sight: Point, label: str,
                      end_len: float = 9.0, arrow_len: float = 9.0) -> None:
        """Cutting-plane line through model points ``pts`` (a polyline, possibly bent).

        ``sight`` is the paper-space unit vector of the viewing direction; arrows
        at both ends point along it and the label letter is placed beyond them.
        """
        sh = self.sheet
        paper = [self.P(*p) for p in pts]
        sh.line(paper, "center")
        ends = [(paper[0], paper[1]), (paper[-1], paper[-2])]
        sx, sy = sight
        for (p, q) in ends:
            d = (q[0] - p[0], q[1] - p[1])
            n = math.hypot(*d)
            d = (d[0] / n, d[1] / n)
            thick_end = (p[0] + d[0] * end_len, p[1] + d[1] * end_len)
            sh.line([p, thick_end], "outline")
            tail = (p[0] + sx * 0.0, p[1])  # arrow shaft starts at the outer end
            shaft_end = (tail[0] + sx * arrow_len, tail[1] + sy * arrow_len)
            sh.line([tail, shaft_end], "outline")
            sh.arrow(shaft_end, (sx, sy))
            # label beyond the arrow, offset away from the line
            lx = shaft_end[0] + sx * 3.2
            ly = shaft_end[1] + sy * 3.2
            sh.text(lx, ly, label, size=FONT_LABEL, ha="center", va="center", weight="bold")
        # bends: short thick marks at interior vertices
        for i in range(1, len(paper) - 1):
            for nb in (paper[i - 1], paper[i + 1]):
                d = (nb[0] - paper[i][0], nb[1] - paper[i][1])
                n = math.hypot(*d)
                sh.line([paper[i], (paper[i][0] + d[0] / n * 4.0, paper[i][1] + d[1] / n * 4.0)], "outline")
