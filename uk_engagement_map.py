#!/usr/bin/env python3
"""
UK Engagement Map
-----------------
Reads location and engagement data from data/engagement.csv and produces
an animated Plotly map with pulsing dots.

Usage:
    python3 uk_engagement_map.py              # opens interactive HTML in browser
    python3 uk_engagement_map.py --video      # also exports uk_engagement.mp4

To add a new location: add a row to data/engagement.csv.
To add a new time period: add a column to data/engagement.csv.
No changes to this script are needed.

Requirements:
    pip install -r requirements.txt
"""

import argparse
import math
import os
import pandas as pd
import plotly.graph_objects as go

# ─────────────────────────────────────────────
#  CONFIG — tweak these if needed
# ─────────────────────────────────────────────

DATA_FILE        = "data/engagement.csv"
OUTPUT_HTML      = "output/uk_engagement_map.html"
OUTPUT_VIDEO     = "output/uk_engagement.mp4"
FRAMES_DIR       = "output/_frames"

N_PULSE_FRAMES   = 16    # frames per pulse cycle (higher = smoother)
PULSE_AMPLITUDE  = 0.30  # dot size variation 0–1  (0 = no pulse)
DOT_SCALE        = 2.0   # base dot size multiplier
FRAME_DURATION   = 80    # milliseconds per frame during playback
VIDEO_FPS        = 12    # frames per second in exported MP4


# ─────────────────────────────────────────────
#  LOAD DATA
# ─────────────────────────────────────────────

def load_data(path):
    df = pd.read_csv(path)
    required = {"name", "lat", "lon"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing columns: {missing}")
    time_cols = [c for c in df.columns if c not in required]
    if not time_cols:
        raise ValueError("CSV has no time-period columns (expected at least one beyond name/lat/lon).")
    return df, time_cols


# ─────────────────────────────────────────────
#  BUILD FIGURE
# ─────────────────────────────────────────────

def build_figure(df, time_cols):
    lats  = df["lat"].tolist()
    lons  = df["lon"].tolist()
    names = df["name"].tolist()
    max_e = df[time_cols].values.max()

    engagement = {col: df[col].tolist() for col in time_cols}

    frames = []
    slider_steps = []

    for step_label in time_cols:
        eng = engagement[step_label]

        for pulse_i in range(N_PULSE_FRAMES):
            t = 2 * math.pi * pulse_i / N_PULSE_FRAMES

            pf        = 1 + PULSE_AMPLITUDE * math.sin(t)
            dot_sizes = [max(5, math.sqrt(e) * DOT_SCALE * pf) for e in eng]

            rf           = 1.7 + 0.55 * math.sin(t + math.pi / 2)
            ring_sizes   = [max(8, math.sqrt(e) * DOT_SCALE * rf) for e in eng]
            ring_opacity = max(0, 0.12 + 0.13 * math.sin(t + math.pi / 2))

            frame_name = f"{step_label}_{pulse_i:02d}"
            frames.append(go.Frame(
                name=frame_name,
                data=[
                    go.Scattergeo(
                        lat=lats, lon=lons, mode="markers+text",
                        marker=dict(
                            size=dot_sizes, color=eng,
                            colorscale="Viridis", cmin=0, cmax=max_e,
                            colorbar=dict(
                                title=dict(text="People<br>Engaged", font=dict(size=11)),
                                thickness=12, len=0.6,
                            ),
                            opacity=0.85, line=dict(width=1.5, color="white"),
                        ),
                        text=names, textposition="top center",
                        textfont=dict(size=10, color="#555"),
                        hovertemplate="<b>%{text}</b><br>Engaged: %{marker.color:.0f}<extra></extra>",
                    ),
                    go.Scattergeo(
                        lat=lats, lon=lons, mode="markers",
                        marker=dict(
                            size=ring_sizes, color="rgba(0,0,0,0)",
                            opacity=ring_opacity, line=dict(width=2, color="#7c3aed"),
                        ),
                        hoverinfo="skip",
                    ),
                ],
            ))

        slider_steps.append(dict(
            label=step_label,
            method="animate",
            args=[[f"{step_label}_00"], dict(
                mode="immediate",
                frame=dict(duration=0, redraw=True),
                transition=dict(duration=0),
            )],
        ))

    init_eng   = engagement[time_cols[0]]
    init_sizes = [max(5, math.sqrt(e) * DOT_SCALE) for e in init_eng]

    fig = go.Figure(
        data=[
            go.Scattergeo(
                lat=lats, lon=lons, mode="markers+text",
                marker=dict(
                    size=init_sizes, color=init_eng,
                    colorscale="Viridis", cmin=0, cmax=max_e,
                    colorbar=dict(
                        title=dict(text="People<br>Engaged", font=dict(size=11)),
                        thickness=12, len=0.6,
                    ),
                    opacity=0.85, line=dict(width=1.5, color="white"),
                ),
                text=names, textposition="top center",
                textfont=dict(size=10, color="#555"),
                hovertemplate="<b>%{text}</b><br>Engaged: %{marker.color:.0f}<extra></extra>",
            ),
            go.Scattergeo(
                lat=lats, lon=lons, mode="markers",
                marker=dict(
                    size=[s * 1.7 for s in init_sizes],
                    color="rgba(0,0,0,0)", opacity=0.15,
                    line=dict(width=2, color="#7c3aed"),
                ),
                hoverinfo="skip",
            ),
        ],
        frames=frames,
    )

    fig.update_layout(
        title=dict(text="UK Engagement Map", font=dict(size=16), x=0.5, xanchor="center"),
        geo=dict(
            scope="europe", resolution=50,
            lonaxis=dict(range=[-9, 3]), lataxis=dict(range=[49, 62]),
            showland=True,       landcolor="rgb(242, 237, 230)",
            showcoastlines=True, coastlinecolor="rgb(155, 155, 155)", coastlinewidth=1,
            showocean=True,      oceancolor="rgb(218, 232, 245)",
            showcountries=True,  countrycolor="rgb(200, 200, 200)",
            bgcolor="rgba(0,0,0,0)",
        ),
        updatemenus=[dict(
            type="buttons", showactive=False,
            x=0.05, y=0.0, xanchor="left", yanchor="top",
            buttons=[
                dict(label="▶  Play", method="animate",
                     args=[None, dict(frame=dict(duration=FRAME_DURATION, redraw=True),
                                      fromcurrent=True, transition=dict(duration=0))]),
                dict(label="⏸  Pause", method="animate",
                     args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")]),
            ],
        )],
        sliders=[dict(
            active=0, steps=slider_steps,
            x=0.05, len=0.9, y=0, yanchor="top",
            currentvalue=dict(prefix="Period: ", font=dict(size=12)),
            transition=dict(duration=0),
        )],
        paper_bgcolor="white", showlegend=False,
        height=620, margin=dict(t=50, b=80, l=10, r=90),
    )

    return fig


# ─────────────────────────────────────────────
#  VIDEO EXPORT
# ─────────────────────────────────────────────

def export_video(fig):
    try:
        import imageio
        import plotly.io as pio
    except ImportError:
        print("Video export requires: pip install kaleido \"imageio[ffmpeg]\"")
        return

    os.makedirs(FRAMES_DIR, exist_ok=True)
    n = len(fig.frames)
    print(f"Rendering {n} frames…")

    for i, frame in enumerate(fig.frames):
        f = go.Figure(data=frame.data, layout=fig.layout)
        f.update_layout(updatemenus=[], sliders=[], title="",
                        margin=dict(t=20, b=20, l=10, r=90))
        pio.write_image(f, f"{FRAMES_DIR}/f{i:04d}.png",
                        width=960, height=640, scale=1.5)
        if i % 10 == 0:
            print(f"  {i}/{n}")

    with imageio.get_writer(OUTPUT_VIDEO, fps=VIDEO_FPS) as writer:
        for i in range(n):
            writer.append_data(imageio.imread(f"{FRAMES_DIR}/f{i:04d}.png"))

    print(f"Saved video → {OUTPUT_VIDEO}")


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="UK Engagement Map")
    parser.add_argument("--video", action="store_true",
                        help="Export an MP4 video in addition to HTML")
    parser.add_argument("--data", default=DATA_FILE,
                        help=f"Path to CSV data file (default: {DATA_FILE})")
    args = parser.parse_args()

    os.makedirs("output", exist_ok=True)

    print(f"Loading data from {args.data}…")
    df, time_cols = load_data(args.data)
    print(f"  {len(df)} locations, {len(time_cols)} time periods: {time_cols}")

    print("Building figure…")
    fig = build_figure(df, time_cols)

    fig.write_html(OUTPUT_HTML)
    print(f"Saved interactive map → {OUTPUT_HTML}")

    if args.video:
        export_video(fig)

    fig.show()


if __name__ == "__main__":
    main()
