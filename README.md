# UK Engagement Map

Animated UK map with pulsing dots sized and coloured by engagement.
Built with Python + Plotly. Outputs an interactive HTML file and optionally an MP4 video.

## Quickstart

```bash
git clone <your-repo-url>
cd uk-engagement-map

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
python3 uk_engagement_map.py
```

Opens `output/uk_engagement_map.html` in your browser.

## Updating the data

Edit **`data/engagement.csv`** — that's the only file you ever need to change.

```
name,lat,lon,Jan,Feb,Mar,Apr,May
London,51.51,-0.13,120,150,180,200,220
Manchester,53.48,-2.24,80,95,110,130,145
...
```

- **Add a location** — add a row with name, lat, lon, and one value per time period.
- **Add a time period** — add a column. The column header becomes the slider label.
- **Rename time periods** — just rename the column headers (e.g. `Q1,Q2,Q3,Q4` or `2022,2023,2024`).

You can use any number of locations or time periods.

## Exporting a video

Install the extra dependencies first:

```bash
pip install kaleido "imageio[ffmpeg]"
```

Then run with the `--video` flag:

```bash
python3 uk_engagement_map.py --video
```

Saves `output/uk_engagement.mp4`. Insert into PowerPoint via **Insert → Movies → Movie from File**.

## Options

All visual settings are controlled via flags — no need to edit the script.

| Flag | Options | Default | Description |
|------|---------|---------|-------------|
| `--pulse` | `on-change`, `always`, `never` | `on-change` | When to pulse dots |
| `--speed` | `slow`, `normal`, `fast` | `normal` | Animation speed |
| `--dot-scale` | any number | `2.0` | Base dot size multiplier |
| `--pulse-amplitude` | 0–1 | `0.35` | How much pulsing dots grow/shrink |
| `--data` | file path | `data/engagement.csv` | CSV data file to use |
| `--video` | — | off | Also export an MP4 video |

Examples:

```bash
# Default
python3 uk_engagement_map.py

# Pulse only dots that changed, fast animation
python3 uk_engagement_map.py --pulse on-change --speed fast

# No pulsing, larger dots
python3 uk_engagement_map.py --pulse never --dot-scale 3.0

# Everything plus video export
python3 uk_engagement_map.py --pulse always --speed slow --video

# Use a different CSV
python3 uk_engagement_map.py --data data/my_data.csv

# See all options
python3 uk_engagement_map.py --help
```

## Output

| File | Description |
|------|-------------|
| `output/uk_engagement_map.html` | Interactive map — open in any browser |
| `output/uk_engagement.mp4` | Video export (with `--video` flag) |

---

## Mailing list map

`mailing_map.py` reads `data/mailing.tsv` and produces an animated **world map** showing mailing-list subscribers appearing over time. Each subscriber pops up with their organisation name visible as they join.

### Running it

```bash
python3 mailing_map.py
```

Opens `output/mailing_map.html` in your browser. Hit **Play** or drag the slider to step through subscribers chronologically.

### Updating the data

Export your mailing list as a TSV with these columns:

```
Subscribed        Location         Company
10/04/2026 15:12  United Kingdom   University of Oxford - IDDO
...
```

- **Subscribed** — date/time the subscriber joined (day/month/year format)
- **Location** — country name, used as a geocoding fallback
- **Company** — organisation name, used to look up coordinates

Geocoding results are cached in `data/geocache.json` so re-running is fast. To fix a wrongly placed dot, edit the JSON directly — add or update the entry with the correct `[lat, lon]`.

### Short or ambiguous names

Names like `KCL` or `Dur` won't geocode well on their own. Add them to the `GEOCODE_OVERRIDES` dict near the top of `mailing_map.py`:

```python
GEOCODE_OVERRIDES = {
    "KCL":  "King's College London, United Kingdom",
    "Dur":  "University of Durham, United Kingdom",
    ...
}
```

### Options

| Flag | Options / type | Default | Description |
|------|----------------|---------|-------------|
| `--data` | file path | `data/mailing.tsv` | Input TSV file |
| `--map-style` | `vector`, `satellite` | `vector` | Map background: vector tiles or satellite imagery |
| `--speed` | `slow`, `normal`, `fast`, `instant` | `normal` | Animation speed — time between subscribers (1500 / 800 / 300 / 80 ms) |
| `--chart` | flag | off | Overlay a small cumulative sign-up line chart in the top-right corner |
| `--thresholds` | comma-separated integers | `1,2,3,4,5` | Sign-up counts that trigger a colour change on the heatmap dot (see below) |
| `--palette` | palette name or colours | `BlRd` | Dot colour scheme — named palette or custom colours (see below) |

```bash
python3 mailing_map.py --map-style satellite --speed fast
python3 mailing_map.py --speed instant            # blaze through all subscribers
python3 mailing_map.py --chart                    # show cumulative sign-up chart
python3 mailing_map.py --thresholds 1,5,10,25 --palette viridis
python3 mailing_map.py --thresholds 1,3 --palette "steelblue,crimson"
```

### Heatmap colours (`--thresholds` and `--palette`)

Each dot changes colour as more subscribers join from the same location. `--thresholds` sets the sign-up counts at which the colour steps up, and `--palette` controls the colour range.

**Thresholds** — the number of values determines how many colour steps there are:

```
--thresholds 1,2,3,4,5    →  5 colours: 1, 2, 3, 4, 5+   (default)
--thresholds 1,3,5,20     →  4 colours: 1, 3, 5, 20+
--thresholds 1,10          →  2 colours: 1, 10+
```

**Named palettes** (colours run low → high count):

| Name | Description |
|------|-------------|
| `BlRd` | Blue → red (default) |
| `RdBl` | Red → blue |
| `warm` | Yellow → orange → red |
| `cool` | Light blue → purple → pink |
| `viridis` | Purple → teal → yellow |
| `plasma` | Dark blue → orange → yellow |
| `greys` | Light grey → black |

The palette is always sampled to match however many thresholds you give, so every combination works.

**Custom colours** — pass a comma-separated list of CSS colour names or hex codes. The number of colours should match the number of thresholds:

```bash
python3 mailing_map.py --thresholds 1,5,20 --palette "royalblue,orange,crimson"
python3 mailing_map.py --thresholds 1,3,5  --palette "#4ade80,#f59e0b,#ef4444"
```
