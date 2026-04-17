#!/usr/bin/env python3
"""
mailing_map.py
--------------
Reads data/mailing.tsv and produces an animated world map showing
mailing-list subscribers appearing over time.  Each new subscriber
pops up with their full organisation name visible on the map.

Usage:
    python3 mailing_map.py
    python3 mailing_map.py --data data/mailing.tsv
    python3 mailing_map.py --map-style satellite

Requirements:
    pip install pandas plotly geopy
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


GEOCACHE_PATH = "data/geocache.json"
OUTPUT_HTML   = "output/mailing_map.html"

# Manual overrides for short/ambiguous names
GEOCODE_OVERRIDES = {
    "Dur":                                "University of Durham, United Kingdom",
    "KCL":                                "King's College London, United Kingdom",
    "ARDC":                               "Australian Research Data Commons, Melbourne, Australia",
    "University of Oxford - IDDO":        "University of Oxford, United Kingdom",
    "Mary Lyon Centre at MRC Harwell":    "MRC Harwell, Oxfordshire, United Kingdom",
    "Croydon Health Services NHS Trust":  "Croydon, London, United Kingdom",
    "National Police Chiefs' Council":    "Westminster, London, United Kingdom",
    "archives of chinese academy of sciences": "Chinese Academy of Sciences, Beijing, China",
}

COUNTRY_CODE_MAP = {
    "United Kingdom": "gb",
    "Australia":      "au",
    "Japan":          "jp",
    "United States":  "us",
}


# ─────────────────────────────────────────────
#  GEOCODING
# ─────────────────────────────────────────────

def load_geocache():
    p = Path(GEOCACHE_PATH)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


def save_geocache(cache):
    Path(GEOCACHE_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(GEOCACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def geocode_company(company, country, cache, geolocator):
    """Return (lat, lon) for a company, using cache then Nominatim."""
    query = GEOCODE_OVERRIDES.get(company, company)
    cc    = COUNTRY_CODE_MAP.get(country)

    for key in [query, f"{query}, {country}"]:
        if key in cache:
            entry = cache[key]
            if entry:
                return tuple(entry)
            return None

    print(f"  Geocoding {query!r} ...", end=" ", flush=True)

    # Small delay to respect Nominatim rate limit
    time.sleep(1.1)

    try:
        from geopy.exc import GeocoderTimedOut
        geo = geolocator.geocode(query, country_codes=cc, timeout=10)
        if not geo and cc:
            geo = geolocator.geocode(query, timeout=10)

        if geo:
            coords = [geo.latitude, geo.longitude]
            print(f"({geo.latitude:.4f}, {geo.longitude:.4f})")
        else:
            # Last resort: geocode just the country
            geo = geolocator.geocode(country, timeout=10)
            if geo:
                coords = [geo.latitude, geo.longitude]
                print(f"country fallback ({geo.latitude:.4f}, {geo.longitude:.4f})")
            else:
                coords = None
                print("NOT FOUND")

        cache[query] = coords
        save_geocache(cache)
        return tuple(coords) if coords else None

    except Exception as e:
        print(f"ERROR: {e}")
        cache[query] = None
        return None


def geocode_all(df):
    try:
        from geopy.geocoders import Nominatim
    except ImportError:
        print("ERROR: geopy is required.  Install with:  pip install geopy")
        sys.exit(1)

    cache      = load_geocache()
    geolocator = Nominatim(user_agent="mailing_map/1.0")
    results    = []
    first_call = True
    uncached   = []

    # First pass: find what needs geocoding so we can warn upfront
    for _, row in df.iterrows():
        company = str(row.get("Company", "")).strip()
        country = str(row.get("Location", "")).strip()
        query   = GEOCODE_OVERRIDES.get(company, company) if company else country
        if query and query not in cache and f"{query}, {country}" not in cache:
            uncached.append(query)

    if uncached:
        unique_uncached = list(dict.fromkeys(uncached))
        print(f"  {len(unique_uncached)} new entr{'y' if len(unique_uncached)==1 else 'ies'} to geocode "
              f"(~{len(unique_uncached)} sec due to rate limit): "
              + ", ".join(repr(u) for u in unique_uncached))
    else:
        print("  All entries found in geocache — no API calls needed.")

    for _, row in df.iterrows():
        company = str(row.get("Company", "")).strip()
        country = str(row.get("Location", "")).strip()
        query   = GEOCODE_OVERRIDES.get(company, company) if company else country
        key     = query

        if key in cache:
            entry = cache[key]
            results.append(tuple(entry) if entry else None)
            continue
        fallback_key = f"{query}, {country}"
        if fallback_key in cache:
            entry = cache[fallback_key]
            results.append(tuple(entry) if entry else None)
            continue

        if not first_call:
            time.sleep(1.1)
        first_call = False

        coords = geocode_company(company, country, cache, geolocator)
        results.append(coords)

    return results


# ─────────────────────────────────────────────
#  LOAD DATA
# ─────────────────────────────────────────────

def load_mailing(path):
    df = pd.read_csv(path, sep="\t", dtype=str)
    df.columns = [c.strip() for c in df.columns]

    if "Subscribed" not in df.columns:
        raise ValueError(f"Expected 'Subscribed' column, got: {list(df.columns)}")

    df["date"]     = pd.to_datetime(df["Subscribed"], dayfirst=True, errors="coerce")
    df["Company"]  = df["Company"].fillna("").str.strip()
    df["Location"] = df["Location"].fillna("").str.strip()

    # Drop rows with no date or no company/location to geocode against
    df = df[df["date"].notna() & ((df["Company"].str.len() > 0) | (df["Location"].str.len() > 0))]
    df = df.sort_values("date").reset_index(drop=True)
    return df


SPEED_MS = {"slow": 1500, "normal": 800, "fast": 300, "instant": 80}

ESRI_LAYER = {
    "below": "traces",
    "sourcetype": "raster",
    "source": [
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}"
    ],
    "sourceattribution": "Imagery \u00a9 Esri",
}


# ─────────────────────────────────────────────
#  BUILD FIGURE
# ─────────────────────────────────────────────

# Country-name-only entries — no institution info, skip prominent labels
BORING_LABELS = {
    "", "United Kingdom", "United States", "Australia", "Japan",
    "Ireland", "Greece", "France", "Canada", "Spain",
    "Netherlands", "Uganda", "Turkey", "Germany", "Egypt",
    "China", "India", "Brazil", "South Africa", "Italy",
    "Sweden", "Norway", "Denmark", "Finland", "Belgium",
    "Switzerland", "Austria", "Poland", "Portugal", "Israel",
    "New Zealand", "South Korea",
}


def _in_uk(lat, lon):
    return 49 <= lat <= 62 and -9 <= lon <= 3


def _interesting(company):
    return bool(company) and company not in BORING_LABELS


DEFAULT_THRESHOLDS = [1, 2, 3, 4, 5]

PALETTES = {
    "BlRd":    ["#3b82f6", "#06b6d4", "#22d3ee", "#4ade80", "#a3e635",
                "#facc15", "#fb923c", "#f87171", "#ef4444", "#b91c1c"],
    "RdBl":    ["#b91c1c", "#ef4444", "#f87171", "#fb923c", "#facc15",
                "#a3e635", "#4ade80", "#22d3ee", "#06b6d4", "#3b82f6"],
    "warm":    ["#fef9c3", "#fef08a", "#fde047", "#facc15", "#fb923c",
                "#f97316", "#ef4444", "#dc2626", "#b91c1c", "#7f1d1d"],
    "cool":    ["#e0f2fe", "#bae6fd", "#7dd3fc", "#60a5fa", "#818cf8",
                "#a78bfa", "#c084fc", "#e879f9", "#f0abfc", "#fbcfe8"],
    "viridis": ["#440154", "#482878", "#3e4989", "#31688e", "#26828e",
                "#1f9e89", "#35b779", "#6ece58", "#b5de2b", "#fde725"],
    "plasma":  ["#0d0887", "#46039f", "#7201a8", "#9c179e", "#bd3786",
                "#d8576b", "#ed7953", "#fb9f3a", "#fdcf18", "#f0f921"],
    "greys":   ["#f3f4f6", "#d1d5db", "#9ca3af", "#6b7280", "#4b5563",
                "#374151", "#1f2937", "#111827", "#030712", "#000000"],
}


def _sample_palette(colors, n):
    """Pick n evenly-spaced colors from a list of any length."""
    if n == 1:
        return [colors[-1]]
    indices = [round(i * (len(colors) - 1) / (n - 1)) for i in range(n)]
    return [colors[i] for i in indices]


def _resolve_palette(palette_str, n):
    """Return exactly n color strings from a named palette or comma-separated colors."""
    if palette_str in PALETTES:
        return _sample_palette(PALETTES[palette_str], n)
    colors = [c.strip() for c in palette_str.split(",") if c.strip()]
    if not colors:
        return _sample_palette(PALETTES["BlRd"], n)
    return _sample_palette(colors, n) if len(colors) != n else colors


def _heat_color(count, thresholds, palette_colors):
    idx = 0
    for i, t in enumerate(thresholds):
        if count >= t:
            idx = i
    return palette_colors[idx]


def _chart_block(show_chart, dark):
    """Return JS snippet (NOT an f-string) for the cumulative line chart overlay.
    Uses placeholder tokens replaced via .replace() so JS braces need no escaping."""
    if not show_chart:
        return "function updateChart(i) {}"
    bg     = "rgba(10,10,30,0.82)" if dark else "rgba(255,255,255,0.88)"
    stroke = "#f59e0b"             if dark else "#d97706"
    ax_col = "rgba(255,255,255,0.2)" if dark else "rgba(0,0,0,0.15)"
    tc_col = "rgba(255,255,255,0.4)" if dark else "rgba(0,0,0,0.4)"
    cc_col = "white"               if dark else "#111"
    tmpl = (
        "  var SVG_NS = 'http://www.w3.org/2000/svg';\n"
        "  var svg = document.createElementNS(SVG_NS, 'svg');\n"
        "  svg.setAttribute('width', '200'); svg.setAttribute('height', '100');\n"
        "  svg.style.cssText = 'position:absolute;top:70px;right:10px;"
            "background:BG;border-radius:6px;pointer-events:none;z-index:100';\n"
        "  function svgEl(tag, attrs) {\n"
        "    var el = document.createElementNS(SVG_NS, tag);\n"
        "    Object.keys(attrs).forEach(function(k) { el.setAttribute(k, attrs[k]); });\n"
        "    return el;\n"
        "  }\n"
        "  svg.appendChild(svgEl('line', {x1:28,y1:78,x2:192,y2:78,"
            "stroke:'AX','stroke-width':1}));\n"
        "  svg.appendChild(svgEl('line', {x1:28,y1:12,x2:28,y2:78,"
            "stroke:'AX','stroke-width':1}));\n"
        "  var titleSvg = svgEl('text', {x:110,y:9,fill:'TC',"
            "'font-size':8,'text-anchor':'middle','font-family':'Arial,sans-serif'});\n"
        "  titleSvg.textContent = 'Cumulative sign-ups';\n"
        "  svg.appendChild(titleSvg);\n"
        "  var countEl = svgEl('text', {x:192,y:30,fill:'CC',"
            "'font-size':22,'text-anchor':'end','font-weight':'bold',"
            "'font-family':'Arial,sans-serif'});\n"
        "  countEl.textContent = '0';\n"
        "  svg.appendChild(countEl);\n"
        "  var lineEl = svgEl('polyline', {points:'',fill:'none',stroke:'ST',"
            "'stroke-width':2,'stroke-linejoin':'round'});\n"
        "  svg.appendChild(lineEl);\n"
        "  var dotEl = svgEl('circle', {cx:28,cy:78,r:3.5,fill:'ST'});\n"
        "  svg.appendChild(dotEl);\n"
        "  wrap.appendChild(svg);\n"
        "  var t0 = tms[0], tRange = Math.max(tms[n - 1] - tms[0], 1);\n"
        "  function chartX(i) { return (28 + (tms[i]-t0)/tRange*164).toFixed(1); }\n"
        "  function chartY(i) { return (78 - (i+1)/n*66).toFixed(1); }\n"
        "  function updateChart(i) {\n"
        "    var pts = '';\n"
        "    for (var j = 0; j <= i; j++) { pts += chartX(j)+','+chartY(j)+' '; }\n"
        "    lineEl.setAttribute('points', pts);\n"
        "    dotEl.setAttribute('cx', chartX(i));\n"
        "    dotEl.setAttribute('cy', chartY(i));\n"
        "    countEl.textContent = String(i + 1);\n"
        "  }"
    )
    return tmpl.replace("BG", bg).replace("AX", ax_col).replace("TC", tc_col) \
               .replace("CC", cc_col).replace("ST", stroke)


def build_figure(df, satellite=False, frame_ms=800, show_chart=False,
                 thresholds=None, palette_colors=None):
    from collections import defaultdict

    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    if palette_colors is None:
        palette_colors = _sample_palette(PALETTES["BlRd"], len(thresholds))

    lats      = df["lat"].tolist()
    lons      = df["lon"].tolist()
    companies = df["Company"].tolist()
    dates     = df["date"].tolist()
    n         = len(df)
    locations = df["Location"].tolist()
    uk_mask   = [_in_uk(lats[i], lons[i]) for i in range(n)]
    interesting = [_interesting(companies[i]) for i in range(n)]

    def hover_label(i):
        name = companies[i] or locations[i] or "Unknown"
        return f"<b>{name}</b><br>{dates[i].strftime('%d %b %Y')}"

    # Location key for grouping — round to ~1km precision
    loc_key = [f"{round(lats[i], 2)},{round(lons[i], 2)}" for i in range(n)]

    timestamps_ms_js = json.dumps([int(d.timestamp() * 1000) for d in dates])

    # Pre-compute per-frame heatmap colors: each dot reflects cumulative visit count
    frame_colors = []
    loc_count = defaultdict(int)
    for idx in range(n):
        loc_count[loc_key[idx]] += 1
        frame_colors.append([
            _heat_color(loc_count[loc_key[i]], thresholds, palette_colors) if i <= idx else "rgba(0,0,0,0)"
            for i in range(n)
        ])

    def sizes(highlight_idx, large=18, small=10):
        return [
            large if i == highlight_idx
            else small if i < highlight_idx
            else 0
            for i in range(n)
        ]

    def world_texts(highlight_idx):
        c = companies[highlight_idx]
        label = c if _interesting(c) else ""
        return [label if i == highlight_idx else "" for i in range(n)]

    def uk_texts(highlight_idx):
        return [
            companies[i] if i <= highlight_idx and uk_mask[i] and _interesting(companies[i]) else ""
            for i in range(n)
        ]

    slider_steps = [
        dict(
            label=dates[idx].strftime("%d %b %Y"),
            method="animate" if not satellite else "skip",
            args=[[f"frame_{idx}"], dict(
                mode="immediate",
                frame=dict(duration=0, redraw=True),
                transition=dict(duration=0),
            )],
        )
        for idx in range(n)
    ]

    thresh_labels = [str(t) for t in thresholds[:-1]] + [f"{thresholds[-1]}+"]
    legend_html = (
        ''.join(f'<span style="color:{c}">●</span> {lbl}  '
                for c, lbl in zip(palette_colors, thresh_labels)) +
        '&nbsp;&nbsp;sign-ups at location'
    )

    # ── SATELLITE ────────────────────────────────────────────────────────────
    if satellite:
        import warnings
        warnings.filterwarnings("ignore", message=".*scattermapbox.*",
                                category=DeprecationWarning)

        fig = make_subplots(
            rows=1, cols=2,
            column_widths=[0.55, 0.45],
            specs=[[{"type": "mapbox"}, {"type": "mapbox"}]],
            subplot_titles=["World", "United Kingdom"],
        )

        empty = ["rgba(0,0,0,0)"] * n

        def sat_trace(sz, c, tx, subplot):
            return go.Scattermapbox(
                lat=lats, lon=lons, mode="markers+text",
                marker=dict(size=sz, color=c, opacity=0.9),
                text=tx, textposition="top right",
                textfont=dict(size=11, color="white", family="Arial Black"),
                hovertext=[hover_label(i) for i in range(n)],
                hoverinfo="text",
                subplot=subplot,
            )

        fig.add_trace(sat_trace([0]*n, empty, [""]*n, "mapbox"),  row=1, col=1)
        fig.add_trace(sat_trace([0]*n, empty, [""]*n, "mapbox2"), row=1, col=2)

        # Collect raw frame data for JS driver
        sat_frames = []
        for idx in range(n):
            c = frame_colors[idx]
            sat_frames.append({
                "w":  {"ds": sizes(idx, 18, 10), "c": c, "tx": world_texts(idx)},
                "uk": {"ds": sizes(idx, 22, 12), "c": c, "tx": uk_texts(idx)},
            })

        fig.update_layout(
            mapbox=dict(
                style="white-bg",
                center=dict(lat=20, lon=10),
                zoom=0.8,
                layers=[ESRI_LAYER],
            ),
            mapbox2=dict(
                style="white-bg",
                center=dict(lat=55, lon=-3),
                zoom=4.5,
                layers=[ESRI_LAYER],
            ),
            paper_bgcolor="#0d1117",
            title=dict(
                text="Mailing List Sign-ups",
                font=dict(size=18, color="white"),
                x=0.5, xanchor="center",
            ),
            updatemenus=[dict(
                type="buttons", showactive=False,
                x=0.01, y=0.99, xanchor="left", yanchor="top",
                buttons=[
                    dict(label="Play",  method="skip"),
                    dict(label="Pause", method="skip"),
                ],
            )],
            sliders=[dict(
                active=0, steps=slider_steps,
                x=0.05, len=0.9, y=0, yanchor="top",
                currentvalue=dict(prefix="Joined: ", font=dict(size=12, color="white")),
                transition=dict(duration=0),
            )],
            showlegend=False,
            height=640,
            margin=dict(t=70, b=80, l=10, r=10),
            annotations=[dict(
                x=0.5, y=-0.08, xref="paper", yref="paper",
                text=legend_html, showarrow=False,
                font=dict(size=12, color="white"), align="center",
            )],
        )

        interesting_js = json.dumps(interesting)
        dates_js       = json.dumps([d.strftime("%d %b %Y") for d in dates])
        frames_json    = json.dumps(sat_frames)
        chart_js       = _chart_block(show_chart, dark=True)
        post_script = f"""\
(function() {{
  var gd          = document.querySelector('.plotly-graph-div');
  var fms         = {frames_json};
  var interesting = {interesting_js};
  var dateStrs    = {dates_js};
  var companies   = {json.dumps(companies)};
  var tms         = {timestamps_ms_js};
  var n           = fms.length;
  var idx         = 0, timer = null, ms = {frame_ms};
  var playing     = false;
  var recent      = [];   // recent interesting additions for the panel

  // ── Info panel (between the two maps) ──────────────────────────────────
  var panel = document.createElement('div');
  panel.style.cssText = [
    'position:absolute',
    'left:55%',
    'top:70px',                         /* align with top of map area */
    'height:490px',                     /* full map height (640 - margin.t 70 - margin.b 80) */
    'transform:translateX(-50%)',
    'background:rgba(10,10,30,0.82)',
    'color:white',
    'padding:10px 14px',
    'border-radius:8px',
    'width:240px',
    'font-size:11px',
    'font-family:Arial,sans-serif',
    'pointer-events:none',
    'z-index:100',
    'line-height:1.4',
    'overflow:hidden',
    'box-sizing:border-box',
  ].join(';');
  // Needs a relative-positioned parent so absolute positioning works
  var wrap = gd.closest('.js-plotly-plot') || gd.parentElement;
  wrap.style.position = 'relative';
  wrap.appendChild(panel);

  {chart_js}

  function updatePanel(i) {{
    if (interesting[i]) {{
      recent.unshift({{name: companies[i], date: dateStrs[i]}});
      if (recent.length > 14) recent.pop();
    }}
    if (recent.length === 0) {{ panel.innerHTML = ''; return; }}
    var html = '<div style="font-size:9px;opacity:0.55;margin-bottom:8px;letter-spacing:.08em;text-transform:uppercase">Recent sign-ups</div>';
    recent.forEach(function(r, ri) {{
      var op = Math.max(0.3, 1 - ri * 0.06);
      var sz = ri === 0 ? '12px' : '11px';
      var wt = ri === 0 ? 'bold' : 'normal';
      html += '<div style="margin-bottom:6px;opacity:' + op + ';border-left:2px solid rgba(245,158,11,' + op + ');padding-left:6px">'
            + '<span style="font-size:' + sz + ';font-weight:' + wt + ';color:#f0f0f0">' + r.name + '</span>'
            + '<br><span style="font-size:9px;opacity:0.6">' + r.date + '</span>'
            + '</div>';
    }});
    panel.innerHTML = html;
  }}

  // ── Apply frame data ────────────────────────────────────────────────────
  // Use restyle (trace-only, fast) and return its Promise so ticks chain off it.
  // Never touch gd.layout.sliders during animation — that fires plotly_sliderchange.
  function applyData(i) {{
    var f = fms[i];
    gd.data[0].text = f.w.tx;
    gd.data[1].text = f.uk.tx;
    updatePanel(i);
    updateChart(i);
    var p = Plotly.restyle(gd,
      {{'marker.size':  [f.w.ds,  f.uk.ds],
        'marker.color': [f.w.c,   f.uk.c]}},
      [0, 1]);
    return (p && p.then) ? p : Promise.resolve();
  }}

  // Full version used when manually moving the slider — updates slider label too.
  function applyFull(i) {{
    var f = fms[i];
    // Rebuild recent list up to this point for the panel
    recent = [];
    for (var j = 0; j <= i; j++) {{
      if (interesting[j]) recent.push({{name: companies[j], date: dateStrs[j]}});
    }}
    recent = recent.slice(-5).reverse();
    updatePanel(i);
    updateChart(i);
    gd.layout.sliders[0].active = i;
    return Plotly.restyle(gd,
      {{'marker.size':  [f.w.ds,  f.uk.ds],
        'marker.color': [f.w.c,   f.uk.c],
        'text':         [f.w.tx,  f.uk.tx]}},
      [0, 1]);
  }}

  // ── Playback control ────────────────────────────────────────────────────
  // Chain ticks off the render Promise so panel and map stay in sync.
  function tick() {{
    if (!playing) return;
    if (idx < n - 1) {{
      idx++;
      applyData(idx).then(function() {{
        if (playing) setTimeout(tick, ms);
      }}).catch(function() {{
        if (playing) setTimeout(tick, ms);
      }});
    }} else {{
      pause();
    }}
  }}
  function play()  {{ if (!playing) {{ playing = true;  setTimeout(tick, ms); }} }}
  function pause() {{ playing = false; }}

  gd.on('plotly_buttonclicked', function(e) {{
    if (e.button.label === 'Play')  play();
    if (e.button.label === 'Pause') pause();
  }});
  gd.on('plotly_sliderchange', function(e) {{
    if (playing) return;   // ignore slider events fired by Plotly during animation
    pause(); idx = e.slider.active; applyFull(idx);
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

    # ── VECTOR ───────────────────────────────────────────────────────────────
    geo_common = dict(
        showland=True,       landcolor="rgb(242, 237, 230)",
        showcoastlines=True, coastlinecolor="rgb(155, 155, 155)", coastlinewidth=1,
        showocean=True,      oceancolor="rgb(218, 232, 245)",
        showcountries=True,  countrycolor="rgb(200, 200, 200)",
        bgcolor="rgba(0,0,0,0)",
    )

    fig = make_subplots(
        rows=1, cols=2,
        column_widths=[0.55, 0.45],
        specs=[[{"type": "geo"}, {"type": "geo"}]],
        subplot_titles=["World", "United Kingdom"],
    )

    ht = [hover_label(i) for i in range(n)]

    def vec_trace(sz, c, tx, geo_ref, fs=11):
        return go.Scattergeo(
            lat=lats, lon=lons, mode="markers+text",
            marker=dict(size=sz, color=c, opacity=0.9,
                        line=dict(width=1.5, color="white")),
            text=tx, textposition="top center",
            textfont=dict(size=fs, color="#1e1b4b", family="Arial Bold"),
            hovertext=ht, hoverinfo="text",
            geo=geo_ref,
        )

    empty_sz = [0] * n
    empty_c  = ["rgba(0,0,0,0)"] * n
    fig.add_trace(vec_trace(empty_sz, empty_c, [""]*n, "geo"),  row=1, col=1)
    fig.add_trace(vec_trace(empty_sz, empty_c, [""]*n, "geo2"), row=1, col=2)

    plotly_frames = []
    for idx in range(n):
        c = frame_colors[idx]
        plotly_frames.append(go.Frame(
            name=f"frame_{idx}",
            data=[
                vec_trace(sizes(idx, 18, 10), c, world_texts(idx), "geo",  fs=11),
                vec_trace(sizes(idx, 22, 12), c, uk_texts(idx),    "geo2", fs=10),
            ],
        ))
    fig.frames = plotly_frames

    fig.update_layout(
        geo=dict(**geo_common, scope="world", projection_type="natural earth"),
        geo2=dict(**geo_common,
                  lonaxis=dict(range=[-9, 3]), lataxis=dict(range=[49, 62]),
                  resolution=50),
        title=dict(text="Mailing List Sign-ups",
                   font=dict(size=18, color="#333"), x=0.5, xanchor="center"),
        paper_bgcolor="white",
        updatemenus=[dict(
            type="buttons", showactive=False,
            x=0.01, y=0.99, xanchor="left", yanchor="top",
            buttons=[
                dict(label="Play", method="animate",
                     args=[None, dict(
                         frame=dict(duration=frame_ms, redraw=True),
                         fromcurrent=True, transition=dict(duration=0),
                     )]),
                dict(label="Pause", method="animate",
                     args=[[None], dict(frame=dict(duration=0, redraw=False),
                                        mode="immediate")]),
            ],
        )],
        sliders=[dict(
            active=0, steps=slider_steps,
            x=0.05, len=0.9, y=0, yanchor="top",
            currentvalue=dict(prefix="Joined: ", font=dict(size=12, color="#333")),
            transition=dict(duration=0),
        )],
        showlegend=False, height=640,
        margin=dict(t=70, b=80, l=10, r=10),
        annotations=[dict(
            x=0.5, y=-0.08, xref="paper", yref="paper",
            text=legend_html, showarrow=False,
            font=dict(size=12, color="#333"), align="center",
        )],
    )

    if not show_chart:
        return fig, None

    # ── Vector post-script: mini cumulative chart ─────────────────────────
    chart_js = _chart_block(show_chart=True, dark=False)
    vec_post_script = f"""\
(function() {{
  var gd  = document.querySelector('.plotly-graph-div');
  var tms = {timestamps_ms_js};
  var n   = {n};
  var wrap = gd.closest('.js-plotly-plot') || gd.parentElement;
  wrap.style.position = 'relative';

  {chart_js}

  gd.on('plotly_animatingframe', function(e) {{
    var name = e.frame && e.frame.name;
    if (!name) return;
    var m = name.match(/frame_(\\d+)/);
    if (m) updateChart(parseInt(m[1], 10));
  }});
  gd.on('plotly_sliderchange', function(e) {{
    updateChart(e.slider.active);
  }});
}})();"""
    return fig, vec_post_script


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Animated mailing-list world map.")
    p.add_argument("--data",      default="data/mailing.tsv")
    p.add_argument("--map-style", default="vector", choices=["vector", "satellite"],
                   help="Map background: vector (default) or satellite imagery")
    p.add_argument("--speed",     default="normal",
                   choices=["slow", "normal", "fast", "instant"],
                   help="Animation speed (default: normal)")
    p.add_argument("--chart", action="store_true",
                   help="Overlay a cumulative sign-up line chart on the map")
    p.add_argument("--thresholds", default="1,2,3,4,5",
                   help="Comma-separated sign-up thresholds for heatmap colours "
                        "(default: 1,2,3,4,5 → 5 colours; e.g. 1,3,5,20 → 4 colours)")
    p.add_argument("--palette", default="BlRd",
                   help=f"Named palette ({', '.join(PALETTES)}) or comma-separated "
                        "CSS/hex colours matching the number of thresholds "
                        "(default: BlRd)")
    return p.parse_args()


def main():
    opts = parse_args()
    os.makedirs("output", exist_ok=True)

    print(f"Loading {opts.data} ...")
    df = load_mailing(opts.data)
    print(f"  {len(df)} subscribers, date range: "
          f"{df['date'].min().date()} – {df['date'].max().date()}")

    print("Geocoding companies ...")
    coords = geocode_all(df)

    df["lat"] = [c[0] if c else None for c in coords]
    df["lon"] = [c[1] if c else None for c in coords]

    missing = df[df["lat"].isna()]
    if not missing.empty:
        print(f"  WARNING: {len(missing)} entries could not be geocoded and will be skipped:")
        for _, r in missing.iterrows():
            print(f"    {r['Company']!r} ({r['Location']})")

    df = df.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    print(f"  {len(df)} entries with coordinates")

    if df.empty:
        print("ERROR: No geocoded entries. Exiting.")
        sys.exit(1)

    frame_ms  = SPEED_MS[opts.speed]
    satellite = opts.map_style == "satellite"

    try:
        thresholds = sorted(set(int(x.strip()) for x in opts.thresholds.split(",")))
        if not thresholds or thresholds[0] < 1:
            raise ValueError
    except ValueError:
        print("ERROR: --thresholds must be comma-separated positive integers, e.g. 1,3,5,20")
        sys.exit(1)
    palette_colors = _resolve_palette(opts.palette, len(thresholds))

    print(f"Building figure (map-style={opts.map_style}, speed={opts.speed} / {frame_ms}ms, "
          f"thresholds={thresholds}, palette={opts.palette}, chart={opts.chart}) ...")
    fig, post_script = build_figure(df, satellite=satellite, frame_ms=frame_ms,
                                    show_chart=opts.chart,
                                    thresholds=thresholds, palette_colors=palette_colors)

    write_kwargs = {"post_script": post_script} if post_script else {}
    fig.write_html(OUTPUT_HTML, **write_kwargs)
    print(f"Saved → {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
