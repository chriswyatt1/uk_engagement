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
