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
    python3 uk_engagement_map.py --map-style satellite  # satellite imagery background
    python3 uk_engagement_map.py --map-style vector     # classic vector map (default)
    python3 uk_engagement_map.py --video                # also export MP4
    python3 uk_engagement_map.py --data path/to/file.csv

Requirements:
    pip install -r requirements.txt
"""

import argparse
import json
import math
import os
import warnings

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
    map_style       = "vector",      # vector | satellite
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
    """Base dot size: larger value -> larger dot (square-root compressed).
    Returns 0 for zero/negative engagement so the city is invisible."""
    if engagement_value <= 0:
        return 0
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
        if e <= 0:
            # City has no engagement this period — keep it invisible
            sizes.append(0)
            ring_sizes.append(0)
            continue

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
    satellite  = (opts.map_style == "satellite")
    if satellite:
        # Scattermapbox is deprecated in favour of Scattermap, but Scattermap
        # doesn't support Plotly.redraw()-driven animation. Suppress the noise.
        warnings.filterwarnings("ignore", message=".*scattermapbox.*",
                                category=DeprecationWarning)

    def dot_traces(dot_sizes, ring_sizes, ring_opacity, eng, texts):
        """Return (main_trace, ring_trace) for the chosen map style.
        `texts` is a per-city label list — empty string hides the label."""
        label_color = "white" if satellite else "#555"
        cbar_color  = "white" if satellite else "#333"
        colorbar = dict(
            title=dict(text="People<br>Engaged", font=dict(size=11, color=cbar_color)),
            thickness=12, len=0.6,
            tickfont=dict(color=cbar_color),
        )
        if satellite:
            main = go.Scattermapbox(
                lat=lats, lon=lons, mode="markers+text",
                marker=dict(
                    size=dot_sizes, color=eng,
                    colorscale="Plasma", cmin=0, cmax=max_e,
                    colorbar=colorbar,
                    opacity=0.9,
                ),
                text=texts, textposition="top right",
                textfont=dict(size=11, color=label_color),
                hovertemplate="<b>%{text}</b><br>Engaged: %{marker.color:.0f}<extra></extra>",
            )
            # Scattermapbox has no marker.line, so a filled ring looks like a
            # halo. Keep the trace (to maintain trace count) but always invisible.
            ring = go.Scattermapbox(
                lat=lats, lon=lons, mode="markers",
                marker=dict(size=1, color="#a78bfa", opacity=0),
                hoverinfo="skip",
            )
        else:
            main = go.Scattergeo(
                lat=lats, lon=lons, mode="markers+text",
                marker=dict(
                    size=dot_sizes, color=eng,
                    colorscale="Viridis", cmin=0, cmax=max_e,
                    colorbar=colorbar,
                    opacity=0.85, line=dict(width=1.5, color="white"),
                ),
                text=texts, textposition="top center",
                textfont=dict(size=10, color=label_color),
                hovertemplate="<b>%{text}</b><br>Engaged: %{marker.color:.0f}<extra></extra>",
            )
            ring = go.Scattergeo(
                lat=lats, lon=lons, mode="markers",
                marker=dict(
                    size=ring_sizes, color="rgba(0,0,0,0)",
                    opacity=ring_opacity, line=dict(width=2, color="#7c3aed"),
                ),
                hoverinfo="skip",
            )
        return main, ring

    # Satellite: Scattermapbox doesn't support go.Frame animation, so we collect
    # raw frame data and drive animation via JS instead.
    # Vector: use Plotly's native go.Frame animation (works fine with Scattergeo).
    sat_frame_data = []
    period_texts   = []   # per-period label arrays for the satellite JS driver
    plotly_frames  = []
    slider_steps   = []

    for step_idx, step_label in enumerate(time_cols):
        eng      = engagement[step_label]
        prev_eng = engagement[time_cols[step_idx - 1]] if step_idx > 0 else eng
        # Label is shown only when a city has engagement; empty string hides it
        texts    = [n if e > 0 else "" for n, e in zip(names, eng)]

        if satellite:
            period_texts.append(texts)

        for pulse_i in range(n_frames):
            t = 2 * math.pi * pulse_i / n_frames
            dot_sizes, ring_sizes, ring_opacity = pulsed_sizes(
                eng, prev_eng, pulse_mode, scale, amplitude, t
            )
            if satellite:
                sat_frame_data.append({
                    'ds': dot_sizes,
                    'e':  list(eng),
                })
            else:
                main_trace, ring_trace = dot_traces(dot_sizes, ring_sizes, ring_opacity, eng, texts)
                plotly_frames.append(go.Frame(
                    name=f"{step_label}_{pulse_i:02d}",
                    data=[main_trace, ring_trace],
                ))

        if satellite:
            # "skip" lets the slider move visually; JS handles the actual update
            slider_steps.append(dict(label=step_label, method="skip"))
        else:
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
    init_texts = [n if e > 0 else "" for n, e in zip(names, init_eng)]
    init_main, init_ring = dot_traces(init_sizes, [s * 1.7 for s in init_sizes], 0.0, init_eng, init_texts)

    fig = go.Figure(data=[init_main, init_ring], frames=plotly_frames)

    # Map background — branch on style
    title_color = "white" if satellite else "#333"
    if satellite:
        map_layout = dict(
            mapbox=dict(
                style="white-bg",
                center=dict(lat=54.5, lon=-2.5),
                zoom=4.8,
                layers=[{
                    "below": "traces",
                    "sourcetype": "raster",
                    "source": [
                        "https://server.arcgisonline.com/ArcGIS/rest/services/"
                        "World_Imagery/MapServer/tile/{z}/{y}/{x}"
                    ],
                    "sourceattribution": "Imagery \u00a9 Esri",
                }],
            ),
            paper_bgcolor="#0d1117",
        )
        play_buttons = [
            dict(label="Play",  method="skip"),
            dict(label="Pause", method="skip"),
        ]
    else:
        map_layout = dict(
            geo=dict(
                scope="europe", resolution=50,
                lonaxis=dict(range=[-9, 3]), lataxis=dict(range=[49, 62]),
                showland=True,       landcolor="rgb(242, 237, 230)",
                showcoastlines=True, coastlinecolor="rgb(155, 155, 155)", coastlinewidth=1,
                showocean=True,      oceancolor="rgb(218, 232, 245)",
                showcountries=True,  countrycolor="rgb(200, 200, 200)",
                bgcolor="rgba(0,0,0,0)",
            ),
            paper_bgcolor="white",
        )
        play_buttons = [
            dict(label="Play", method="animate",
                 args=[None, dict(
                     frame=dict(duration=frame_dur, redraw=True),
                     fromcurrent=True, transition=dict(duration=0),
                 )]),
            dict(label="Pause", method="animate",
                 args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")]),
        ]

    fig.update_layout(
        title=dict(
            text="UK Engagement Map",
            font=dict(size=16, color=title_color),
            x=0.5, xanchor="center",
        ),
        **map_layout,
        updatemenus=[dict(
            type="buttons", showactive=False,
            x=0.01, y=0.99, xanchor="left", yanchor="top",
            buttons=play_buttons,
        )],
        sliders=[dict(
            active=0, steps=slider_steps,
            x=0.05, len=0.9, y=0, yanchor="top",
            currentvalue=dict(prefix="Period: ", font=dict(size=12, color=title_color)),
            transition=dict(duration=0),
        )],
        showlegend=False,
        height=620, margin=dict(t=50, b=80, l=10, r=90),
    )

    post_script = (
        _satellite_post_script(sat_frame_data, period_texts, n_frames, len(time_cols), frame_dur)
        if satellite else None
    )
    return fig, post_script


# ─────────────────────────────────────────────
#  SATELLITE JS ANIMATION DRIVER
# ─────────────────────────────────────────────

def _satellite_post_script(sat_frame_data, period_texts, n_pulse_frames, n_periods, frame_dur):
    """Return JS injected into the HTML to drive satellite animation.

    Scattermapbox traces don't support Plotly's go.Frame animation engine.
    Instead we mutate gd.data directly and call Plotly.redraw(), which
    propagates changes through to the Mapbox rendering layer.
    """
    frames_json      = json.dumps(sat_frame_data)
    period_texts_json = json.dumps(period_texts)
    total = n_pulse_frames * n_periods
    return f"""\
(function() {{
  var gd  = document.querySelector('.plotly-graph-div');
  var fms = {frames_json};
  var ptx = {period_texts_json};
  var idx = 0, timer = null, ms = {frame_dur};
  var np  = {n_pulse_frames}, tot = {total};
  var curPeriod = 0;

  function apply(i) {{
    var f = fms[i];
    var p = Math.floor(i / np);
    gd.data[0].marker.size  = f.ds;
    gd.data[0].marker.color = f.e;
    // On period change: update labels and advance slider
    if (p !== curPeriod) {{
      curPeriod = p;
      gd.data[0].text = ptx[p];
      gd.layout.sliders[0].active = p;
    }}
    Plotly.redraw(gd);
  }}

  function tick()  {{ idx = (idx + 1) % tot; apply(idx); }}
  function play()  {{ if (!timer) timer = setInterval(tick, ms); }}
  function pause() {{ clearInterval(timer); timer = null; }}

  // Primary: Plotly event API
  gd.on('plotly_buttonclicked', function(e) {{
    if (e.button.label === 'Play')  play();
    if (e.button.label === 'Pause') pause();
  }});

  gd.on('plotly_sliderchange', function(e) {{
    pause();
    curPeriod = e.slider.active;
    idx = curPeriod * np;
    apply(idx);
  }});

  // Fallback: direct DOM click capture in case Plotly swallows the event
  gd.addEventListener('click', function(e) {{
    var el = e.target;
    for (var i = 0; i < 8; i++) {{
      if (!el || el === gd) break;
      var txt = (el.textContent || '').trim();
      if (txt === 'Play')  {{ play();  return; }}
      if (txt === 'Pause') {{ pause(); return; }}
      el = el.parentElement;
    }}
  }}, true);
}})();"""


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
  python3 uk_engagement_map.py --map-style satellite
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
    p.add_argument("--map-style",
                   default=DEFAULTS["map_style"],
                   choices=["vector", "satellite"],
                   help="Map background style: vector (default) or satellite imagery")
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
    print(f"  pulse={opts.pulse}, dot-scale={opts.dot_scale}, speed={opts.speed}, map-style={opts.map_style}")

    print("Building figure...")
    fig, post_script = build_figure(df, time_cols, opts)

    write_kwargs = {"post_script": post_script} if post_script else {}
    fig.write_html(OUTPUT_HTML, **write_kwargs)
    print(f"Saved -> {OUTPUT_HTML}")

    if opts.video:
        export_video(fig)


if __name__ == "__main__":
    main()
