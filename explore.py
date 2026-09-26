# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

"""
Look at the raw earthquake file before doing anything else with it, then turn
1,765 individual earthquakes into one row per year — the shape the tree-ring
picture actually needs.

Run it:

    uv run explore.py

This only reads data/quakes-taiwan-2016-01-01-to-2025-12-31.geojson. It never
touches the network — that is fetch.py's job, and it already ran.
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
RAW = HERE / "data" / "quakes-taiwan-2016-01-01-to-2025-12-31.geojson"
YEARLY_OUTPUT = HERE / "out" / "quakes-by-year.csv"
EVENTS_OUTPUT = HERE / "out" / "quakes-events.csv"

# ---------------------------------------------------------------------------
# Step 1 — print it before you plot it.
# ---------------------------------------------------------------------------


def load_events():
    """Every earthquake as a plain dict: year, month, magnitude, depth."""
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    events = []
    for feature in raw["features"]:
        props = feature["properties"]
        lng, lat, depth_km = feature["geometry"]["coordinates"]
        # USGS gives time as milliseconds since 1970 — Python's time module
        # wants seconds, so divide by 1000 before converting.
        import datetime as dt
        when = dt.datetime.fromtimestamp(props["time"] / 1000, tz=dt.timezone.utc)
        events.append({
            "year": when.year,
            "month": when.month,
            "doy": when.timetuple().tm_yday,   # day of year: Jan 1 = 1, Dec 31 = 365/366
            "mag": props["mag"],
            "depth_km": depth_km,
            "sig": props["sig"],
        })
    return events


def describe(events):
    """The numbers you should look at before designing the picture."""
    mags = [e["mag"] for e in events]
    depths = [e["depth_km"] for e in events]
    by_year = defaultdict(int)
    for e in events:
        by_year[e["year"]] += 1

    print(f"{len(events)} earthquakes total, {min(by_year)}–{max(by_year)}")
    print()
    print("count per year:")
    for year in sorted(by_year):
        print(f"  {year}: {by_year[year]}")
    print()
    print(f"magnitude:  min {min(mags):.1f}  max {max(mags):.1f}  "
          f"average {sum(mags) / len(mags):.2f}")
    print(f"depth (km): min {min(depths):.1f}  max {max(depths):.1f}  "
          f"average {sum(depths) / len(depths):.1f}")


# ---------------------------------------------------------------------------
# Step 2 — trim it into the one-row-per-year shape the picture needs.
# ---------------------------------------------------------------------------


def summarise_by_year(events):
    """One row per year: how many quakes, how strong, how deep, how energetic."""
    by_year = defaultdict(list)
    for e in events:
        by_year[e["year"]].append(e)

    rows = []
    for year in sorted(by_year):
        year_events = by_year[year]
        mags = [e["mag"] for e in year_events]
        # Seismic energy grows exponentially with magnitude, not linearly —
        # this is the standard textbook conversion (energy in joules).
        energy = sum(10 ** (1.5 * m + 4.8) for m in mags)
        rows.append({
            "year": year,
            "count": len(year_events),
            "max_mag": max(mags),
            "mean_depth_km": sum(e["depth_km"] for e in year_events) / len(year_events),
            "total_energy_joules": energy,
        })
    return rows


def main():
    events = load_events()
    describe(events)

    YEARLY_OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    # One row per year — for the width of each ring.
    yearly_rows = summarise_by_year(events)
    with YEARLY_OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(yearly_rows[0]))
        writer.writeheader()
        writer.writerows(yearly_rows)
    print()
    print(f"wrote {YEARLY_OUTPUT.name} — {len(yearly_rows)} years, one row each")

    # One row per earthquake — for the scars on top of the rings. This is
    # the trimmed, five-column version of the 1,765-event raw file: only
    # what the picture actually needs.
    with EVENTS_OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(events[0]))
        writer.writeheader()
        writer.writerows(events)
    print(f"wrote {EVENTS_OUTPUT.name} — {len(events)} earthquakes, one row each")


if __name__ == "__main__":
    main()