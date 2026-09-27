# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib", "numpy"]
# ///

"""
Draw ten years of Taiwan earthquakes as tree rings, each ring a wavy ribbon
that thickens symmetrically around its own centre line and shifts colour
continuously -- both driven by the same underlying signal: how much seismic
disturbance is "in the air" on any given day.

That signal follows Omori's law: real aftershock rates decay roughly as
1 / (t + c)^p after a main shock, t in days -- a fast rise on the day
itself, a long, slowly flattening tail. Here it drives two things from the
same source, so they always agree with each other:

  - the ribbon's THICKNESS swells around its centre line near a big day,
    fattest on the day itself, tapering back to a thin resting line
  - the ribbon's COLOUR blends toward that day's depth the same way -- an
    earthquake's colour "bleeds" into the days around it and fades out,
    instead of switching abruptly from one day to the next

A year's baseline thickness (before any spike) also reflects that year's
total seismic energy, so a busy year sits visibly thicker even between
its spikes.

The twelve faint radial lines mark the start of each calendar month, so a
spike can be read as "April" or "December" instead of "day 100".

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
from matplotlib.colors import to_rgb, LinearSegmentedColormap, rgb_to_hsv, hsv_to_rgb

HERE = Path(__file__).parent
YEARLY = HERE / "out" / "quakes-by-year.csv"
EVENTS = HERE / "out" / "quakes-events.csv"
OUTPUT = HERE / "out" / "tree-rings.png"

# ---------------------------------------------------------------------------
# The knobs.
# ---------------------------------------------------------------------------

PITH_RADIUS = 1.0          # radius of the empty centre, like the tree's core
RADIAL_STEP = 4.0          # centre-to-centre distance between consecutive years

BASE_LW_MIN = 2.0          # baseline ribbon thickness (points) for the quietest year
BASE_LW_MAX = 11.0         # baseline ribbon thickness (points) for the busiest year
SPIKE_LW_MAX = 16.0        # extra thickness (points) a full-strength spike adds on top

ROUNDING_DAYS = 3          # blurs the peak tip and sawtooth into a smooth curve

# Omori's law: aftershock rate ~ 1 / (t + OMORI_C) ** OMORI_P, t in days
OMORI_C = 4.0
OMORI_P = 1.05
COLOUR_CONTRAST_GAMMA = 0.4
BLEND_SHARPNESS = 6
COLOUR_ROUNDING_DAYS = 5
SATURATION_BOOST = 1.6     # >1 pushes colours back toward vivid after the blending
                            # and smoothing above inevitably mutes them a little

CURVE_RESOLUTION = 2000    # points used to draw the curve smoothly

DEPTH_COLOUR_CAP_KM = 50   # depths beyond this are drawn the same colour as the cap --
                            # lowered from 100: most real quakes here are under 30km,
                            # so a lower cap spreads the common range across more of
                            # the palette instead of bunching it all at one end

# Wood-tone palette.
# 浅层从饱和的琥珀色起步（不能太接近背景色，不然浅层地震几乎看不见），
# 中段过渡到赭红，深层落到深棕——整条色阶从头到尾都有辨识度。
CMAP = LinearSegmentedColormap.from_list(
    "wood_depth",
    ["#A56A3F",
     "#BA9478",
     "#F0D1A1",
     "#99AA86",
     "#7DA055"],
)
WOOD_BG = "#ffffff"                       # canvas
NEUTRAL_RGB = np.array(to_rgb(WOOD_BG))   # quiet days fade to the same wood tone
MONTH_LINE = "#8a7a5a"                    # twelve month dividers
MONTH_LABEL = "#6a5a3a"                   # month names
YEAR_LABEL = "#4a3520"                    # the year numbers

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
# Omori-law weights, one per event per fine point on the circle.
# ---------------------------------------------------------------------------


def smooth_circular(values, window):
    """A Gaussian-weighted average that wraps around, so the smoothing has
    no seam where the ring closes on itself."""
    sigma = window / 3
    half = max(1, window * 2)
    offsets = np.arange(-half, half + 1)
    kernel = np.exp(-(offsets ** 2) / (2 * sigma ** 2))
    kernel /= kernel.sum()
    padded = np.concatenate([values[-half:], values, values[:half]])
    smoothed = np.convolve(padded, kernel, mode="same")
    return smoothed[half:half + len(values)]


def event_weights(year_events, fine_days, n_days, global_max_mag):
    """One Omori-decay curve per event, each scaled by that event's
    magnitude. Shape: (n_events, CURVE_RESOLUTION)."""
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


# ---------------------------------------------------------------------------
# Turning a year's earthquakes into a thickness envelope and a colour blend.
# ---------------------------------------------------------------------------


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

    # Blending and smoothing both mute colour toward grey -- push saturation
    # back up afterwards so the ribbon reads as vivid, not washed out.
    hsv = rgb_to_hsv(np.clip(colour, 0, 1))
    hsv[:, 1] = np.clip(hsv[:, 1] * SATURATION_BOOST, 0, 1)
    colour = hsv_to_rgb(hsv)

    return colour


def base_linewidths(yearly):
    """Rank years by energy and spread them evenly across BASE_LW_MIN..MAX."""
    ranked = sorted(yearly, key=lambda r: r["total_energy_joules"])
    n = len(ranked)
    widths = {}
    for rank, row in enumerate(ranked):
        fraction = rank / (n - 1) if n > 1 else 0
        widths[row["year"]] = BASE_LW_MIN + fraction * (BASE_LW_MAX - BASE_LW_MIN)
    return widths


# ---------------------------------------------------------------------------
# Month positions.
# ---------------------------------------------------------------------------


def month_angles():
    """Return [(angle_radians, name), ...] for the start of each month."""
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


def draw_month_lines(ax, ring_edge_radius, label_radius):
    for angle, name in month_angles():
        ax.plot([angle, angle], [PITH_RADIUS, ring_edge_radius],
                color=MONTH_LINE, linewidth=0.5, alpha=0.35, zorder=0)
        ax.text(angle, label_radius, name,
                ha="center", va="center", fontsize=8,
                color=MONTH_LABEL, alpha=0.9, zorder=3)


def draw(yearly, events_by_year, global_max_mag):
    base_lw = base_linewidths(yearly)

    fig, ax = plt.subplots(figsize=(9, 9), subplot_kw={"projection": "polar"})
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_facecolor(WOOD_BG)
    fig.patch.set_facecolor(WOOD_BG)

    # The outermost ring's own line can visually render much wider than its
    # data-radius position suggests (linewidth is in points, not data
    # units), so the label needs a generous margin -- not just a hair
    # beyond the last ring's centre -- or it still reads as crowded.
    outer_ring_radius = PITH_RADIUS + RADIAL_STEP * len(yearly)
    ring_edge_radius = outer_ring_radius + 1.2
    label_radius = outer_ring_radius + 2.4
    max_radius = label_radius + 0.6

    # Month dividers first, so they sit under the ribbons.
    draw_month_lines(ax, ring_edge_radius, label_radius)

    for i, row in enumerate(yearly):
        year = row["year"]
        year_events = events_by_year.get(year, [])
        n_days = 366 if calendar.isleap(year) else 365

        fine_days = np.linspace(0, n_days, CURVE_RESOLUTION, endpoint=False)
        weights = event_weights(year_events, fine_days, n_days, global_max_mag)
        envelope = year_envelope(weights, n_days, fine_days)
        colours = year_colours(weights, year_events, n_days)

        fraction = np.clip(envelope, 0, 1)
        linewidths = base_lw[year] + fraction * SPIKE_LW_MAX

        centre_radius = PITH_RADIUS + RADIAL_STEP / 2 + i * RADIAL_STEP
        theta = fine_days / n_days * 2 * math.pi
        points = np.column_stack([theta, np.full(CURVE_RESOLUTION, centre_radius)])
        points = np.vstack([points, points[0]])
        segments = np.stack([points[:-1], points[1:]], axis=1)

        seg_colours = np.vstack([colours, colours[0]])[:-1]
        seg_linewidths = np.append(linewidths, linewidths[0])[:-1]

        ring = LineCollection(segments, colors=seg_colours, linewidths=seg_linewidths,
                              capstyle="butt", joinstyle="round", zorder=1)
        ax.add_collection(ring)

        ax.text(math.pi, centre_radius, str(year), ha="center", va="center",
                fontsize=8, color=YEAR_LABEL,
                bbox={"facecolor": WOOD_BG, "edgecolor": "none", "alpha": 0.85, "pad": 1.5})

    ax.set_ylim(0, max_radius)
    ax.set_yticklabels([])
    ax.set_xticklabels([])
    ax.spines["polar"].set_visible(False)
    ax.grid(False)

    sm = plt.cm.ScalarMappable(cmap=CMAP, norm=plt.Normalize(vmin=0, vmax=DEPTH_COLOUR_CAP_KM))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.035, pad=0.08)
    cbar.set_label(f"depth (km, capped at {DEPTH_COLOUR_CAP_KM})", fontsize=8)

    ax.set_title("Ten years of Taiwan earthquakes, as tree rings\n"
                  "baseline thickness = that year's energy · bulge = a day's magnitude "
                  "(Omori decay) · colour = nearby depth",
                  fontsize=10, pad=24)

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