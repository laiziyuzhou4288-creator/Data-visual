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

Run it:

    uv run plot.py

This only reads out/quakes-by-year.csv and out/quakes-events.csv -- both
written by explore.py. It never touches data/ or the network.
"""

import calendar
import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.colors import to_rgb

HERE = Path(__file__).parent
YEARLY = HERE / "out" / "quakes-by-year.csv"
EVENTS = HERE / "out" / "quakes-events.csv"
OUTPUT = HERE / "out" / "tree-rings.png"

# ---------------------------------------------------------------------------
# The knobs.
# ---------------------------------------------------------------------------

PITH_RADIUS = 1.0          # radius of the empty centre, like the tree's core
RADIAL_STEP = 1.6          # centre-to-centre distance between consecutive years

BASE_LW_MIN = 2.0          # baseline ribbon thickness (points) for the quietest year
BASE_LW_MAX = 11.0         # baseline ribbon thickness (points) for the busiest year
SPIKE_LW_MAX = 16.0        # extra thickness (points) a full-strength spike adds on top

ROUNDING_DAYS = 3          # blurs the peak tip and sawtooth into a smooth curve

# Omori's law: aftershock rate ~ 1 / (t + OMORI_C) ** OMORI_P, t in days
# since the event. Shared by both the thickness spike and the colour blend,
# so a ribbon's bulge and its colour always agree about how "close" a day is
# to an earthquake.
OMORI_C = 4.0
OMORI_P = 1.05
COLOUR_CONTRAST_GAMMA = 0.4   # < 1 sharpens the fade to neutral -- bigger contrast,
                               # less of a long faint tail near each event
BLEND_SHARPNESS = 6           # how strongly the nearest event dominates the colour --
                               # high enough that hue barely blends except right at a
                               # crossover between two nearby events, where it eases
                               # smoothly from one to the other instead of jumping
COLOUR_ROUNDING_DAYS = 5      # extra smoothing pass on the finished colour itself, so
                               # a dense year (many quakes close together) still reads
                               # as smooth bands instead of adjacent blocks

CURVE_RESOLUTION = 2000    # points used to draw the curve smoothly

DEPTH_COLOUR_CAP_KM = 100  # depths beyond this are drawn the same colour as the cap
CMAP = plt.get_cmap("coolwarm")   # coolwarm: shallow (low km) -> cool/blue, deep -> warm/red
NEUTRAL_RGB = np.array(to_rgb("#e8dcc3"))   # pale wood tone a quiet day fades toward

# ---------------------------------------------------------------------------
# Reading the trimmed data. fetch.py and explore.py already did the work.
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
# One shared Omori-law weight per event, per fine point on the circle --
# used to build BOTH the thickness envelope and the colour blend, so they
# always move together.
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
        t = (fine_days - e["doy"]) % n_days   # forward-only, wraps around the circle
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
    event_rgb = np.array([depth_to_rgb(e["depth_km"]) for e in year_events])   # (n_events, 3)

    # How concentrated the colour is (vs fading to the neutral tone) comes
    # from the strongest single event at each point -- a sharp contrast
    # between "near an earthquake" and "quiet".
    strength = weights.max(axis=0)
    alpha = np.clip(strength, 0, 1) ** COLOUR_CONTRAST_GAMMA

    # Which HUE to show is a softened weighted blend across nearby events --
    # sharpened so the closest event dominates almost completely, but not
    # with a hard cutoff, so two overlapping sequences ease from one colour
    # into the other across their crossover instead of jumping.
    sharp_weights = weights ** BLEND_SHARPNESS
    totals = sharp_weights.sum(axis=0)
    totals[totals == 0] = 1   # avoid dividing by zero where nothing is nearby at all
    hue_rgb = (sharp_weights.T @ event_rgb) / totals[:, None]

    colour = alpha[:, None] * hue_rgb + (1 - alpha[:, None]) * NEUTRAL_RGB

    # A dense year packs many events close together, so the blend above can
    # still change from one dominant event to the next every day or two --
    # smooth the finished colour itself so it always reads as continuous
    # bands, no matter how crowded the year is.
    samples_per_day = CURVE_RESOLUTION / n_days
    window = max(3, round(COLOUR_ROUNDING_DAYS * samples_per_day))
    for channel in range(3):
        colour[:, channel] = smooth_circular(colour[:, channel], window)

    return colour


def base_linewidths(yearly):
    """Rank years by energy and spread them evenly across BASE_LW_MIN..MAX --
    guarantees ten visibly different thicknesses regardless of how close (or
    how far apart) the real energy values happen to be. Trades exact
    proportionality for a difference you can actually see at a glance."""
    ranked = sorted(yearly, key=lambda r: r["total_energy_joules"])
    n = len(ranked)
    widths = {}
    for rank, row in enumerate(ranked):
        fraction = rank / (n - 1) if n > 1 else 0
        widths[row["year"]] = BASE_LW_MIN + fraction * (BASE_LW_MAX - BASE_LW_MIN)
    return widths


# ---------------------------------------------------------------------------
# Drawing.
# ---------------------------------------------------------------------------


def draw(yearly, events_by_year, global_max_mag):
    base_lw = base_linewidths(yearly)

    fig, ax = plt.subplots(figsize=(9, 9), subplot_kw={"projection": "polar"})
    ax.set_theta_zero_location("N")   # Jan 1 points straight up
    ax.set_theta_direction(-1)        # the year runs clockwise, like a clock face

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
        points = np.vstack([points, points[0]])   # close the loop, no seam at year end
        segments = np.stack([points[:-1], points[1:]], axis=1)

        seg_colours = np.vstack([colours, colours[0]])[:-1]
        seg_linewidths = np.append(linewidths, linewidths[0])[:-1]

        ring = LineCollection(segments, colors=seg_colours, linewidths=seg_linewidths,
                              capstyle="butt", joinstyle="round", zorder=1)
        ax.add_collection(ring)

        ax.text(math.pi, centre_radius, str(year), ha="center", va="center",
                fontsize=8, color="#4a3520",
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.75, "pad": 1.5})

    max_radius = PITH_RADIUS + RADIAL_STEP * len(yearly) + 0.6
    ax.set_ylim(0, max_radius)
    ax.set_yticklabels([])
    ax.set_xticklabels([])
    ax.spines["polar"].set_visible(False)
    ax.grid(False)
    ax.set_facecolor("white")

    sm = plt.cm.ScalarMappable(cmap=CMAP, norm=plt.Normalize(vmin=0, vmax=DEPTH_COLOUR_CAP_KM))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.035, pad=0.08)
    cbar.set_label(f"depth (km, capped at {DEPTH_COLOUR_CAP_KM})", fontsize=8)

    ax.set_title("Ten years of Taiwan earthquakes, as tree rings\n"
                  "baseline thickness = that year's energy · bulge = a day's magnitude "
                  "(Omori decay) · colour = nearby depth",
                  fontsize=10, pad=24)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, dpi=200, bbox_inches="tight")
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