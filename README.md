# UK Engagement Map

Animated UK map with pulsing dots sized and coloured by engagement.
Built with Python + Plotly. Outputs an interactive HTML file and optionally an MP4 video.

## Quickstart

```bash
git clone https://github.com/chriswyatt1/uk_engagement.git
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

## Using a different data file

```bash
python3 uk_engagement_map.py --data path/to/mydata.csv
```

## Output

| File | Description |
|------|-------------|
| `output/uk_engagement_map.html` | Interactive map — open in any browser |
| `output/uk_engagement.mp4` | Video export (with `--video` flag) |

## Configuration

Fine-grained animation settings are at the top of `uk_engagement_map.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `N_PULSE_FRAMES` | 16 | Frames per pulse cycle — higher = smoother |
| `PULSE_AMPLITUDE` | 0.30 | How much dots grow/shrink (0 = no pulse) |
| `DOT_SCALE` | 2.0 | Base dot size multiplier |
| `FRAME_DURATION` | 80 ms | Speed of animation playback |
| `VIDEO_FPS` | 12 | Frames per second in MP4 export |
