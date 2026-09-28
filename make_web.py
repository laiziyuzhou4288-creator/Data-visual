# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib", "numpy"]
# ///

"""
Build the interactive HTML page for the Taiwan earthquake tree rings.

Run it:

    uv run make_web.py

It writes site/index.html -- open that file in a browser. plot.py is not
touched: everything below only changes how the SAME build_figure() picture
is exported for the browser.

What was making the page stutter (measured, not guessed -- hovering a ring
took ~840 ms before, ~95 ms now):

1. Too many DOM elements. Every point of every ring becomes its own <path>,
   so 800 points x 10 rings = ~8,000 elements. WEB_CURVE_RESOLUTION redraws
   the picture with 400 points per ring (~4,000 elements). Because plot.py's
   smoothing windows are counted in samples, halving the resolution would
   make the rings visibly rougher, so WEB_ROUNDING_DAYS widens them to match.

2. A clip-path on every single segment. matplotlib writes one per <path>;
   4,000 clip operations on every repaint was the biggest single cost.
   strip_path_clips() removes them (the rings already sit inside the axes).

3. JavaScript touching thousands of elements. Focusing a ring now changes
   ONE CSS custom property on that ring's <g>. Every path's stroke-width is
   written as min(calc(<original> * var(--ring-scale, 1)), var(--ring-cap)),
   so the browser fans the change out itself. Hover only changes opacity.

Making an enlarged ring not cover its neighbours: the gap between two rings
is only ~18pt while plot.py's thickest spikes are ~32pt, so growth is
capped (CAP_GAPS x the measured spacing) and the focused ring is moved to
the bottom of the paint order while focused.
"""

import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import plot
from plot import WOOD_BG, build_figure, load_events, load_yearly

HERE = Path(__file__).parent
SITE = HERE / "site"
OUTPUT = SITE / "index.html"
SVG = SITE / "tree-rings.svg"

# Redraw at a coarser resolution just for the web page -- the Gaussian
# smoothing already in plot.py means this loses no visible detail, only
# the number of DOM elements the browser (and our JS) has to deal with.
WEB_CURVE_RESOLUTION = 400
# plot.py's smoothing windows are written in DAYS but applied in samples
# (days x samples-per-day). Halving the samples per day halves the window
# in samples too, so the ring's thickness gets rougher -- neighbouring
# segments jump 2.4x further apart, which shows up as a fringe of spikes
# once a ring is thickened. Widening the windows in days restores the
# same smoothness at the lower resolution.
WEB_ROUNDING_DAYS = 6
WEB_COLOUR_ROUNDING_DAYS = 8

# Focus behaviour. The gap between two neighbouring rings is only ~18pt,
# while plot.py's thickest spikes are already ~32pt wide -- so a ring cannot
# simply be scaled up without limit. Two safeguards:
#   * a per-ring cap (CAP_GAPS x the real ring spacing, measured from the
#     figure below) so an enlarged ring never grows wildly past its lane;
#   * the focused ring is moved to the BOTTOM of the paint order while
#     focused, so wherever it still bleeds into a neighbour's lane, the
#     neighbour is drawn on top of it -- it never covers another ring.
# (Widening plot.RADIAL_STEP does NOT help: the frame rescales with it, so
# spacing as a fraction of the picture stays the same.)
FOCUS_SCALE = 1.8          # how much a clicked ring's stroke grows (before the cap)
UNFOCUSED_SCALE = 0.5      # how much every other ring's stroke shrinks
UNFOCUSED_OPACITY = 0.55
CAP_GAPS = 1.45            # focused stroke never wider than this x ring spacing


def measure_ring_spacing_pt(fig):
    """Distance in SVG points between the centre lines of two neighbouring
    years (using the narrowest part of the Taiwan-shaped outline)."""
    ax = fig.axes[0]
    fig.canvas.draw()
    radius_pt = ax.get_window_extent().width / 2 * 72 / fig.dpi
    unit_pt = radius_pt / ax.get_ylim()[1]
    return plot.RADIAL_STEP * min(plot.TAIWAN_SHAPE.values()) * unit_pt


def add_ring_scale_variable(svg_text):
    """Rewrite every stroke-width: NUMBER in the SVG's inline styles into
    min(calc(NUMBER * var(--ring-scale, 1)), var(--ring-cap, 9999)), so later a single CSS custom
    property change on a ring's own <g> resizes every path inside it --
    the browser does the fan-out, not a JavaScript loop."""
    return re.sub(
        r"stroke-width:\s*([\d.]+)",
        r"stroke-width: min(calc(\1 * var(--ring-scale, 1)), var(--ring-cap, 9999))",
        svg_text,
    )


def strip_path_clips(svg_text):
    """Remove the clip-path="url(#...)" matplotlib puts on every single
    segment. With ~4,000 segments that is 4,000 clip operations on every
    repaint -- measured, it was the single biggest cost of hovering (about
    3x slower). The rings already sit inside the axes, so nothing is lost."""
    return re.sub(r'(<path [^>]*?) clip-path="url\(#[^)]*\)"', r'\1', svg_text)


def year_summary(yearly, events_by_year):
    """{year: {count, max_mag, mean_depth_km}} for the info card."""
    out = {}
    for row in yearly:
        year = row["year"]
        evs = events_by_year.get(year, [])
        if evs:
            max_mag = max(e["mag"] for e in evs)
            mean_depth = sum(e["depth_km"] for e in evs) / len(evs)
        else:
            max_mag = 0.0
            mean_depth = 0.0
        out[year] = {
            "count": len(evs),
            "max_mag": round(max_mag, 1),
            "mean_depth_km": round(mean_depth, 1),
        }
    return out


def inline_svg_with_years(svg_path, years):
    """Tag each ring <g> with data-year and rewrite stroke-width into the
    calc()-based form, then return just the <svg>...</svg> body."""
    text = svg_path.read_text(encoding="utf-8")

    def add_year(match):
        idx = int(match.group(1)) - 1
        year = years[idx] if 0 <= idx < len(years) else ""
        return f'<g id="LineCollection_{match.group(1)}" data-year="{year}"'

    text = re.sub(r'<g id="LineCollection_(\d+)"', add_year, text)
    text = add_ring_scale_variable(text)
    text = strip_path_clips(text)

    start = text.find("<svg")
    end = text.rfind("</svg>") + len("</svg>")
    return text[start:end]


def main():
    yearly = load_yearly()
    events = load_events()

    events_by_year = {}
    for e in events:
        events_by_year.setdefault(e["year"], []).append(e)

    global_max_mag = max(e["mag"] for e in events)

    # Both overrides apply only for this build: plot.py's own numbers, and
    # anyone running `uv run plot.py` for the static PNG, are unaffected.
    plot.CURVE_RESOLUTION = WEB_CURVE_RESOLUTION
    plot.ROUNDING_DAYS = WEB_ROUNDING_DAYS
    plot.COLOUR_ROUNDING_DAYS = WEB_COLOUR_ROUNDING_DAYS

    fig = build_figure(yearly, events_by_year, global_max_mag)
    ring_cap = round(CAP_GAPS * measure_ring_spacing_pt(fig), 1)
    print(f"ring spacing cap: {ring_cap} pt")

    SITE.mkdir(parents=True, exist_ok=True)
    fig.savefig(SVG, format="svg", bbox_inches="tight", facecolor=WOOD_BG)
    plt.close(fig)

    years = [row["year"] for row in yearly]
    svg_inline = inline_svg_with_years(SVG, years)

    year_data = year_summary(yearly, events_by_year)
    year_data_js = json.dumps(year_data)

    year_options = "\n".join(
        f'        <option value="{y}">{y}</option>' for y in years
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ten years of Taiwan earthquakes, as tree rings</title>
  <style>
    * {{ box-sizing: border-box; }}
    [hidden] {{ display: none !important; }}   /* .stats sets display:grid, which otherwise beats the hidden attribute */
    body {{
      margin: 0;
      min-height: 100vh;
      background: {WOOD_BG};
      font-family: Georgia, "Times New Roman", serif;
      color: #4a3520;
    }}
    main {{
      width: min(1180px, 100%);
      margin: 0 auto;
      padding: 1.5rem;
    }}
    h1 {{
      font-size: clamp(1.1rem, 2vw, 1.45rem);
      font-weight: normal;
      text-align: center;
      margin: 0 0 1rem;
      line-height: 1.4;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 250px;
      gap: 1.25rem;
      align-items: start;
    }}
    .visual {{ min-width: 0; }}
    .controls {{
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 0.65rem;
      margin-bottom: 0.75rem;
      font-size: 0.95rem;
    }}
    .controls label {{ opacity: 0.8; }}
    .controls select {{
      font-family: inherit;
      font-size: 0.95rem;
      padding: 5px 9px;
      border: 1px solid #c8b088;
      background: #fff;
      color: #4a3520;
      border-radius: 4px;
      cursor: pointer;
    }}
    .figure {{ width: 100%; line-height: 0; }}
    .figure svg {{
      width: 100%;
      height: auto;
      display: block;
    }}
    .figure svg path {{
      stroke-linejoin: round;
      stroke-linecap: butt;   /* round caps turn a thick ring into a string of beads */
    }}
    .figure svg g[data-year] {{
      cursor: pointer;
      transition: opacity 0.2s ease;
    }}
    .figure svg g[data-year] path {{
      transition: stroke-width 0.2s ease;
    }}
    .figure svg g[data-year].hovered {{
      filter: drop-shadow(0 0 2px rgba(74, 53, 32, 0.45));
    }}
    .info-card {{
      position: sticky;
      top: 1.5rem;
      padding: 1rem 1.05rem;
      background: rgba(255, 250, 238, 0.88);
      border: 1px solid #c8b088;
      border-radius: 8px;
      box-shadow: 0 5px 18px rgba(74, 53, 32, 0.08);
      min-height: 180px;
    }}
    .info-card h2 {{
      margin: 0 0 0.75rem;
      font-size: 1.35rem;
      font-weight: normal;
    }}
    .info-card .hint {{
      margin: 0;
      line-height: 1.55;
      font-size: 0.88rem;
      opacity: 0.72;
    }}
    .stats {{
      display: grid;
      gap: 0.65rem;
      margin: 0;
    }}
    .stat {{
      display: flex;
      justify-content: space-between;
      gap: 0.75rem;
      border-bottom: 1px solid rgba(200, 176, 136, 0.45);
      padding-bottom: 0.45rem;
    }}
    .stat:last-child {{ border-bottom: 0; }}
    .stat dt {{ opacity: 0.72; }}
    .stat dd {{ margin: 0; font-weight: bold; text-align: right; }}
    .selection-note {{
      margin: 0.8rem 0 0;
      font-size: 0.78rem;
      line-height: 1.45;
      opacity: 0.7;
    }}
    p.note {{
      margin: 0.75rem 0 0;
      font-size: 0.85rem;
      text-align: center;
      opacity: 0.85;
    }}
    @media (max-width: 760px) {{
      main {{ padding: 1rem; }}
      .layout {{ grid-template-columns: 1fr; }}
      .info-card {{ position: static; order: -1; min-height: 0; }}
      .stats {{ grid-template-columns: 1fr 1fr; }}
    }}
    @media (max-width: 430px) {{
      .stats {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>Ten years of Taiwan earthquakes, as tree rings</h1>

    <div class="layout">
      <section class="visual">
        <div class="controls">
          <label for="year-select">Focus year:</label>
          <select id="year-select">
            <option value="">All years</option>
{year_options}
          </select>
        </div>

        <div class="figure">
          {svg_inline}
        </div>

        <p class="note">Hover over a ring to inspect that year. Choose a year to focus it.</p>
      </section>

      <aside class="info-card" id="info-card" aria-live="polite">
        <h2 id="info-year">All years</h2>
        <p class="hint" id="info-hint">Hover over a ring or choose a year from the menu to see its earthquake data.</p>
        <dl class="stats" id="stats" hidden>
          <div class="stat"><dt>Earthquakes</dt><dd id="stat-count">—</dd></div>
          <div class="stat"><dt>Largest magnitude</dt><dd id="stat-mag">—</dd></div>
          <div class="stat"><dt>Mean depth</dt><dd id="stat-depth">—</dd></div>
        </dl>
        <p class="selection-note" id="selection-note" hidden>The selected ring stays visually prominent; other years are thinned back so you can inspect its shape.</p>
      </aside>
    </div>
  </main>

  <script>
    const YEAR_DATA = {year_data_js};
    const FOCUS_SCALE = {FOCUS_SCALE};
    const UNFOCUSED_SCALE = {UNFOCUSED_SCALE};
    const UNFOCUSED_OPACITY = {UNFOCUSED_OPACITY};
    const RING_CAP = {ring_cap};

    const yearSelect = document.getElementById('year-select');
    const rings = Array.from(document.querySelectorAll('g[data-year]'))
      .filter(ring => ring.dataset.year);   // drop the colourbar's own line
                                              // collection, which the regex
                                              // above also matched but has
                                              // no year of its own
    const infoYear = document.getElementById('info-year');
    const infoHint = document.getElementById('info-hint');
    const stats = document.getElementById('stats');
    const selectionNote = document.getElementById('selection-note');

    // The resize itself is one CSS custom-property write per ring -- every
    // path inside that ring already reads stroke-width as
    // calc(<original> * var(--ring-scale, 1)), so the browser's own CSS
    // engine fans this out to however many paths are inside, without
    // JavaScript touching a single <path>.
    function setRingScale(ring, scale) {{
      ring.style.setProperty('--ring-scale', scale);
    }}

    // Paint order: SVG has no z-index, so "behind" means earlier in the DOM.
    // Remember where every ring started so the original order can be put
    // back exactly when focus is cleared.
    const originalNext = new Map(rings.map(r => [r, r.nextSibling]));
    const firstRing = rings[0];

    function restorePaintOrder() {{
      rings.forEach(r => {{
        const next = originalNext.get(r);
        if (next && next.parentNode === r.parentNode) r.parentNode.insertBefore(r, next);
      }});
    }}

    function focusYear(year) {{
      restorePaintOrder();
      rings.forEach(ring => {{
        const active = !year || ring.dataset.year === year;
        ring.style.opacity = active ? '1' : String(UNFOCUSED_OPACITY);
        setRingScale(ring, active && year ? FOCUS_SCALE : (year ? UNFOCUSED_SCALE : 1));
        // Only the focused ring is capped; in the all-years view nothing is.
        if (active && year) ring.style.setProperty('--ring-cap', RING_CAP);
        else ring.style.removeProperty('--ring-cap');
        if (active && year && ring !== firstRing) firstRing.parentNode.insertBefore(ring, firstRing);   // move behind the others
      }});
    }}

    function showYearInfo(year) {{
      if (!year || !YEAR_DATA[year]) {{
        infoYear.textContent = 'All years';
        infoHint.hidden = false;
        stats.hidden = true;
        selectionNote.hidden = true;
        return;
      }}

      const data = YEAR_DATA[year];
      infoYear.textContent = year;
      infoHint.hidden = true;
      stats.hidden = false;
      selectionNote.hidden = yearSelect.value !== year;
      document.getElementById('stat-count').textContent = data.count;
      document.getElementById('stat-mag').textContent = 'M ' + data.max_mag;
      document.getElementById('stat-depth').textContent = data.mean_depth_km + ' km';
    }}

    function selectYear(year) {{
      yearSelect.value = year || '';
      focusYear(year || '');
      showYearInfo(year || '');
    }}

    // Hover is a cheap PREVIEW: it only changes opacity (composited, very
    // cheap) and resizes the one ring under the cursor. The expensive part --
    // changing every ring's stroke width -- is left for a click / the menu.
    // (The old handler called focusYear() on every mouseenter, i.e. it
    // rescaled all ten rings each time the cursor crossed one.)
    rings.forEach(ring => {{
      ring.addEventListener('mouseenter', () => {{
        const year = ring.dataset.year;
        const selected = yearSelect.value;
        ring.classList.add('hovered');

        if (selected) {{
          if (year !== selected) ring.style.opacity = '0.85';
        }} else {{
          rings.forEach(r => {{ r.style.opacity = r === ring ? '1' : '0.55'; }});
          setRingScale(ring, 1.25);
        }}
        showYearInfo(year);
      }});

      ring.addEventListener('mouseleave', () => {{
        ring.classList.remove('hovered');
        const selected = yearSelect.value;

        if (selected) {{
          if (ring.dataset.year !== selected) ring.style.opacity = String(UNFOCUSED_OPACITY);
        }} else {{
          rings.forEach(r => {{ r.style.opacity = '1'; }});
          setRingScale(ring, 1);
        }}
        showYearInfo(selected || '');
      }});

      ring.addEventListener('click', () => {{
        selectYear(ring.dataset.year);
      }});
    }});

    yearSelect.addEventListener('change', event => {{
      selectYear(event.target.value);
    }});

    focusYear('');
  </script>
</body>
</html>
"""

    OUTPUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUTPUT}")
    print(f"wrote {SVG}")


if __name__ == "__main__":
    main()