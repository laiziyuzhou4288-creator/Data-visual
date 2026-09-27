# /// script
# requires-python = ">=3.10"
# dependencies = ["plotly"]
# ///

"""
Build a static HTML page from the earthquake tree-ring data.

This is step one: just the picture, no interaction yet.  Run it:

    uv run make_web.py

It writes site/index.html -- open that file in a browser.
"""

import calendar
import csv
import datetime as dt
import math
from pathlib import Path

import plotly.graph_objects as go

HERE = Path(__file__).parent
YEARLY = HERE / "out" / "quakes-by-year.csv"
EVENTS = HERE / "out" / "quakes-events.csv"
SITE = HERE / "site"
OUTPUT = SITE / "index.html"

# ---------------------------------------------------------------------------
# Knobs (match plot.py as closely as Plotly allows).
# ---------------------------------------------------------------------------

PITH_RADIUS = 1.0
RADIAL_STEP = 2.0
THICKNESS_MIN = 0.6         # quietest year
THICKNESS_MAX = 2.4         # busiest year
SPIKE_MAX = 1.2             # extra radius at a full-strength spike

OMORI_C = 4.0
OMORI_P = 1.05
ROUNDING_DAYS = 3
CURVE_RESOLUTION = 720      # one point every half a degree; enough for the web

DEPTH_COLOUR_CAP_KM = 100

# Taiwan silhouette, same 8 compass points as plot.py.
TAIWAN_SHAPE = {
    0:             1.00,
    math.pi / 4:   1.06,
    math.pi / 2:   1.15,
    3 * math.pi / 4: 1.08,
    math.pi:       1.20,
    5 * math.pi / 4: 1.03,
    3 * math.pi / 2: 0.97,
    7 * math.pi / 4: 0.97,
}


def taiwan_radius(theta):
    angles = sorted(TAIWAN_SHAPE.keys())
    radii = [TAIWAN_SHAPE[a] for a in angles]
    angles_ext = angles + [a + 2 * math.pi for a in angles]
    radii_ext = radii + radii
    # Simple linear interpolation, good enough for the web view.
    t = theta % (2 * math.pi)
    for i in range(len(angles_ext) - 1):
        if angles_ext[i] <= t <= angles_ext[i + 1]:
            a0, a1 = angles_ext[i], angles_ext[i + 1]
            r0, r1 = radii_ext[i], radii_ext[i + 1]
            return r0 + (r1 - r0) * (t - a0) / (a1 - a0)
    return 1.0


# ---------------------------------------------------------------------------
# Reading the data.
# ---------------------------------------------------------------------------


def load_yearly():
    with YEARLY.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["year"] = int(row["year"])
        row["total_energy_joules"] = float(row["total_energy_joules"])
    return sorted(rows, key=lambda r: r["year"])


def load_events():
    with EVENTS.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["year"] = int(row["year"])
        row["doy"] = int(row["doy"])
        row["mag"] = float(row["mag"])
        row["depth_km"] = float(row["depth_km"])
    return rows


# ---------------------------------------------------------------------------
# Building the rings.
# ---------------------------------------------------------------------------


def smooth_circular(values, window):
    sigma = window / 3
    half = max(1, window * 2)
    n = len(values)
    kernel = []
    total = 0.0
    for k in range(-half, half + 1):
        w = math.exp(-(k * k) / (2 * sigma * sigma))
        kernel.append(w)
        total += w
    kernel = [w / total for w in kernel]
    out = [0.0] * n
    for i in range(n):
        s = 0.0
        for k, w in zip(range(-half, half + 1), kernel):
            s += values[(i + k) % n] * w
        out[i] = s
    return out


def year_envelope(year_events, n_days, global_max_mag):
    fine = [i * n_days / CURVE_RESOLUTION for i in range(CURVE_RESOLUTION)]
    env = [0.0] * CURVE_RESOLUTION
    for e in year_events:
        peak = e["mag"] / global_max_mag
        for i, day in enumerate(fine):
            t = (day - e["doy"]) % n_days
            v = peak / (1 + t / OMORI_C) ** OMORI_P
            if v > env[i]:
                env[i] = v
    samples_per_day = CURVE_RESOLUTION / n_days
    return fine, smooth_circular(env, max(3, round(ROUNDING_DAYS * samples_per_day)))


def base_thickness(yearly):
    ranked = sorted(yearly, key=lambda r: r["total_energy_joules"])
    n = len(ranked)
    out = {}
    for rank, row in enumerate(ranked):
        frac = rank / (n - 1) if n > 1 else 0
        out[row["year"]] = THICKNESS_MIN + frac * (THICKNESS_MAX - THICKNESS_MIN)
    return out


# Colour: pale cream (shallow) to deep brown (deep).
def depth_colour(depth_km):
    frac = min(depth_km, DEPTH_COLOUR_CAP_KM) / DEPTH_COLOUR_CAP_KM
    # Start:  #f0e0bc  ->  End: #5a4022
    def lerp(a, b, t):
        return round(a + (b - a) * t)
    r = lerp(0xf0, 0x5a, frac)
    g = lerp(0xe0, 0x40, frac)
    b = lerp(0xbc, 0x22, frac)
    return f"rgb({r},{g},{b})"


# ---------------------------------------------------------------------------
# Building the Plotly figure.
# ---------------------------------------------------------------------------


def build_figure():
    yearly = load_yearly()
    events = load_events()

    events_by_year = {}
    for e in events:
        events_by_year.setdefault(e["year"], []).append(e)

    global_max_mag = max(e["mag"] for e in events)

    thickness = base_thickness(yearly)

    fig = go.Figure()

    running_outer = PITH_RADIUS

    for row in yearly:
        year = row["year"]
        year_events = events_by_year.get(year, [])
        n_days = 366 if calendar.isleap(year) else 365

        fine, env = year_envelope(year_events, n_days, global_max_mag)

        mean_depth = (
            sum(e["depth_km"] for e in year_events) / len(year_events)
            if year_events else 30.0
        )
        colour = depth_colour(mean_depth)

        base = thickness[year]

        # In Plotly's polar scatter, theta is in degrees, 0 at north.
        # A year's day d maps to angle 90 - d/n_days * 360 so Jan 1 sits at
        # the top and the year runs clockwise, matching plot.py.
        theta_deg = [90 - d / n_days * 360 for d in fine]

        outer_r = []
        inner_r = []
        for i in range(CURVE_RESOLUTION):
            spike = env[i] * SPIKE_MAX
            half = (base + spike) / 2
            centre = running_outer + half
            inner_r.append(centre - half)
            outer_r.append(centre + half)
            # apply taiwan stretch on each angle
            shape = taiwan_radius(math.radians(theta_deg[i]))
            inner_r[-1] *= shape
            outer_r[-1] *= shape

        # Update running_outer to this ring's average outer edge,
        # so the next ring hugs it.
        running_outer = sum(outer_r) / len(outer_r)

        # Close the loop
        theta_closed = theta_deg + [theta_deg[0]]
        outer_closed = outer_r + [outer_r[0]]
        inner_closed = inner_r + [inner_r[0]]

        # Outer boundary, going forward
        theta_ring = theta_closed + list(reversed(theta_closed))
        r_ring = outer_closed + list(reversed(inner_closed))

        fig.add_trace(go.Scatterpolar(
            r=r_ring,
            theta=theta_ring,
            fill="toself",
            mode="lines",
            line=dict(color="#8b6b3d", width=0.5),
            fillcolor=colour,
            name=str(year),
            hoverinfo="name",
        ))

    fig.update_layout(
        title=dict(
            text=("Ten years of Taiwan earthquakes, as tree rings<br>"
                  "<sub>baseline thickness = that year's energy · "
                  "bulge = a day's magnitude (Omori decay) · "
                  "colour = that year's mean depth</sub>"),
            x=0.5, xanchor="center",
        ),
        polar=dict(
            angularaxis=dict(
                direction="clockwise",
                rotation=90,
                showticklabels=False,
                gridcolor="#e6dcc3",
            ),
            radialaxis=dict(showticklabels=False, showgrid=False),
            bgcolor="#ffffff",
        ),
        paper_bgcolor="#ffffff",
        showlegend=False,
        margin=dict(l=40, r=40, t=90, b=40),
    )

    return fig


def main():
    SITE.mkdir(parents=True, exist_ok=True)
    fig = build_figure()
    fig.write_html(OUTPUT, include_plotlyjs="cdn")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()