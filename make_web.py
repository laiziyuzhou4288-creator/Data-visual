# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib", "numpy"]
# ///

"""
Build the interactive HTML page for the Taiwan earthquake tree rings.

Run it:

    uv run make_web.py

It writes site/index.html -- open that file in a browser.

The SVG comes from the same build_figure() that plot.py uses, so the
picture is identical. We inline the SVG (not <object>) so JavaScript can
reach each ring <g>, tag the rings with data-year, and wire up hover,
tooltip, and the year selector.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import json
import re
from pathlib import Path

from plot import WOOD_BG, build_figure, load_events, load_yearly

HERE = Path(__file__).parent
SITE = HERE / "site"
OUTPUT = SITE / "index.html"
SVG = SITE / "tree-rings.svg"


def year_summary(yearly, events_by_year):
    """A dict of {year: {count, max_mag, mean_depth_km}} for the tooltip."""
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
    """Read the SVG matplotlib wrote, tag each ring <g> with data-year,
    and return just the <svg>...</svg> body so it can be pasted into the
    HTML directly (which is what lets JS see the rings)."""
    text = svg_path.read_text(encoding="utf-8")

    def add_year(match):
        idx = int(match.group(1)) - 1
        year = years[idx] if 0 <= idx < len(years) else ""
        return f'<g id="LineCollection_{match.group(1)}" data-year="{year}"'

    text = re.sub(r'<g id="LineCollection_(\d+)"', add_year, text)

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

    fig = build_figure(yearly, events_by_year, global_max_mag)

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
      stroke-linecap: round;
    }}
    .figure svg g[data-year] {{
      cursor: pointer;
      transition: opacity 0.2s ease;
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
    const yearSelect = document.getElementById('year-select');
    const rings = Array.from(document.querySelectorAll('g[data-year]'));
    const infoYear = document.getElementById('info-year');
    const infoHint = document.getElementById('info-hint');
    const stats = document.getElementById('stats');
    const selectionNote = document.getElementById('selection-note');

    // Save each path's original stroke width. This lets focus mode make a
    // ring thicker/thinner without destroying the magnitude/energy encoding
    // already present in the SVG.
    rings.forEach(ring => {{
      ring.querySelectorAll('path, line, polyline').forEach(el => {{
        const width = parseFloat(el.getAttribute('stroke-width')) || parseFloat(getComputedStyle(el).strokeWidth) || 1;
        el.dataset.baseWidth = width;
      }});
    }});

    function setRingWidth(ring, scale) {{
      ring.querySelectorAll('path, line, polyline').forEach(el => {{
        const base = parseFloat(el.dataset.baseWidth);
        if (Number.isFinite(base)) {{
          el.style.strokeWidth = (base * scale).toFixed(3);
        }}
      }});
    }}

    function clearRingWidth(ring) {{
      ring.querySelectorAll('path, line, polyline').forEach(el => {{
        el.style.strokeWidth = '';
      }});
    }}

    function focusYear(year) {{
      rings.forEach(ring => {{
        const ringYear = ring.dataset.year;
        const active = !year || ringYear === year;
        ring.style.opacity = active ? '1' : '0.42';
        setRingWidth(ring, active && year ? 1.9 : (year ? 0.58 : 1));
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

    // Hovering temporarily emphasizes the ring and updates the fixed info card.
    // Unlike the old mouse-following tooltip, the information stays readable
    // while the cursor moves around the large SVG.
    rings.forEach(ring => {{
      ring.addEventListener('mouseenter', () => {{
        const year = ring.dataset.year;
        ring.classList.add('hovered');

        if (yearSelect.value) {{
          // Keep the selected year dominant, but still make the hovered ring visible.
          if (year === yearSelect.value) {{
            setRingWidth(ring, 2.25);
          }} else {{
            ring.style.opacity = '0.72';
            setRingWidth(ring, 0.85);
          }}
        }} else {{
          focusYear(year);
          setRingWidth(ring, 1.25);
        }}
        showYearInfo(year);
      }});

      ring.addEventListener('mouseleave', () => {{
        ring.classList.remove('hovered');
        const selected = yearSelect.value;
        focusYear(selected);
        showYearInfo(selected || '');
      }});

      ring.addEventListener('click', () => {{
        const year = ring.dataset.year;
        selectYear(year);
      }});
    }});

    yearSelect.addEventListener('change', event => {{
      selectYear(event.target.value);
    }});

    // Initial state: all years visible, original stroke widths preserved.
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