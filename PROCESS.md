# Process

## Tools

I used Claude to help write `make_web.py` — the interactive HTML page — and the taiwan_radius function in `plot.py`. The rest of plot.py is mine, from the week 3 tutorial scripts. I wrote fetch.py and explore.py assist by Claude and DeepSeek.

## Kept

I kept the Omori's law decay as the shape of the spikes. It is the textbook formula for how aftershock rates fall off after a main shock, and it is what turns a list of magnitudes into a picture that looks like a tree.

I kept three fixes that cut the hover lag: the web build draws at a coarser resolution with wider smoothing to match, the clip-path matplotlib puts on every <path> is stripped out, and each stroke-width reads a CSS variable on its parent <g> so the browser handles the fan-out instead of a JavaScript loop.

## Rejected

I tried Plotly for the web version and rejected it: its polar axes put zero at east, not north, and the filled rings looked nothing like the matplotlib drawing. I used matplotlib and inline SVG instead.

I tried full SVG interaction (hover every segment, change ring width on selection) and rejected it: 20,000 `<path>` elements were too slow. The final page keeps the picture as one PNG and adds a thin gold outline on the selected year.

I tried a wood-tone background and went back to white, because the rings read more clearly against a plain background.