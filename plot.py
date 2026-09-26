# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib", "numpy"]
# ///

"""
Draw ten years of Taiwan earthquakes as tree rings -- each ring a solid
silhouette, spiking up sharply on the day of an earthquake and settling back
down slowly afterwards, the way real aftershock sequences actually decay.

That shape is not invented for effect. Real aftershock rates follow Omori's
law: roughly proportional to 1/(t + c)^p, where t is days since the main
shock -- a near-vertical rise on the day itself, then a long, slowly
flattening tail. A year with one clean rupture makes one clean spike; a year
with several sequences makes several, overlapping if they are close together.

One ring per year, 2016 innermost and 2025 outermost. Two things vary:

  - the SHAPE of the ring -- spikes where a bigger earthquake happened,
    spike height set by magnitude, spike decay following Omori's law
  - the COLOUR of the whole ring -- that year's average depth, warm for
    shallow, cool for deep

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

HERE = Path(__file__).parent
YEARLY = HERE / "out" / "quakes-by-year.csv"
EVENTS = HERE / "out" / "quakes-events.csv"
OUTPUT = HERE / "out" / "tree-rings.png"

# ---------------------------------------------------------------------------
# The knobs.
# ---------------------------------------------------------------------------

PITH_RADIUS = 1.0          # radius of the empty centre, like the tree's core
RADIAL_STEP = 1.6          # centre-to-centre distance between consecutive years
BASELINE_THICKNESS = 0.12  # the ring's resting thickness with no earthquake
SPIKE_AMPLITUDE = 1.3      # how far the single biggest possible day swells the ring
ROUNDING_DAYS = 3          # blurs the peak's tip and the sawtooth tail into a smooth curve

# Omori's law: aftershock rate ~ 1 / (t + OMORI_C) ** OMORI_P, t in days
# since the event. A few days' width, not a fraction of one, or the peak
# is a single-pixel needle instead of a readable mountain shape.
OMORI_C = 4.0
OMORI_P = 1.05

CURVE_RESOLUTION = 2000    # points used to draw the curve smoothly

DEPTH_COLOUR_CAP_KM = 100  # depths beyond this are drawn the same colour as the cap
CMAP = plt.get_cmap("coolwarm_r")   # reversed: shallow (low km) -> warm/red, deep -> cool/blue

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
# Building one year's silhouette: a sharp rise on the day of each earthquake,
# an Omori-law tail afterwards, the tallest event winning wherever two
# sequences overlap.
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


def year_silhouette(year_events, n_days, global_max_mag):
    fine_days = np.linspace(0, n_days, CURVE_RESOLUTION, endpoint=False)
    envelope = np.zeros(CURVE_RESOLUTION)

    for e in year_events:
        peak_height = (e["mag"] / global_max_mag) * SPIKE_AMPLITUDE
        # Forward-only distance in days, wrapping around the circle, so an
        # event late in the year still decays smoothly rather than jumping.
        t = (fine_days - e["doy"]) % n_days
        decay = peak_height / (1 + t / OMORI_C) ** OMORI_P
        envelope = np.maximum(envelope, decay)

    # Round off the peak's tip and the sawtooth left by many overlapping
    # aftershock curves, without erasing the day-to-day shape entirely.
    samples_per_day = CURVE_RESOLUTION / n_days
    envelope = smooth_circular(envelope, max(3, round(ROUNDING_DAYS * samples_per_day)))

    return fine_days, envelope


def year_colour(year_events):
    if not year_events:
        return CMAP(0.0)
    mean_depth = sum(e["depth_km"] for e in year_events) / len(year_events)
    fraction = min(mean_depth, DEPTH_COLOUR_CAP_KM) / DEPTH_COLOUR_CAP_KM
    return CMAP(fraction)


# ---------------------------------------------------------------------------
# Drawing.
# ---------------------------------------------------------------------------


def draw(yearly, events_by_year, global_max_mag):
    fig, ax = plt.subplots(figsize=(9, 9), subplot_kw={"projection": "polar"})
    ax.set_theta_zero_location("N")   # Jan 1 points straight up
    ax.set_theta_direction(-1)        # the year runs clockwise, like a clock face

    for i, row in enumerate(yearly):
        year = row["year"]
        year_events = events_by_year.get(year, [])
        n_days = 366 if calendar.isleap(year) else 365

        fine_days, envelope = year_silhouette(year_events, n_days, global_max_mag)
        theta = fine_days / n_days * 2 * math.pi

        centre_radius = PITH_RADIUS + RADIAL_STEP / 2 + i * RADIAL_STEP
        half_thickness = BASELINE_THICKNESS / 2 + envelope / 2
        inner = centre_radius - half_thickness
        outer = centre_radius + half_thickness

        colour = year_colour(year_events)
        ax.fill_between(theta, inner, outer, color=colour, zorder=1,
                        edgecolor="#3a2a18", linewidth=0.3)

        ax.text(math.pi, centre_radius, str(year), ha="center", va="center",
                fontsize=8, color="#4a3520",
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.75, "pad": 1.5})

    max_radius = PITH_RADIUS + RADIAL_STEP * len(yearly) + SPIKE_AMPLITUDE + 0.3
    ax.set_ylim(0, max_radius)
    ax.set_yticklabels([])
    ax.set_xticklabels([])
    ax.spines["polar"].set_visible(False)
    ax.grid(False)
    ax.set_facecolor("white")

    sm = plt.cm.ScalarMappable(cmap=CMAP, norm=plt.Normalize(vmin=0, vmax=DEPTH_COLOUR_CAP_KM))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.035, pad=0.08)
    cbar.set_label(f"mean depth (km, capped at {DEPTH_COLOUR_CAP_KM})", fontsize=8)

    ax.set_title("Ten years of Taiwan earthquakes, as tree rings\n"
                  "spike height = magnitude · spike decay = Omori's law · "
                  "colour = that year's mean depth",
                  fontsize=10.5, pad=24)

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