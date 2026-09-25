"""Build the report's charts as static SVG (light + dark) from data/krones_financials_2015_2025.csv.

No third-party dependencies. Run from the repository root:

    python3 charts/build_charts.py
"""

import csv
import math
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "krones_financials_2015_2025.csv"
OUT = ROOT / "charts"

FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

# Reference palette (dataviz skill): categorical slots 1-2, chrome and ink per mode.
THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781",
                  grid="#e1e0d9", axis="#c3c2b7", s1="#2a78d6", s2="#eb6834"),
    "dark": dict(surface="#1a1a19", ink="#ffffff", ink2="#c3c2b7", muted="#898781",
                 grid="#2c2c2a", axis="#383835", s1="#3987e5", s2="#d95926"),
}

W, H = 760, 420
LEFT, RIGHT, TOP, BOTTOM = 64, 28, 104, 44


def load():
    rows = list(csv.DictReader(DATA.open()))

    def col(name):
        return [float(r[name]) if r[name] != "" else None for r in rows]

    return [int(r["year"]) for r in rows], col


def fmt_int(v):
    return f"{v:,.0f}".replace("-", "−")


def fmt_pct(v):
    return f"{v:.1f}%".replace("-", "−")


def fmt_eur(v):
    return f"{v:.2f}".replace("-", "−")


class Chart:
    def __init__(self, theme, title, subtitle, years, y_min, y_max, y_step, y_fmt,
                 right=RIGHT, desc=""):
        self.t = THEMES[theme]
        self.title, self.subtitle, self.desc = title, subtitle, desc
        self.years = years
        self.y_min, self.y_max, self.y_step, self.y_fmt = y_min, y_max, y_step, y_fmt
        self.x0, self.x1 = LEFT, W - right
        self.y0, self.y1 = TOP, H - BOTTOM
        self.band = (self.x1 - self.x0) / len(years)
        self.parts = []

    # --- scales -----------------------------------------------------------------
    def x(self, i):
        return self.x0 + self.band * (i + 0.5)

    def y(self, v):
        return self.y1 - (v - self.y_min) / (self.y_max - self.y_min) * (self.y1 - self.y0)

    # --- chrome -----------------------------------------------------------------
    def frame(self, legend=()):
        t = self.t
        p = self.parts
        p.append(f'<rect width="{W}" height="{H}" rx="8" fill="{t["surface"]}"/>')
        p.append(f'<text x="{LEFT - 44}" y="30" font-size="17" font-weight="600" fill="{t["ink"]}">'
                 f'{escape(self.title)}</text>')
        p.append(f'<text x="{LEFT - 44}" y="52" font-size="13" fill="{t["ink2"]}">'
                 f'{escape(self.subtitle)}</text>')
        lx = LEFT - 44
        for label, key, kind in legend:
            color = t[key]
            if kind == "line":
                p.append(f'<line x1="{lx}" y1="75" x2="{lx + 18}" y2="75" stroke="{color}" '
                         f'stroke-width="2" stroke-linecap="round"/>')
                p.append(f'<circle cx="{lx + 9}" cy="75" r="4" fill="{color}" '
                         f'stroke="{t["surface"]}" stroke-width="2"/>')
                tx = lx + 26
            else:
                p.append(f'<rect x="{lx}" y="69" width="12" height="12" rx="3" fill="{color}"/>')
                tx = lx + 18
            p.append(f'<text x="{tx}" y="79.5" font-size="13" fill="{t["ink2"]}">{escape(label)}</text>')
            lx = tx + 7.4 * len(label) + 26
        # gridlines + y ticks
        v = self.y_min
        while v <= self.y_max + 1e-9:
            yy = self.y(v)
            stroke = t["axis"] if abs(v) < 1e-9 else t["grid"]
            p.append(f'<line x1="{self.x0}" y1="{yy:.1f}" x2="{self.x1}" y2="{yy:.1f}" '
                     f'stroke="{stroke}" stroke-width="1" shape-rendering="crispEdges"/>')
            p.append(f'<text x="{self.x0 - 8}" y="{yy + 4:.1f}" font-size="12" fill="{t["muted"]}" '
                     f'text-anchor="end" style="font-variant-numeric: tabular-nums">'
                     f'{escape(self.y_fmt(v))}</text>')
            v += self.y_step
        # x labels
        for i, yr in enumerate(self.years):
            p.append(f'<text x="{self.x(i):.1f}" y="{self.y1 + 22}" font-size="12" fill="{t["muted"]}" '
                     f'text-anchor="middle" style="font-variant-numeric: tabular-nums">{yr}</text>')

    # --- marks ------------------------------------------------------------------
    def bar(self, cx, w, v, color, tip):
        base = self.y(0) if self.y_min <= 0 <= self.y_max else self.y1
        end = self.y(v)
        x = cx - w / 2
        h = abs(base - end)
        r = min(4, h, w / 2)
        if v >= 0:
            d = (f"M{x:.1f},{base:.1f} L{x:.1f},{end + r:.1f} A{r},{r} 0 0 1 {x + r:.1f},{end:.1f} "
                 f"L{x + w - r:.1f},{end:.1f} A{r},{r} 0 0 1 {x + w:.1f},{end + r:.1f} "
                 f"L{x + w:.1f},{base:.1f} Z")
        else:
            d = (f"M{x:.1f},{base:.1f} L{x:.1f},{end - r:.1f} A{r},{r} 0 0 0 {x + r:.1f},{end:.1f} "
                 f"L{x + w - r:.1f},{end:.1f} A{r},{r} 0 0 0 {x + w:.1f},{end - r:.1f} "
                 f"L{x + w:.1f},{base:.1f} Z")
        self.parts.append(f'<g><title>{escape(tip)}</title><path d="{d}" fill="{color}"/></g>')

    def line(self, idx_vals, color, tips):
        pts = [(self.x(i), self.y(v)) for i, v in idx_vals]
        d = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        self.parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" '
                          f'stroke-linejoin="round" stroke-linecap="round"/>')
        for (px, py), tip in zip(pts, tips):
            self.parts.append(f'<g><title>{escape(tip)}</title>'
                              f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{color}" '
                              f'stroke="{self.t["surface"]}" stroke-width="2"/></g>')

    def label(self, x, y, text, anchor="middle", weight="400"):
        self.parts.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="12" font-weight="{weight}" '
                          f'fill="{self.t["ink2"]}" text-anchor="{anchor}" '
                          f'style="font-variant-numeric: tabular-nums">{escape(text)}</text>')

    def svg(self):
        body = "\n  ".join(self.parts)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
                f'role="img" aria-labelledby="t d" font-family="{FONT}">\n'
                f'  <title id="t">{escape(self.title)}</title>\n'
                f'  <desc id="d">{escape(self.desc or self.subtitle)}</desc>\n  {body}\n</svg>\n')


def write(name, theme, chart):
    (OUT / f"{name}-{theme}.svg").write_text(chart.svg(), encoding="utf-8")


def revenue_orders(theme, years, col):
    rev, orders = col("revenue_eur_m"), col("order_intake_eur_m")
    c = Chart(theme, "Revenue and order intake, 2015–2025",
              "€ million · orders ran far ahead of revenue in 2021–22, filling the backlog",
              years, 0, 6000, 1000, fmt_int,
              desc="Line chart. Revenue rose from 3,174 to 5,664 million euros; order intake from 3,189 to 5,565, "
                   "peaking at 5,783 in 2022.")
    c.frame(legend=[(f"Revenue (2025: {fmt_int(rev[-1])})", "s1", "line"),
                    (f"Order intake (2025: {fmt_int(orders[-1])})", "s2", "line")])
    c.line(list(enumerate(orders)), c.t["s2"], [f"{y} order intake: €{fmt_int(v)}m" for y, v in zip(years, orders)])
    c.line(list(enumerate(rev)), c.t["s1"], [f"{y} revenue: €{fmt_int(v)}m" for y, v in zip(years, rev)])
    i22 = years.index(2022)
    c.label(c.x(i22), c.y(orders[i22]) - 12, f"{fmt_int(orders[i22])} (2022 peak)")
    i20 = years.index(2020)
    c.label(c.x(i20), c.y(rev[i20]) + 24, f"{fmt_int(rev[i20])} (COVID)")
    return c


def backlog(theme, years, col):
    bl = col("order_backlog_eur_m")
    c = Chart(theme, "Order backlog at year-end, 2015–2025",
              "€ million · ≈€4.3bn at June 2026 · 2015, 2016 and 2021 derived from reported growth rates",
              years, 0, 5000, 1000, fmt_int,
              desc="Column chart. Backlog was about 1.1 to 1.4 billion euros from 2015 to 2020, then rose to 3.5 billion "
                   "in 2022 and about 4.2 billion in 2025.")
    c.frame()
    w = min(24, c.band * 0.6)
    for i, (yr, v) in enumerate(zip(years, bl)):
        c.bar(c.x(i), w, v, c.t["s1"], f"{yr} backlog: €{fmt_int(v)}m")
    for yr in (2015, 2020, 2022, 2025):
        i = years.index(yr)
        c.label(c.x(i), c.y(bl[i]) - 8, fmt_int(bl[i]))
    return c


def margins(theme, years, col):
    rev, ebt, ebitda = col("revenue_eur_m"), col("ebt_eur_m"), col("ebitda_eur_m")
    ebt_m = [e / r * 100 for e, r in zip(ebt, rev)]
    ebitda_m = [(i, e / r * 100) for i, (e, r) in enumerate(zip(ebitda, rev)) if e is not None]
    c = Chart(theme, "Profit margins, 2015–2025",
              "% of revenue · the 2018–20 slump and the recovery to record levels",
              years, -2, 12, 2, lambda v: f"{v:.0f}%".replace("-", "−"), right=64,
              desc="Line chart. EBT margin was 7.0% in 2015-2017, fell to -1.1% in 2020 and recovered to 7.5% in 2025. "
                   "EBITDA margin rose from 4.0% in 2020 to 10.6% in 2025.")
    c.frame(legend=[("EBT margin", "s1", "line"), ("EBITDA margin (2020–2025)", "s2", "line")])
    c.line(ebitda_m, c.t["s2"], [f"{years[i]} EBITDA margin: {fmt_pct(v)}" for i, v in ebitda_m])
    c.line(list(enumerate(ebt_m)), c.t["s1"], [f"{y} EBT margin: {fmt_pct(v)}" for y, v in zip(years, ebt_m)])
    last = len(years) - 1
    c.label(c.x(last) + 12, c.y(ebt_m[last]) + 4, fmt_pct(ebt_m[last]), anchor="start")
    c.label(c.x(last) + 12, c.y(ebitda_m[-1][1]) + 4, fmt_pct(ebitda_m[-1][1]), anchor="start")
    i20 = years.index(2020)
    c.label(c.x(i20), c.y(ebt_m[i20]) + 20, fmt_pct(ebt_m[i20]))
    i16 = years.index(2016)
    c.label(c.x(i16), c.y(ebt_m[i16]) - 12, fmt_pct(ebt_m[i16]))
    return c


def cash(theme, years, col):
    ni, fcf = col("net_income_eur_m"), col("fcf_reported_eur_m")
    start = years.index(2017)
    yrs = years[start:]
    ni, fcf = ni[start:], fcf[start:]
    c = Chart(theme, "Net income vs. free cash flow, 2017–2025",
              "€ million · FCF as reported (after acquisitions) · lumpy, but it follows profit over a cycle",
              yrs, -200, 400, 100, fmt_int,
              desc="Grouped columns. Net income and reported free cash flow by year from 2017 to 2025. "
                   "Free cash flow was negative in 2017, 2019 and 2023.")
    c.frame(legend=[("Net income", "s1", "bar"), ("Free cash flow (reported)", "s2", "bar")])
    w = min(24, (c.band - 2) * 0.34)
    for i, yr in enumerate(yrs):
        cx = c.x(i)
        c.bar(cx - 1 - w / 2, w, ni[i], c.t["s1"], f"{yr} net income: €{fmt_int(ni[i])}m")
        c.bar(cx + 1 + w / 2, w, fcf[i], c.t["s2"], f"{yr} free cash flow: €{fmt_int(fcf[i])}m")
    for yr in (2017, 2022, 2023):
        i = yrs.index(yr)
        v = fcf[i]
        y = c.y(v) - 8 if v >= 0 else c.y(v) + 18
        c.label(c.x(i) + 1 + w / 2, y, fmt_int(v))
    i25 = yrs.index(2025)
    c.label(c.x(i25) - 1 - w / 2, c.y(ni[i25]) - 8, fmt_int(ni[i25]))
    return c


def per_share(theme, years, col):
    eps, dps = col("eps_eur"), col("dps_eur")
    c = Chart(theme, "Earnings and dividend per share, 2015–2025",
              "€ per share · 31.6m shares throughout, so per-share growth equals company growth",
              years, -4, 10, 2, lambda v: f"{v:.0f}".replace("-", "−"),
              desc="Grouped columns. EPS rose from 4.98 euros in 2015 to 9.45 in 2025, with a loss of -2.52 in 2020. "
                   "Dividend rose from 1.45 to 2.80 euros, cut to 0.75 for 2019 and 0.06 for 2020.")
    c.frame(legend=[("Earnings per share", "s1", "bar"), ("Dividend per share", "s2", "bar")])
    w = min(24, (c.band - 2) * 0.34)
    for i, yr in enumerate(years):
        cx = c.x(i)
        c.bar(cx - 1 - w / 2, w, eps[i], c.t["s1"], f"{yr} EPS: €{fmt_eur(eps[i])}")
        c.bar(cx + 1 + w / 2, w, dps[i], c.t["s2"], f"{yr} dividend: €{fmt_eur(dps[i])}")
    last = len(years) - 1
    c.label(c.x(last) - 1 - w / 2, c.y(eps[last]) - 8, fmt_eur(eps[last]))
    c.label(c.x(last) + 1 + w / 2, c.y(dps[last]) - 8, fmt_eur(dps[last]))
    i20 = years.index(2020)
    c.label(c.x(i20) - 1 - w / 2, c.y(eps[i20]) + 18, fmt_eur(eps[i20]))
    return c


def main():
    years, col = load()
    charts = {
        "revenue-orders": revenue_orders,
        "backlog": backlog,
        "margins": margins,
        "cash": cash,
        "per-share": per_share,
    }
    for name, fn in charts.items():
        for theme in THEMES:
            write(name, theme, fn(theme, years, col))
    print(f"wrote {len(charts) * len(THEMES)} SVGs to {OUT}")


if __name__ == "__main__":
    main()
