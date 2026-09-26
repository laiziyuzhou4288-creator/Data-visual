# Process

## Tools

I used Claude to help write `plot.py`, especially the Omori's law part and the polar plotting. I wrote `fetch.py` and `explore.py` mostly myself, following the week 3 tutorial scripts.

## Kept

I kept the Omori's law decay in `plot.py`. The model wrote most of that function, but I checked it against the tutorial — the shape `1/(t+c)^p` is the textbook formula, not something the model invented.

## Rejected

The first version of `plot.py` the model gave me used `pandas` to read the CSV. I threw it out and used the built-in `csv` module instead, because `pandas` is a big dependency for two small files, and the week 3 tutorial uses `csv` too. I also rejected a version that drew one ring per earthquake — it made the picture unreadable and hid the yearly pattern.