# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib", "numpy"]
# ///

"""
Draw ten years of Taiwan earthquakes as trees growth rings, each ring a wavy ribbon
that thickens symmetrically around its own centre line and shifts colour
continuously -- both driven by the same underlying signal: how much seismic
disturbance is "in the air" on any given day.

That signal follows Omori's law: real aftershock rates decay roughly as
1 / (t + c)^p after a main shock, t in days.

A year's baseline thickness reflects that year's total seismic energy. A
year's centre line is also nudged outward wherever the previous year bulged.
The nudge decays year by year and is recentred.

The whole thing is squashed into a rough Taiwan silhouette.

Run it:

    uv run plot.py

This only reads out/quakes-by-year.csv and out/quakes-events.csv -- both
written by explore.py. It never touches data/ or the network.
"""

import calendar
import csv
import datetime as dt
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.colors import to_rgb, LinearSegmentedColormap

HERE = Path(__file__).parent
YEARLY = HERE / "out" / "quakes-by-year.csv"
EVENTS = HERE / "out" / "quakes-events.csv"
OUTPUT = HERE / "out" / "annual-rings.png"

# ---------------------------------------------------------------------------
# The knobs.
# ---------------------------------------------------------------------------

PITH_RADIUS = 1.0
RADIAL_STEP = 3.0

BASE_LW_MIN = 2.0
BASE_LW_MAX = 11.0
SPIKE_LW_MAX = 16.0

GROWTH_DECAY = 0.4
GROWTH_TRANSFER = 0.08

ROUNDING_DAYS = 3

OMORI_C = 4.0
OMORI_P = 1.05
COLOUR_CONTRAST_GAMMA = 0.4
BLEND_SHARPNESS = 6
COLOUR_ROUNDING_DAYS = 5

CURVE_RESOLUTION = 800

DEPTH_COLOUR_CAP_KM = 100

CMAP = LinearSegmentedColormap.from_list(
    "wood_depth",
    ["#8d9e5b",
     "#c0c971",
     "#e8d376",
     "#a7670c",
     "#811901"],
)
WOOD_BG = "#ffffff"
NEUTRAL_RGB = np.array(to_rgb("#f0e2c8"))
MONTH_LINE = "#8a7a5a"
MONTH_LABEL = "#6a5a3a"
YEAR_LABEL = "#4a3520"
BARK = "#c8b088"

# Taiwan silhouette (gentle so nothing gets clipped).
TAIWAN_SHAPE = {
    0:             1.00,   # N
    math.pi / 4:   1.06,   # NE
    math.pi / 2:   1.15,   # E
    3 * math.pi / 4: 1.08, # SE
    math.pi:       1.20,   # S
    5 * math.pi / 4: 1.03, # SW
    3 * math.pi / 2: 0.97, # W
    7 * math.pi / 4: 0.97, # NW
}


def taiwan_radius(theta):
    angles = sorted(TAIWAN_SHAPE.keys())
    radii = [TAIWAN_SHAPE[a] for a in angles]
    angles_ext = angles + [a + 2 * math.pi for a in angles]
    radii_ext = radii + radii
    return float(np.interp(theta, angles_ext, radii_ext))


# ---------------------------------------------------------------------------
# Reading the trimmed data.
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
# Omori-law weights.
# ---------------------------------------------------------------------------


def smooth_circular(values, window):
    sigma = window / 3
    half = max(1, window * 2)
    offsets = np.arange(-half, half + 1)
    kernel = np.exp(-(offsets ** 2) / (2 * sigma ** 2))
    kernel /= kernel.sum()
    padded = np.concatenate([values[-half:], values, values[:half]])
    smoothed = np.convolve(padded, kernel, mode="same")
    return smoothed[half:half + len(values)]


def event_weights(year_events, fine_days, n_days, global_max_mag):
    if not year_events:
        return np.zeros((0, len(fine_days)))
    weights = np.empty((len(year_events), len(fine_days)))
    for idx, e in enumerate(year_events):
        peak_height = e["mag"] / global_max_mag
        t = (fine_days - e["doy"]) % n_days
        weights[idx] = peak_height / (1 + t / OMORI_C) ** OMORI_P
    return weights


def depth_to_rgb(depth_km):
    fraction = min(depth_km, DEPTH_COLOUR_CAP_KM) / DEPTH_COLOUR_CAP_KM
    return np.array(CMAP(fraction)[:3])


def year_envelope(weights, n_days, fine_days):
    if weights.shape[0] == 0:
        return np.zeros(len(fine_days))
    envelope = weights.max(axis=0)
    samples_per_day = CURVE_RESOLUTION / n_days
    return smooth_circular(envelope, max(3, round(ROUNDING_DAYS * samples_per_day)))


def year_colours(weights, year_events, n_days):
    if weights.shape[0] == 0:
        return np.tile(NEUTRAL_RGB, (CURVE_RESOLUTION, 1))
    event_rgb = np.array([depth_to_rgb(e["depth_km"]) for e in year_events])

    strength = weights.max(axis=0)
    alpha = np.clip(strength, 0, 1) ** COLOUR_CONTRAST_GAMMA

    sharp_weights = weights ** BLEND_SHARPNESS
    totals = sharp_weights.sum(axis=0)
    totals[totals == 0] = 1
    hue_rgb = (sharp_weights.T @ event_rgb) / totals[:, None]

    colour = alpha[:, None] * hue_rgb + (1 - alpha[:, None]) * NEUTRAL_RGB

    samples_per_day = CURVE_RESOLUTION / n_days
    window = max(3, round(COLOUR_ROUNDING_DAYS * samples_per_day))
    for channel in range(3):
        colour[:, channel] = smooth_circular(colour[:, channel], window)

    return colour


def base_linewidths(yearly):
    ranked = sorted(yearly, key=lambda r: r["total_energy_joules"])
    n = len(ranked)
    widths = {}
    for rank, row in enumerate(ranked):
        fraction = rank / (n - 1) if n > 1 else 0
        widths[row["year"]] = BASE_LW_MIN + fraction * (BASE_LW_MAX - BASE_LW_MIN)
    return widths


def month_angles():
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    out = []
    for m, name in enumerate(names, start=1):
        doy = dt.date(2023, m, 1).timetuple().tm_yday - 1
        angle = doy / 365 * 2 * math.pi
        out.append((angle, name))
    return out


# ---------------------------------------------------------------------------
# Drawing.
# ---------------------------------------------------------------------------


def draw_month_lines(ax, base_max_radius):
    """base_max_radius is the un-squashed radius; each line stretches by
    taiwan_radius(angle) itself."""
    for angle, name in month_angles():
        shape = taiwan_radius(angle)
        ax.plot([angle, angle], [PITH_RADIUS, base_max_radius * shape* 1.08],
                color=MONTH_LINE, linewidth=0.5, alpha=0.35, zorder=0)
        ax.text(angle, base_max_radius * shape * 1.10, name,
                ha="center", va="center", fontsize=7,
                color=MONTH_LABEL, alpha=0.85, zorder=3)


def draw_bark_rings(ax, outer_edge, base_max_radius):
    bark_gap = 0.18
    bark_count = 5
    full_circle = np.linspace(0, 2 * math.pi, 400)
    shape = np.array([taiwan_radius(t) for t in full_circle])
    for k in range(1, bark_count + 1):
        r = outer_edge + k * bark_gap
        if r >= base_max_radius - 0.05:
            break
        ax.plot(full_circle, r * shape,
                color=BARK, linewidth=0.5, alpha=0.35, zorder=0)


def build_figure(yearly, events_by_year, global_max_mag):
    """Build the matplotlib figure. Shared by plot.py and make_web.py."""
    base_lw = base_linewidths(yearly)

    fig, ax = plt.subplots(figsize=(9, 9), subplot_kw={"projection": "polar"})
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_facecolor(WOOD_BG)
    fig.patch.set_facecolor(WOOD_BG)

    # Un-squashed radius for the axes; the plotted limit is the squashed one,
    # so the bulging direction still fits inside the frame.
    base_max_radius = 30.0   # 固定值，不跟 RADIAL_STEP 变
    max_shape = max(TAIWAN_SHAPE.values())
    max_radius = base_max_radius * max_shape

    draw_month_lines(ax, base_max_radius)

    cumulative_offset = np.zeros(CURVE_RESOLUTION)

    for i, row in enumerate(yearly):
        year = row["year"]
        year_events = events_by_year.get(year, [])
        n_days = 366 if calendar.isleap(year) else 365

        fine_days = np.linspace(0, n_days, CURVE_RESOLUTION, endpoint=False)
        weights = event_weights(year_events, fine_days, n_days, global_max_mag)
        envelope = year_envelope(weights, n_days, fine_days)
        colours = year_colours(weights, year_events, n_days)

        theta = fine_days / n_days * 2 * math.pi
        shape = np.array([taiwan_radius(t) for t in theta])

        fraction = np.clip(envelope, 0, 1)
        linewidths = (base_lw[year] + fraction * SPIKE_LW_MAX) * shape

        base_radius = PITH_RADIUS + RADIAL_STEP / 2 + i * RADIAL_STEP
        centre_radius = base_radius + cumulative_offset
        centre_radius = centre_radius * shape

        points = np.column_stack([theta, centre_radius])
        points = np.vstack([points, points[0]])
        segments = np.stack([points[:-1], points[1:]], axis=1)

        seg_colours = np.vstack([colours, colours[0]])[:-1]
        seg_linewidths = np.append(linewidths, linewidths[0])[:-1]

        ring = LineCollection(segments, colors=seg_colours, linewidths=seg_linewidths,
                              capstyle="butt", joinstyle="round", zorder=1)
        ax.add_collection(ring)

        label_idx = int(np.argmin(np.abs(theta - math.pi)))
        label_radius = float(centre_radius[label_idx])
        ax.text(math.pi, label_radius, str(year), ha="center", va="center",
                fontsize=8, color=YEAR_LABEL,
                bbox={"facecolor": WOOD_BG, "edgecolor": "none", "alpha": 0.85, "pad": 1.5})

        cumulative_offset = (cumulative_offset * GROWTH_DECAY
                             + envelope * (RADIAL_STEP * GROWTH_TRANSFER))
        cumulative_offset -= np.mean(cumulative_offset)

    outer_edge = base_max_radius - 1.4
    draw_bark_rings(ax, outer_edge, base_max_radius)

    ax.set_ylim(0, max_radius)
    ax.set_yticklabels([])
    ax.set_xticklabels([])
    ax.spines["polar"].set_visible(False)
    ax.grid(False)

    sm = plt.cm.ScalarMappable(cmap=CMAP, norm=plt.Normalize(vmin=0, vmax=DEPTH_COLOUR_CAP_KM))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.035, pad=0.08)
    cbar.set_label(f"depth (km, capped at {DEPTH_COLOUR_CAP_KM})", fontsize=8)

    ax.set_title("Ten years of Taiwan earthquakes in annual rings\n"
                  "baseline thickness = that year's energy · bulge = a day's magnitude "
                  "(Omori decay) · colour = nearby depth",
                  fontsize=10, pad=24)

    return fig


def draw(yearly, events_by_year, global_max_mag):
    fig = build_figure(yearly, events_by_year, global_max_mag)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, dpi=200, bbox_inches="tight", facecolor=WOOD_BG)
    print(f"wrote {OUTPUT.name}")
    plt.show()


def main():
    yearly = load_yearly()
    events = load_events()

    events_by_year = {}
    for e in events:
        events_by_year.setdefault(e["year"], []).append(e)

    global_max_mag = max(e["mag"] for e in events)

    draw(yearly, events_by_year, global_max_mag)


if __name__ == "__main__":
    main()