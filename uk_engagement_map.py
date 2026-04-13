#!/usr/bin/env python3
"""
UK Engagement Map
-----------------
Reads location and engagement data from data/engagement.csv and produces
an animated Plotly map. Dot size scales with engagement. Dots pulse only
when their value changes between periods (or always/never — see options).

Usage:
    python3 uk_engagement_map.py                        # defaults
    python3 uk_engagement_map.py --pulse always         # always pulse
    python3 uk_engagement_map.py --pulse never          # static dots
    python3 uk_engagement_map.py --pulse on-change      # pulse only changed dots (default)
    python3 uk_engagement_map.py --speed fast           # faster animation
    python3 uk_engagement_map.py --dot-scale 3.0        # larger dots
    python3 uk_engagement_map.py --video                # also export MP4
    python3 uk_engagement_map.py --data path/to/file.csv

Requirements:
    pip install -r requirements.txt
"""

import argparse
import math
import os

import pandas as pd
import plotly.graph_objects as go


# ─────────────────────────────────────────────
#  DEFAULTS (overridden by CLI flags)
# ─────────────────────────────────────────────

DEFAULTS = dict(
    data            = "data/engagement.csv",
    pulse           = "on-change",   # always | on-change | never
    dot_scale       = 2.0,           # base dot size multiplier
    pulse_amplitude = 0.35,          # how much changed dots grow/shrink (0-1)
    speed           = "normal",      # slow | normal | fast
    n_pulse_frames  = 16,            # frames per pulse cycle
    video           = False,
)

SPEED_MS = {"slow": 120, "normal": 80, "fast": 45}

OUTPUT_HTML  = "output/uk_engagement_map.html"
OUTPUT_VIDEO = "output/uk_engagement.mp4"
FRAMES_DIR   = "output/_frames"
VIDEO_FPS    = 12


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
        raise ValueError("CSV has no time-period columns.")
    return df, time_cols


# ─────────────────────────────────────────────
#  DOT SIZE HELPERS
# ─────────────────────────────────────────────

def dot_size(engagement_value, scale):
    """Base dot size: larger value -> larger dot (square-root compressed)."""
    return max(6, math.sqrt(engagement_value) * scale)

def pulsed_sizes(eng, prev_eng, pulse_mode, scale, amplitude, t):
    """
    Return (dot_sizes, ring_sizes, ring_opacity) for one animation frame.

    pulse_mode : 'always' | 'on-change' | 'never'
    t          : current phase angle in radians
    """
    sizes      = []
    ring_sizes = []

    for i, e in enumerate(eng):
        base    = dot_size(e, scale)
        changed = (eng[i] != prev_eng[i])

        if pulse_mode == "never" or (pulse_mode == "on-change" and not changed):
            pf = 1.0
        else:
            pf = 1 + amplitude * math.sin(t)

        sizes.append(base * pf)

        rf = 1.7 + 0.55 * math.sin(t + math.pi / 2)
        ring_sizes.append(base * (rf if pf > 1.0 else 1.7))

    ring_opacity = max(0.0, 0.12 + 0.13 * math.sin(t + math.pi / 2))
    if pulse_mode == "never":
        ring_opacity = 0.0

    return sizes, ring_sizes, ring_opacity


# ─────────────────────────────────────────────
#  BUILD FIGURE
# ─────────────────────────────────────────────

def build_figure(df, time_cols, opts):
    lats  = df["lat"].tolist()
    lons  = df["lon"].tolist()
    names = df["name"].tolist()
    max_e = df[time_cols].values.max()

    engagement = {col: df[col].tolist() for col in time_cols}
    scale      = opts.dot_scale
    amplitude  = opts.pulse_amplitude
    pulse_mode = opts.pulse
    n_frames   = DEFAULTS["n_pulse_frames"]
    frame_dur  = SPEED_MS[opts.speed]

    frames       = []
    slider_steps = []

    for step_idx, step_label in enumerate(time_cols):
        eng      = engagement[step_label]
        prev_eng = engagement[time_cols[step_idx - 1]] if step_idx > 0 else eng

        for pulse_i in range(n_frames):
            t = 2 * math.pi * pulse_i / n_frames
            dot_sizes, ring_sizes, ring_opacity = pulsed_sizes(
                eng, prev_eng, pulse_mode, scale, amplitude, t
            )

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

    # Initial state: first time period, no pulse
    init_eng   = engagement[time_cols[0]]
    init_sizes = [dot_size(e, scale) for e in init_eng]

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
                    color="rgba(0,0,0,0)", opacity=0.0,
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
                dict(label="Play", method="animate",
                     args=[None, dict(
                         frame=dict(duration=frame_dur, redraw=True),
                         fromcurrent=True, transition=dict(duration=0),
                     )]),
                dict(label="Pause", method="animate",
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
        print('Video export requires: pip install kaleido "imageio[ffmpeg]"')
        return

    os.makedirs(FRAMES_DIR, exist_ok=True)
    n = len(fig.frames)
    print(f"Rendering {n} frames...")

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

    print(f"Saved video -> {OUTPUT_VIDEO}")


# ─────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Animated UK engagement map.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python3 uk_engagement_map.py
  python3 uk_engagement_map.py --pulse always --speed fast
  python3 uk_engagement_map.py --pulse never --dot-scale 3.0
  python3 uk_engagement_map.py --video
  python3 uk_engagement_map.py --data data/my_data.csv
        """,
    )
    p.add_argument("--data",
                   default=DEFAULTS["data"],
                   help=f"CSV data file (default: {DEFAULTS['data']})")
    p.add_argument("--pulse",
                   default=DEFAULTS["pulse"],
                   choices=["always", "on-change", "never"],
                   help="When to pulse dots (default: on-change)")
    p.add_argument("--dot-scale",
                   default=DEFAULTS["dot_scale"],
                   type=float, metavar="N",
                   help=f"Dot size multiplier (default: {DEFAULTS['dot_scale']})")
    p.add_argument("--pulse-amplitude",
                   default=DEFAULTS["pulse_amplitude"],
                   type=float, metavar="N",
                   help=f"Pulse size variation 0-1 (default: {DEFAULTS['pulse_amplitude']})")
    p.add_argument("--speed",
                   default=DEFAULTS["speed"],
                   choices=["slow", "normal", "fast"],
                   help="Animation speed (default: normal)")
    p.add_argument("--video",
                   action="store_true",
                   help="Also export an MP4 video")
    return p.parse_args()


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    opts = parse_args()
    os.makedirs("output", exist_ok=True)

    print(f"Loading data from {opts.data}...")
    df, time_cols = load_data(opts.data)
    print(f"  {len(df)} locations, {len(time_cols)} periods: {time_cols}")
    print(f"  pulse={opts.pulse}, dot-scale={opts.dot_scale}, speed={opts.speed}")

    print("Building figure...")
    fig = build_figure(df, time_cols, opts)

    fig.write_html(OUTPUT_HTML)
    print(f"Saved -> {OUTPUT_HTML}")

    if opts.video:
        export_video(fig)

    fig.show()


if __name__ == "__main__":
    main()
