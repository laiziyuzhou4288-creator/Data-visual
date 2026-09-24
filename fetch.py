# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///

"""
Fetch ten years of Taiwan earthquakes from the USGS, and write the raw reply
out as one file.

The USGS Earthquake Hazards Program publishes a "query" API: you tell it a
time range, a bounding box (min/max latitude and longitude), and a magnitude
threshold, all as URL parameters, and it answers with a GeoJSON file — one
"feature" per earthquake, each with its magnitude, depth, location and time.

Unlike the tidal-stream example, this needs only ONE request: the whole ten
years, in one go. There is no loop over time slots here, because the API
itself accepts a date range instead of asking one moment at a time.

Run it:

    uv run fetch.py

The first run asks the USGS server once and saves the raw reply to data/.
Every run after that finds the file already there and does nothing — so you
never re-fetch by accident, and the script still "works" with no internet as
long as the file from the first run is still in data/.
"""

import json
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# The knobs. Change these to fetch a different place, time range or threshold.
# ---------------------------------------------------------------------------

START_DATE = "2016-01-01"   # YYYY-MM-DD, inclusive
END_DATE = "2025-12-31"     # YYYY-MM-DD, inclusive — ten full calendar years

MIN_MAGNITUDE = 3.5         # ignore anything weaker than this

# A box around Taiwan and its nearby waters, where most of its earthquakes
# actually happen (the east coast offshore is very active).
MIN_LATITUDE = 21.0
MAX_LATITUDE = 26.0
MIN_LONGITUDE = 119.0
MAX_LONGITUDE = 123.0

HERE = Path(__file__).parent                     # this folder, wherever you run it from
DATA = HERE / "data"
OUTPUT = DATA / f"quakes-taiwan-{START_DATE}-to-{END_DATE}.geojson"

# The USGS FDSN Event query endpoint. This is the general-purpose one that
# accepts a custom date range and bounding box — not the same as the
# "last 30 days" feed the earthquakes.py tutorial script used.
URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

# USGS asks that automated requests identify themselves.
HEADERS = {"User-Agent": "student-project (name/course, contact: your-email@example.com)"}

# ---------------------------------------------------------------------------
# Getting the data. Fetch once, keep the file, parse the file.
# ---------------------------------------------------------------------------


def fetch():
    """Ask the USGS for the earthquakes, as raw text. Returns None if unreachable."""
    params = {
        "format": "geojson",
        "starttime": START_DATE,
        "endtime": END_DATE,
        "minmagnitude": MIN_MAGNITUDE,
        "minlatitude": MIN_LATITUDE,
        "maxlatitude": MAX_LATITUDE,
        "minlongitude": MIN_LONGITUDE,
        "maxlongitude": MAX_LONGITUDE,
    }
    try:
        reply = requests.get(URL, params=params, headers=HEADERS, timeout=60)
        reply.raise_for_status()          # turns a bad HTTP status into an exception
    except requests.RequestException as problem:
        print(f"could not fetch ({problem})")
        return None
    return reply.text


def main():
    if OUTPUT.exists():
        print(f"{OUTPUT.name} is already in data/ — not fetching again")
    else:
        print("asking USGS for ten years of Taiwan earthquakes…")
        text = fetch()
        if text is None:
            print("nothing fetched, and nothing cached — stopping")
            return
        DATA.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(text, encoding="utf-8")   # the raw reply, unchanged
        print(f"wrote {OUTPUT.name}")

    # A quick look at what we got, so you know the file is not empty or broken
    # before you go any further. This is the "print it before you plot it" step.
    data = json.loads(OUTPUT.read_text(encoding="utf-8"))
    count = len(data["features"])
    print(f"{count} earthquakes in the file")
    if count:
        first = data["features"][0]["properties"]
        print(f"first record: mag {first['mag']}, {first['place']}")


if __name__ == "__main__":
    main()