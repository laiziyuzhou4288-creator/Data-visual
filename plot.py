# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib"]
# ///

"""
Draw ten years of Taiwan earthquakes as tree rings.

One ring per year, 2016 innermost and 2025 outermost -- the way a real tree
grows outward from its centre. The width of each ring is how much seismic
energy that year released (log-scaled, or 2024's magnitude-7.4 sequence
would swallow every other year). Every earthquake is a scar on its year's
ring: its angle is the month it happened in (January at the top, like a
clock), its size is the magnitude, and its colour is how deep it was.

Run it:

    uv run plot.py

This only reads out/quakes-by-year.csv and out/quakes-events.csv -- both
written by explore.py. It never touches data/ or the network.
"""

import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt

HERE = Path(__file__).parent
YEARLY = HERE / "out" / "quakes-by-year.csv"
EVENTS = HERE / "out" / "quakes-events.csv"
OUTPUT = HERE / "out" / "tree-rings.png"

# ---------------------------------------------------------------------------
# The knobs.
# ---------------------------------------------------------------------------

PITH_RADIUS = 1.0        # radius of the empty centre, like the tree's core
MIN_RING_WIDTH = 0.6      # a quiet year still gets a visible ring
MAX_RING_WIDTH = 1.8      # the busiest year (2024) caps out here

MIN_MARKER_SIZE = 20      # smallest scar (a magnitude-3.5 quake)
MAX_MARKER_SIZE = 220     # largest scar (the magnitude-7.4 quake)

# Three depth bands instead of one continuous colour scale -- with most
# quakes shallow and a handful very deep, a continuous scale would crowd
# almost every point into one end of it.
DEPTH_BANDS = [
    (30, "#e6550d", "shallow (<30 km)"),
    (70, "#3182bd", "mid (30-70 km)"),
    (float("inf"), "#756bb1", "deep (>70 km)"),
]

RING_COLOURS = ["#d9c19a", "#c9ac7c"]   # alternate light/dark, like earlywood/latewood

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
        row["month"] = int(row["month"])
        row["mag"] = float(row["mag"])
        row["depth_km"] = float(row["depth_km"])
    return rows


# ---------------------------------------------------------------------------
# Turning numbers into radii, sizes and colours.
# ---------------------------------------------------------------------------


def ring_widths(yearly):
    """Normalise log(energy) into the MIN_RING_WIDTH..MAX_RING_WIDTH range."""
    logs = [math.log10(row["total_energy_joules"]) for row in yearly]
    low, high = min(logs), max(logs)
    widths = {}
    for row, log_energy in zip(yearly, logs):
        fraction = (log_energy - low) / (high - low)
        widths[row["year"]] = MIN_RING_WIDTH + fraction * (MAX_RING_WIDTH - MIN_RING_WIDTH)
    return widths


def ring_boundaries(yearly, widths):
    """Each year's (inner_radius, outer_radius), stacked from the pith outward."""
    boundaries = {}
    radius = PITH_RADIUS
    for row in yearly:
        year = row["year"]
        boundaries[year] = (radius, radius + widths[year])
        radius += widths[year]
    return boundaries


def marker_size(mag, all_mags):
    low, high = min(all_mags), max(all_mags)
    fraction = (mag - low) / (high - low)
    return MIN_MARKER_SIZE + fraction * (MAX_MARKER_SIZE - MIN_MARKER_SIZE)


def depth_colour(depth_km):
    for limit, colour, _label in DEPTH_BANDS:
        if depth_km < limit:
            return colour
    return DEPTH_BANDS[-1][1]


# ---------------------------------------------------------------------------
# Drawing.
# ---------------------------------------------------------------------------


def draw(yearly, events):
    widths = ring_widths(yearly)
    boundaries = ring_boundaries(yearly, widths)
    all_mags = [e["mag"] for e in events]

    fig, ax = plt.subplots(figsize=(9, 9), subplot_kw={"projection": "polar"})
    ax.set_theta_zero_location("N")   # January points straight up
    ax.set_theta_direction(-1)        # months run clockwise, like a clock face

    theta = [t / 200 * 2 * math.pi for t in range(201)]   # a full circle, densely sampled

    # One filled ring per year.
    for i, row in enumerate(yearly):
        inner, outer = boundaries[row["year"]]
        ax.fill_between(theta, inner, outer, color=RING_COLOURS[i % 2], zorder=1)

    # One scar per earthquake, on top of its year's ring.
    for band_limit, colour, label in DEPTH_BANDS:
        band_events = [e for e in events if depth_colour(e["depth_km"]) == colour]
        if not band_events:
            continue
        angles = [e["month"] / 12 * 2 * math.pi for e in band_events]
        radii = [sum(boundaries[e["year"]]) / 2 for e in band_events]   # middle of the ring
        sizes = [marker_size(e["mag"], all_mags) for e in band_events]
        ax.scatter(angles, radii, s=sizes, color=colour, alpha=0.85,
                   edgecolor="black", linewidth=0.3, zorder=2, label=label)

    # Year labels, one per ring, placed at the 6 o'clock gap so they don't
    # collide with the scars.
    for row in yearly:
        inner, outer = boundaries[row["year"]]
        ax.text(math.pi, (inner + outer) / 2, str(row["year"]),
                ha="center", va="center", fontsize=8, color="#4a3520",
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.75, "pad": 1.5})

    ax.set_ylim(0, PITH_RADIUS + sum(widths.values()) + 0.5)
    ax.set_yticklabels([])            # radius numbers would not mean anything to a reader
    ax.set_xticklabels([])            # month numbers instead of names would need explaining
    ax.spines["polar"].set_visible(False)
    ax.grid(False)
    ax.set_facecolor("white")

    ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.1), title="depth",
              fontsize=8, title_fontsize=9, frameon=False)
    ax.set_title("Ten years of Taiwan earthquakes, as tree rings\n"
                  "ring width = that year's seismic energy - scar size = magnitude",
                  fontsize=11, pad=20)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, dpi=200, bbox_inches="tight")
    print(f"wrote {OUTPUT.name}")
    plt.show()


def main():
    yearly = load_yearly()
    events = load_events()
    draw(yearly, events)


if __name__ == "__main__":
    main()
