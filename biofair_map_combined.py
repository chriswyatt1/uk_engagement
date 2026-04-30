#!/usr/bin/env python3
"""
biofair_map_combined.py  –  Two-panel UK engagement map.

Left panel  : UK mailing-list sign-ups (heatmap by count).
Right panel : BioFAIR roadshow / fellows / events combined,
              each source drawn in a distinct colour.

Usage:
    python3 biofair_map_combined.py
    python3 biofair_map_combined.py --dot-map
    python3 biofair_map_combined.py --speed fast
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Re-use shared helpers from biofair_map.py ────────────────────────────────
from biofair_map import (
    GEOCACHE_PATH, GEOCODE_OVERRIDES, COUNTRY_CODE_MAP,
    DOT_BG_COLOR, DOT_SPACING, UK_DOT_LAT_SPACING,
    SPEED_MS, PALETTES, DEFAULT_THRESHOLDS,
    GEO_COMMON, GEO_BLANK,
    load_geocache, save_geocache, geocode_company, geocode_all,
    _fetch_uk_land, _grid_inside, generate_uk_dots,
    _snap_to_grid, _snap_all_uk,
    load_mailing, load_events, load_fellows,
    _sample_palette, _resolve_palette, _heat_color, precompute_heatmap,
)

# ── Paths ─────────────────────────────────────────────────────────────────────
ROADSHOW_PATH = "data/biofair_roadshow.csv"
OUTPUT_HTML   = "output/biofair_map_combined.html"

# ── Right-panel source colours ────────────────────────────────────────────────
RIGHT_COLOR = {"roadshow": "#f97316", "fellows": "#16a34a", "events": "#9333ea"}
RIGHT_LABEL = {"roadshow": "BioFAIR Roadshow", "fellows": "BioFAIR Fellows",
               "events": "BioFAIR Events"}


# ── Roadshow loader ───────────────────────────────────────────────────────────

def load_roadshow(path=ROADSHOW_PATH):
    """
    Parse city-block roadshow TSV:
      City: <CityName>
      No.  Institution  Date
      1    Some Uni     23-Apr-24
      ...
    Each attendee row becomes one data point geocoded to that city.
    """
    p = Path(path)
    if not p.exists():
        print(f"  NOTE: {path} not found — roadshow data skipped")
        return pd.DataFrame(columns=["date", "Company", "Location", "display", "source"])

    rows = []
    current_city = None
    with open(p) as f:
        for line in f:
            line = line.rstrip()
            if line.startswith("City:"):
                current_city = line[5:].strip()
                continue
            parts = line.split("\t")
            if len(parts) < 3 or parts[0].strip() in ("No.", ""):
                continue
            inst     = parts[1].strip() if len(parts) > 1 else ""
            date_str = parts[2].strip() if len(parts) > 2 else ""
            if not date_str or not current_city:
                continue
            if inst.lower() in ("", "n/a", "na", "nan"):
                inst = current_city
            try:
                date = pd.to_datetime(date_str, format="%d-%b-%y")
            except Exception:
                continue
            rows.append({
                "date":     date,
                "Company":  current_city,   # geocode by city
                "Location": "United Kingdom",
                "display":  inst,
                "source":   "roadshow",
            })

    if not rows:
        return pd.DataFrame(columns=["date", "Company", "Location", "display", "source"])

    df = pd.DataFrame(rows)
    counts = df.groupby(["Company", "date"]).size().reset_index(name="n")
    df = df.drop_duplicates(subset=["Company", "date"]).merge(counts, on=["Company", "date"])
    df["display"] = df.apply(
        lambda r: f"{r['Company']} ({r['n']} attendee{'s' if r['n'] != 1 else ''})", axis=1
    )
    return df.sort_values("date").reset_index(drop=True)


# ── Combined loader ───────────────────────────────────────────────────────────

def load_all():
    print("Loading mailing list ...")
    dm = load_mailing("data/mailing.tsv")
    print(f"  {len(dm)} rows, {dm['date'].min().date()} – {dm['date'].max().date()}")

    print("Loading roadshow ...")
    dr = load_roadshow(ROADSHOW_PATH)
    if len(dr):
        print(f"  {len(dr)} rows, {dr['date'].min().date()} – {dr['date'].max().date()}")

    print("Loading fellows ...")
    df = load_fellows("data/biofair_fellow.csv")
    print(f"  {len(df)} rows, {df['date'].min().date()} – {df['date'].max().date()}")

    print("Loading events ...")
    de = load_events("data/biofair_events.csv")
    print(f"  {len(de)} rows, {de['date'].min().date()} – {de['date'].max().date()}")

    merged = pd.concat([dm, dr, df, de], ignore_index=True) \
               .sort_values("date").reset_index(drop=True)
    print(f"Combined: {len(merged)} rows")
    return merged


# ── Figure builder ────────────────────────────────────────────────────────────

def build_figure(df, frame_ms=800, thresholds=None, palette_colors=None,
                 dot_map=False):

    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    if palette_colors is None:
        palette_colors = _sample_palette(PALETTES["BlRd"], len(thresholds))

    df_m = df[df["source"] == "mailing"].reset_index(drop=True)
    df_r = df[df["source"] == "roadshow"].reset_index(drop=True)
    df_f = df[df["source"] == "fellows"].reset_index(drop=True)
    df_e = df[df["source"] == "events"].reset_index(drop=True)
    n, n_m, n_r, n_f, n_e = len(df), len(df_m), len(df_r), len(df_f), len(df_e)

    # Per-frame counts revealed per source
    km_arr, kr_arr, kf_arr, ke_arr = [], [], [], []
    km = kr = kf = ke = 0
    for src in df["source"]:
        if   src == "mailing":  km += 1
        elif src == "roadshow": kr += 1
        elif src == "fellows":  kf += 1
        else:                   ke += 1
        km_arr.append(km); kr_arr.append(kr)
        kf_arr.append(kf); ke_arr.append(ke)

    dates   = df["date"].tolist()
    labels  = df["display"].tolist()
    sources = df["source"].tolist()

    timestamps_ms_js = json.dumps([int(d.timestamp() * 1000) for d in dates])
    dates_js   = json.dumps([d.strftime("%d %b %Y") for d in dates])
    labels_js  = json.dumps(labels)
    sources_js = json.dumps(sources)

    hover_m = [f"<b>{df_m['display'].iloc[i]}</b><br>{df_m['date'].iloc[i].strftime('%d %b %Y')}"
               for i in range(n_m)]
    hover_r = [f"<b>{df_r['display'].iloc[i]}</b><br>{df_r['date'].iloc[i].strftime('%d %b %Y')}"
               for i in range(n_r)]
    hover_f = [f"<b>{df_f['display'].iloc[i]}</b><br>{df_f['date'].iloc[i].strftime('%d %b %Y')}"
               for i in range(n_f)]
    hover_e = [f"<b>{df_e['display'].iloc[i]}</b><br>{df_e['date'].iloc[i].strftime('%d %b %Y')}"
               for i in range(n_e)]

    # Precompute mailing heatmap (left panel)
    m_colors_by_k, m_perms_by_k = precompute_heatmap(df_m, thresholds, palette_colors)

    # ── Slider ────────────────────────────────────────────────────────────────
    slider_steps = [
        dict(label=dates[i].strftime("%d %b %Y"), method="skip",
             args=[[f"frame_{i}"], dict(mode="immediate",
                                        frame=dict(duration=0, redraw=True),
                                        transition=dict(duration=0))])
        for i in range(n)
    ]

    # ── Legend ────────────────────────────────────────────────────────────────
    thresh_labels = [str(t) for t in thresholds[:-1]] + [f"{thresholds[-1]}+"]
    mailing_legend = "  ".join(
        f'<span style="color:{c}">●</span> {lbl}'
        for c, lbl in zip(palette_colors, thresh_labels)
    ) + "&nbsp; mailing sign-ups"

    right_legend = "  ".join(
        f'<span style="color:{RIGHT_COLOR[s]}">●</span> {RIGHT_LABEL[s]}'
        for s in ["roadshow", "fellows", "events"]
    )
    legend_html = mailing_legend + "&nbsp;&nbsp;&nbsp;" + right_legend

    # ── Subplots ──────────────────────────────────────────────────────────────
    geo_base = GEO_BLANK if dot_map else GEO_COMMON
    uk_geo   = dict(lonaxis=dict(range=[-9, 3]), lataxis=dict(range=[49, 62]),
                    resolution=50, projection_type="mercator")

    fig = make_subplots(
        rows=1, cols=2,
        horizontal_spacing=0,
        specs=[[{"type": "geo"}, {"type": "geo"}]],
    )

    empty_sz = [0]
    empty_c  = ["rgba(0,0,0,0)"]

    def _scat(lat_, lon_, sz, c, ht_, geo_ref):
        return go.Scattergeo(
            lat=lat_, lon=lon_, mode="markers",
            marker=dict(size=sz, color=c, opacity=0.9,
                        line=dict(width=1, color="white")),
            hovertext=ht_, hoverinfo="text",
            geo=geo_ref, showlegend=False,
        )

    def _bg(dot_list, geo_ref):
        return go.Scattergeo(
            lat=[d[0] for d in dot_list], lon=[d[1] for d in dot_list],
            mode="markers",
            marker=dict(size=7, color=DOT_BG_COLOR, opacity=0.9, line=dict(width=0)),
            hoverinfo="skip", showlegend=False, geo=geo_ref,
        )

    M_LARGE, M_SMALL = 22, 12   # mailing dot sizes
    R_LARGE, R_SMALL = 18, 10   # right-panel dot sizes

    if dot_map:
        print("  Building UK dot grid ...")
        uk_grid = generate_uk_dots()
        print(f"    {len(uk_grid)} UK dots")

        um_lats, um_lons = _snap_all_uk(df_m["lat"].tolist(), df_m["lon"].tolist(), uk_grid)
        ur_lats, ur_lons = _snap_all_uk(df_r["lat"].tolist(), df_r["lon"].tolist(), uk_grid) if n_r else ([], [])
        uf_lats, uf_lons = _snap_all_uk(df_f["lat"].tolist(), df_f["lon"].tolist(), uk_grid)
        ue_lats, ue_lons = _snap_all_uk(df_e["lat"].tolist(), df_e["lon"].tolist(), uk_grid)

        # Traces: 0=left bg, 1=right bg, 2=mailing, 3=roadshow, 4=fellows, 5=events
        fig.add_trace(_bg(uk_grid, "geo"),  row=1, col=1)  # 0
        fig.add_trace(_bg(uk_grid, "geo2"), row=1, col=2)  # 1
        fig.add_trace(_scat(um_lats, um_lons, empty_sz, empty_c, hover_m, "geo"),  row=1, col=1)  # 2
        fig.add_trace(_scat(ur_lats if n_r else [0], ur_lons if n_r else [0], empty_sz, empty_c, hover_r or [""], "geo2"), row=1, col=2)  # 3
        fig.add_trace(_scat(uf_lats, uf_lons, empty_sz, empty_c, hover_f, "geo2"), row=1, col=2)  # 4
        fig.add_trace(_scat(ue_lats, ue_lons, empty_sz, empty_c, hover_e, "geo2"), row=1, col=2)  # 5

        fig.frames = []
        frame_json = json.dumps({
            "km": km_arr, "kr": kr_arr, "kf": kf_arr, "ke": ke_arr,
            "mc": m_colors_by_k, "mp": m_perms_by_k,
        })

    else:
        # Vector mode
        um_lats, um_lons = df_m["lat"].tolist(), df_m["lon"].tolist()
        ur_lats, ur_lons = df_r["lat"].tolist(), df_r["lon"].tolist()
        uf_lats, uf_lons = df_f["lat"].tolist(), df_f["lon"].tolist()
        ue_lats, ue_lons = df_e["lat"].tolist(), df_e["lon"].tolist()

        # Traces: 0=mailing, 1=roadshow, 2=fellows, 3=events
        fig.add_trace(_scat(um_lats, um_lons, empty_sz, empty_c, hover_m, "geo"),  row=1, col=1)  # 0
        fig.add_trace(_scat(ur_lats if n_r else [0], ur_lons if n_r else [0], empty_sz, empty_c, hover_r or [""], "geo2"), row=1, col=2)  # 1
        fig.add_trace(_scat(uf_lats, uf_lons, empty_sz, empty_c, hover_f, "geo2"), row=1, col=2)  # 2
        fig.add_trace(_scat(ue_lats, ue_lons, empty_sz, empty_c, hover_e, "geo2"), row=1, col=2)  # 3

        def ws_m(km):
            mp = m_perms_by_k[km]
            mc = m_colors_by_k[km]
            sz = [M_LARGE if j == km-1 else M_SMALL if j < km else 0 for j in range(n_m)]
            return [mp[i] for i in range(n_m)], [sz[mp[i]] for i in range(n_m)], [mc[mp[i]] for i in range(n_m)]

        def ws_r(k, n_src, col, large, small):
            sz = [large if j==k-1 else small if j<k else 0 for j in range(n_src)]
            c  = [col if j < k else "rgba(0,0,0,0)" for j in range(n_src)]
            return sz, c

        plotly_frames = []
        for i in range(n):
            km, kr, kf, ke = km_arr[i], kr_arr[i], kf_arr[i], ke_arr[i]
            mp, sz_m_p, c_m_p = ws_m(km)

            def _pa(lats, lons, perm):
                return [lats[j] for j in perm], [lons[j] for j in perm]

            m_lat_p, m_lon_p = _pa(um_lats, um_lons, m_perms_by_k[km])
            sz_r_, c_r_ = ws_r(kr, n_r, RIGHT_COLOR["roadshow"], R_LARGE, R_SMALL)
            sz_f_, c_f_ = ws_r(kf, n_f, RIGHT_COLOR["fellows"],  R_LARGE, R_SMALL)
            sz_e_, c_e_ = ws_r(ke, n_e, RIGHT_COLOR["events"],   R_LARGE, R_SMALL)

            plotly_frames.append(go.Frame(
                name=f"frame_{i}",
                data=[
                    _scat(m_lat_p,  m_lon_p,  sz_m_p, c_m_p, [m for m in [hover_m[j] for j in m_perms_by_k[km]]], "geo"),
                    _scat(ur_lats, ur_lons, sz_r_, c_r_, hover_r or [""], "geo2"),
                    _scat(uf_lats, uf_lons, sz_f_, c_f_, hover_f, "geo2"),
                    _scat(ue_lats, ue_lons, sz_e_, c_e_, hover_e, "geo2"),
                ],
            ))
        fig.frames = plotly_frames
        frame_json = "{}"

    fig.update_layout(
        geo=dict(**geo_base,  **uk_geo, domain=dict(x=[0.0, 0.38], y=[0.0, 1.0])),
        geo2=dict(**geo_base, **uk_geo, domain=dict(x=[0.40, 0.78], y=[0.0, 1.0])),
        title=dict(text="BioFAIR UK Engagement", font=dict(size=18, color="#333"),
                   x=0.5, xanchor="center"),
        paper_bgcolor="white",
        updatemenus=[dict(
            type="buttons", showactive=False,
            x=0.01, y=0.99, xanchor="left", yanchor="top",
            buttons=(
                [dict(label="Play",  method="skip"),
                 dict(label="Pause", method="skip")]
                if dot_map else
                [dict(label="Play", method="animate",
                      args=[None, dict(frame=dict(duration=frame_ms, redraw=True),
                                       fromcurrent=True, transition=dict(duration=0))]),
                 dict(label="Pause", method="animate",
                      args=[[None], dict(frame=dict(duration=0, redraw=False),
                                          mode="immediate")])]
            ),
        )],
        sliders=[dict(
            active=0, steps=slider_steps,
            x=0.05, len=0.9, y=0, yanchor="top",
            currentvalue=dict(prefix="Date: ", font=dict(size=12, color="#333")),
            transition=dict(duration=0),
        )],
        showlegend=False, height=640,
        margin=dict(t=70, b=80, l=10, r=220),
        annotations=[
            dict(x=0.19, y=1.02, xref="paper", yref="paper",
                 text="UK — Mailing List Sign-ups", showarrow=False,
                 font=dict(size=13, color="#444"), xanchor="center"),
            dict(x=0.59, y=1.02, xref="paper", yref="paper",
                 text="UK — BioFAIR Engagement", showarrow=False,
                 font=dict(size=13, color="#444"), xanchor="center"),
            dict(x=0.42, y=-0.08, xref="paper", yref="paper",
                 text=legend_html, showarrow=False,
                 font=dict(size=11, color="#333"), align="center"),
        ],
    )

    if not dot_map:
        return fig, None

    # ── JS animation driver ───────────────────────────────────────────────────

    col_r = RIGHT_COLOR["roadshow"]
    col_f = RIGHT_COLOR["fellows"]
    col_e = RIGHT_COLOR["events"]

    post_script = f"""\
(function() {{
  var gd = document.querySelector('.plotly-graph-div');
  var wrap = gd.closest('.js-plotly-plot') || gd.parentElement;
  wrap.style.position = 'relative';

  var n   = {n};
  var n_m = {n_m}, n_r = {n_r}, n_f = {n_f}, n_e = {n_e};
  var ms  = {frame_ms};
  var tms = {timestamps_ms_js};
  var dateStrs = {dates_js};
  var labels   = {labels_js};
  var sources  = {sources_js};

  var COL_R = '{col_r}', COL_F = '{col_f}', COL_E = '{col_e}';
  var M_LARGE = {M_LARGE}, M_SMALL = {M_SMALL};
  var R_LARGE = {R_LARGE}, R_SMALL = {R_SMALL};
  // Subscriber traces start at index 2 (0,1 are backgrounds)
  var BG = 2;

  var fdata  = {frame_json};
  var km_arr = fdata.km, kr_arr = fdata.kr, kf_arr = fdata.kf, ke_arr = fdata.ke;
  var mc_k = fdata.mc, mp_k = fdata.mp;

  // Capture original lat/lon for mailing (needs permutation for heatmap z-order)
  var lat0_m = gd.data[BG].lat.slice(), lon0_m = gd.data[BG].lon.slice();
  var ht_m   = gd.data[BG].hovertext.slice();

  function pa(arr, perm) {{ return perm.map(function(j) {{ return arr[j]; }}); }}

  function mkSz(k, n_src, large, small) {{
    var s = [];
    for (var j = 0; j < n_src; j++)
      s.push(j === k-1 ? large : j < k ? small : 0);
    return s;
  }}

  function mkCol(k, n_src, col) {{
    var c = [];
    for (var j = 0; j < n_src; j++) c.push(j < k ? col : 'rgba(0,0,0,0)');
    return c;
  }}

  // ── Info panel (right side) ────────────────────────────────────────────────
  var panel = document.createElement('div');
  panel.style.cssText = [
    'position:absolute','right:10px','top:70px','height:490px',
    'background:rgba(245,247,251,0.93)',
    'color:#1e1b4b','padding:10px 14px','border-radius:8px','width:200px',
    'font-size:11px','font-family:Arial,sans-serif','pointer-events:none',
    'z-index:100','line-height:1.4','overflow:hidden','box-sizing:border-box',
  ].join(';');
  wrap.appendChild(panel);
  var recent = [];

  var SRC_COL = {{
    mailing:  '#3b82f6',
    roadshow: COL_R,
    fellows:  COL_F,
    events:   COL_E,
  }};
  var SRC_LBL = {{
    mailing:  'Mailing',
    roadshow: 'Roadshow',
    fellows:  'Fellow',
    events:   'Event',
  }};

  function updatePanel(i) {{
    var lbl = labels[i], src = sources[i];
    if (lbl && lbl.length > 1 && lbl !== src) {{
      recent.unshift({{name: lbl, date: dateStrs[i], src: src}});
      if (recent.length > 16) recent.pop();
    }}
    if (!recent.length) {{ panel.innerHTML = ''; return; }}
    var html = '<div style="font-size:9px;opacity:0.55;margin-bottom:8px;'
             + 'letter-spacing:.08em;text-transform:uppercase">Recent</div>';
    recent.forEach(function(r, ri) {{
      var op  = Math.max(0.3, 1 - ri * 0.055);
      var sz  = ri === 0 ? '12px' : '11px';
      var wt  = ri === 0 ? 'bold' : 'normal';
      var col = SRC_COL[r.src] || '#333';
      html += '<div style="margin-bottom:5px;opacity:' + op
            + ';border-left:2px solid ' + col + ';padding-left:6px">'
            + '<div style="font-size:8px;color:' + col + ';opacity:0.85">'
            + (SRC_LBL[r.src] || '') + '</div>'
            + '<span style="font-size:' + sz + ';font-weight:' + wt
            + ';color:#1e1b4b">' + r.name + '</span>'
            + '<br><span style="font-size:9px;opacity:0.6">' + r.date + '</span>'
            + '</div>';
    }});
    panel.innerHTML = html;
  }}

  function applyData(i) {{
    var km = km_arr[i], kr = kr_arr[i], kf = kf_arr[i], ke = ke_arr[i];
    var mp = mp_k[km], mc = mc_k[km];

    updatePanel(i);

    // Mailing: heatmap + permuted z-order
    var sz_m = mp.map(function(j) {{ return j===km-1?M_LARGE:j<km?M_SMALL:0; }});
    var p1 = Plotly.restyle(gd, {{
      lat:            [pa(lat0_m, mp)],
      lon:            [pa(lon0_m, mp)],
      hovertext:      [pa(ht_m, mp)],
      'marker.size':  [sz_m],
      'marker.color': [pa(mc, mp)],
    }}, [BG]);

    // Right panel: fixed source colours, no permutation
    var p2 = Plotly.restyle(gd, {{
      'marker.size':  [mkSz(kr, n_r, R_LARGE, R_SMALL),
                       mkSz(kf, n_f, R_LARGE, R_SMALL),
                       mkSz(ke, n_e, R_LARGE, R_SMALL)],
      'marker.color': [mkCol(kr, n_r, COL_R),
                       mkCol(kf, n_f, COL_F),
                       mkCol(ke, n_e, COL_E)],
    }}, [BG+1, BG+2, BG+3]);

    return (p2 && p2.then) ? p2 : Promise.resolve();
  }}

  function applyFull(i) {{
    recent = [];
    for (var j = 0; j <= i; j++) {{
      var lbl = labels[j];
      if (lbl && lbl.length > 1 && lbl !== sources[j])
        recent.push({{name: lbl, date: dateStrs[j], src: sources[j]}});
    }}
    recent = recent.slice(-16).reverse();
    gd.layout.sliders[0].active = i;
    return applyData(i);
  }}

  var idx = 0, playing = false;
  function tick() {{
    if (!playing) return;
    if (idx < n - 1) {{
      idx++;
      applyData(idx).then(function() {{
        if (playing) setTimeout(tick, ms);
      }}).catch(function() {{
        if (playing) setTimeout(tick, ms);
      }});
    }} else {{ pause(); }}
  }}
  function play()  {{ if (!playing) {{ playing = true; setTimeout(tick, ms); }} }}
  function pause() {{ playing = false; }}

  gd.on('plotly_buttonclicked', function(e) {{
    if (e.button.label === 'Play')  play();
    if (e.button.label === 'Pause') pause();
  }});
  gd.on('plotly_sliderchange', function(e) {{
    if (playing) return;
    idx = e.slider.active; applyFull(idx);
  }});
  gd.addEventListener('click', function(e) {{
    var el = e.target;
    for (var i = 0; i < 8; i++) {{
      if (!el || el === gd) break;
      var t = (el.textContent || '').trim();
      if (t === 'Play')  {{ play();  return; }}
      if (t === 'Pause') {{ pause(); return; }}
      el = el.parentElement;
    }}
  }}, true);
}})();"""

    return fig, post_script


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="BioFAIR combined engagement map.")
    p.add_argument("--speed", default="normal",
                   choices=["slow", "normal", "fast", "instant"])
    p.add_argument("--thresholds", default="1,2,3,4,5")
    p.add_argument("--palette", default="BlRd",
                   help=f"Palette for mailing heatmap ({', '.join(PALETTES)})")
    p.add_argument("--dot-map", action="store_true",
                   help="Render as dot-grid silhouette (recommended)")
    return p.parse_args()


def main():
    opts = parse_args()
    os.makedirs("output", exist_ok=True)

    df = load_all()

    print("Geocoding ...")
    coords = geocode_all(df)
    df["lat"] = [c[0] if c else None for c in coords]
    df["lon"] = [c[1] if c else None for c in coords]

    missing = df[df["lat"].isna()]
    if not missing.empty:
        print(f"  {len(missing)} entries skipped (no geocode):")
        for _, r in missing.iterrows():
            print(f"    [{r['source']}] {r['Company']!r}")

    df = df.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    print(f"  {len(df)} entries with coordinates")

    if df.empty:
        print("ERROR: No geocoded entries.")
        sys.exit(1)

    try:
        thresholds = sorted(set(int(x.strip()) for x in opts.thresholds.split(",")))
        if not thresholds or thresholds[0] < 1:
            raise ValueError
    except ValueError:
        print("ERROR: --thresholds must be positive integers")
        sys.exit(1)

    palette_colors = _resolve_palette(opts.palette, len(thresholds))
    frame_ms = SPEED_MS[opts.speed]

    print(f"Building figure (dot-map={opts.dot_map}, speed={opts.speed}) ...")
    fig, post_script = build_figure(
        df, frame_ms=frame_ms,
        thresholds=thresholds, palette_colors=palette_colors,
        dot_map=opts.dot_map,
    )

    write_kwargs = {"post_script": post_script} if post_script else {}
    fig.write_html(OUTPUT_HTML, **write_kwargs)
    print(f"Saved → {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
