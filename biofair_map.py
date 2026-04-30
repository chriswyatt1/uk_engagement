#!/usr/bin/env python3
"""
biofair_map.py  –  Animated BioFAIR engagement map.

Four panels:
  • World map  – all three sources combined, colour-coded
  • UK map     – mailing list subscribers
  • UK map     – BioFAIR events
  • UK map     – BioFAIR fellows engagements

Usage:
    python3 biofair_map.py
    python3 biofair_map.py --dot-map
    python3 biofair_map.py --speed fast --chart
"""

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# ── Paths ─────────────────────────────────────────────────────────────────────
MAILING_PATH  = "data/mailing.tsv"
EVENTS_PATH   = "data/biofair_events.csv"
FELLOWS_PATH  = "data/biofair_fellow.csv"
GEOCACHE_PATH = "data/geocache.json"
OUTPUT_HTML   = "output/biofair_map.html"

# ── Source colours / labels ───────────────────────────────────────────────────
SOURCE_COLOR = {"mailing": "#3b82f6", "events": "#f97316", "fellows": "#16a34a"}
SOURCE_LABEL = {"mailing": "Mailing List", "events": "BioFAIR Events", "fellows": "BioFAIR Fellows"}

# ── Geocoding overrides ───────────────────────────────────────────────────────
GEOCODE_OVERRIDES = {
    # mailing
    "Dur":                               "University of Durham, United Kingdom",
    "KCL":                               "King's College London, United Kingdom",
    "ARDC":                              "Australian Research Data Commons, Melbourne, Australia",
    "University of Oxford - IDDO":       "University of Oxford, United Kingdom",
    "Mary Lyon Centre at MRC Harwell":   "MRC Harwell, Oxfordshire, United Kingdom",
    "Croydon Health Services NHS Trust": "Croydon, London, United Kingdom",
    "National Police Chiefs' Council":   "Westminster, London, United Kingdom",
    "archives of chinese academy of sciences": "Chinese Academy of Sciences, Beijing, China",
    # events (location strings)
    "Hinxton": "Hinxton, Cambridgeshire, United Kingdom",
    # fellows – ambiguous / compound names
    "Supercomputing Wales (Cardiff/Bangor)":           "Cardiff, United Kingdom",
    "Isambard 3 supercomputer (GW4)":                  "Bristol, United Kingdom",
    "Supercomputing Wales (Swansea/Aberystwyth)":      "Swansea, United Kingdom",
    "GW4 (Cardiff, Bath, Bristol, Exeter)":            "Bristol, United Kingdom",
    "N8 Universities: Durham, Lancaster, Leeds, Liverpool, Manchester, Newcastle, Sheffield and York":
        "Leeds, United Kingdom",
    "University to Dundee":                            "Dundee, United Kingdom",
    "HDR-UK Glasgow":                                  "Glasgow, United Kingdom",
    "RMS Newcastle":                                   "Newcastle upon Tyne, United Kingdom",
    "OME-NGFF":                                        "Dundee, United Kingdom",
    "ELIXIR-UK Training Club":                         "Hinxton, Cambridgeshire, United Kingdom",
    "Scottish BioMedical Roundtable":                  "Glasgow, United Kingdom",
    "UKRI DRI Retreat":                                "Manchester, United Kingdom",
    "EPSRC/N-CODE":                                    "London, United Kingdom",
    "EPSRC/N-CODE workshop - Wearables/EEG for Neurodegenerative Diseases": "London, United Kingdom",
    "nf-core hackathon training":                      "London, United Kingdom",
    "nf-core London local site hackathon":             "London, United Kingdom",
    "AIBIO-UK EMBL-EBI workshop":                      "Hinxton, Cambridgeshire, United Kingdom",
    "AIBIO-UK EMBL-EBI AI Data Readiness workshop":    "Hinxton, Cambridgeshire, United Kingdom",
    "NorthernBUG15 meeting":                           "Newcastle upon Tyne, United Kingdom",
    "BSCB/Biochemical Society Dynamic Cell VI Conference": "Cambridge, United Kingdom",
    "N8 UKRI digital research infrastrcuture retreat": "York, United Kingdom",
    "EMBL-EBI imaging course":                         "Hinxton, Cambridgeshire, United Kingdom",
    "UK Dementia Research Institute (UK DRI) ECR Informatics Committee": "London, United Kingdom",
    "UK Dementia Research Institute (UK DRI) Cambridge":   "Cambridge, United Kingdom",
    "UK Dementia Research Institute (UK DRI) Cardiff":     "Cardiff, United Kingdom",
    "UK Dementia Research Institute (UK DRI) Edinburgh":   "Edinburgh, United Kingdom",
    "UK Dementia Research Institute (UK DRI) Imperial":    "South Kensington, London, United Kingdom",
    "UK Dementia Research Institute (UK DRI) King's":      "Denmark Hill, London, United Kingdom",
    "UK Dementia Research Institute (UK DRI) UCL":         "Bloomsbury, London, United Kingdom",
    "UK Dementia Research Institute (UK DRI) Care Research and Technology Centre": "London, United Kingdom",
    "UK Dementia Research Institute (UK DRI) BHF-UK Centre for Vascular Dementia Research": "Edinburgh, United Kingdom",
    "UK Dementia Research Institute (UK DRI) Parkinson's Research Centre": "Edinburgh, United Kingdom",
    "UK Dementia Research Institute FAIR Workshop":    "London, United Kingdom",
    "Understanding Life (Understanding Life: Using Largescale Biodiversity Reference Genomes)":
        "Wellcome Sanger Institute, Hinxton, United Kingdom",
    "Bioinformatics MSc Lecture":                      "Belfast, United Kingdom",
    "Festival of genomics and biodata":                "London, United Kingdom",
    "Building a comprehensive and coordinated training landscape for dRTPs": "London, United Kingdom",
    "British Ecology Society Conference":              "Edinburgh, United Kingdom",
    "deNBI hackathon 2025":                            "Bielefeld, Germany",
    "Cambridge ISCB Uk conference":                    "Cambridge, United Kingdom",
    "Euro-BioImaging FAIR Image Data Workflows Expert Group": "Amsterdam, Netherlands",
    # drop – online or too ambiguous to resolve to a specific place
    "WorkflowHub Community Call":                      None,
    "WorkflowHub Publishers Forum (online)":           None,
    "BSCB NextGen - online seminar for ECRs":          None,
    "Wales Kidney Research Unit":                      None,
    "University College London (Centre of biodiversity and the environment)": None,
}

COUNTRY_CODE_MAP = {
    "United Kingdom": "gb", "Australia": "au", "Japan": "jp", "United States": "us",
}

BORING_LABELS = {
    "", "United Kingdom", "United States", "Australia", "Japan",
    "Ireland", "Greece", "France", "Canada", "Spain", "Netherlands",
    "Uganda", "Turkey", "Germany", "Egypt", "China", "India", "Brazil",
    "South Africa", "Italy", "Sweden", "Norway", "Denmark", "Finland",
    "Belgium", "Switzerland", "Austria", "Poland", "Portugal", "Israel",
    "New Zealand", "South Korea",
}

# ── Dot-grid constants ────────────────────────────────────────────────────────
DOT_SPACING        = 0.35
UK_DOT_LAT_SPACING = DOT_SPACING * math.cos(math.radians(55.0))
UK_LAND_GEOJSON    = "data/ne_50m_admin_0_gbr.geojson"
WORLD_LAND_GEOJSON = "data/ne_50m_land.geojson"
WORLD_LAND_URL     = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
                      "master/geojson/ne_50m_land.geojson")
_UK_COUNTRIES_URL  = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
                      "master/geojson/ne_50m_admin_0_countries.geojson")
WORLD_DOT_SPACING  = 4.0
DOT_BG_COLOR       = "#6ee7b7"

SPEED_MS = {"slow": 1500, "normal": 800, "fast": 300, "instant": 80}

PALETTES = {
    "BlRd":    ["#3b82f6","#06b6d4","#22d3ee","#4ade80","#a3e635",
                "#facc15","#fb923c","#f87171","#ef4444","#b91c1c"],
    "RdBl":    ["#b91c1c","#ef4444","#f87171","#fb923c","#facc15",
                "#a3e635","#4ade80","#22d3ee","#06b6d4","#3b82f6"],
    "warm":    ["#fef9c3","#fef08a","#fde047","#facc15","#fb923c",
                "#f97316","#ef4444","#dc2626","#b91c1c","#7f1d1d"],
    "cool":    ["#e0f2fe","#bae6fd","#7dd3fc","#60a5fa","#818cf8",
                "#a78bfa","#c084fc","#e879f9","#f0abfc","#fbcfe8"],
    "viridis": ["#440154","#482878","#3e4989","#31688e","#26828e",
                "#1f9e89","#35b779","#6ece58","#b5de2b","#fde725"],
    "greys":   ["#f3f4f6","#d1d5db","#9ca3af","#6b7280","#4b5563",
                "#374151","#1f2937","#111827","#030712","#000000"],
}

DEFAULT_THRESHOLDS = [1, 2, 3, 4, 5]


# ── Geocoding ─────────────────────────────────────────────────────────────────

def load_geocache():
    p = Path(GEOCACHE_PATH)
    return json.load(open(p)) if p.exists() else {}


def save_geocache(cache):
    Path(GEOCACHE_PATH).parent.mkdir(parents=True, exist_ok=True)
    json.dump(cache, open(GEOCACHE_PATH, "w"), indent=2)


def geocode_company(company, country, cache, geolocator):
    query = GEOCODE_OVERRIDES.get(company, company)
    if query is None:
        cache[company] = None
        return None
    cc = COUNTRY_CODE_MAP.get(country)
    for key in [query, f"{query}, {country}"]:
        if key in cache:
            entry = cache[key]
            return tuple(entry) if entry else None
    print(f"  Geocoding {query!r} ...", end=" ", flush=True)
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
        print("ERROR: pip install geopy")
        sys.exit(1)
    cache = load_geocache()
    geolocator = Nominatim(user_agent="biofair_map/1.0")
    uncached = []
    for _, row in df.iterrows():
        company = str(row.get("Company", "")).strip()
        country = str(row.get("Location", "")).strip()
        query = GEOCODE_OVERRIDES.get(company, company) if company else country
        if query and query not in cache and f"{query}, {country}" not in cache:
            uncached.append(query)
    unique_uncached = list(dict.fromkeys(u for u in uncached if u is not None))
    if unique_uncached:
        print(f"  {len(unique_uncached)} new entries to geocode "
              f"(~{len(unique_uncached)} sec): "
              + ", ".join(repr(u) for u in unique_uncached))
    else:
        print("  All entries found in geocache.")
    results = []
    first_call = True
    for _, row in df.iterrows():
        company = str(row.get("Company", "")).strip()
        country = str(row.get("Location", "")).strip()
        query = GEOCODE_OVERRIDES.get(company, company) if company else country
        if query is None:
            results.append(None)
            continue
        key = query
        if key in cache:
            entry = cache[key]
            results.append(tuple(entry) if entry else None)
            continue
        fallback = f"{query}, {country}"
        if fallback in cache:
            entry = cache[fallback]
            results.append(tuple(entry) if entry else None)
            continue
        if not first_call:
            time.sleep(1.1)
        first_call = False
        results.append(geocode_company(company, country, cache, geolocator))
    return results


# ── Dot-grid helpers ──────────────────────────────────────────────────────────

def _polys_from_geojson(gj):
    polys = []
    for feat in gj.get("features", []):
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [])
        if geom.get("type") == "Polygon":
            polys.append([(lat, lon) for lon, lat in coords[0]])
        elif geom.get("type") == "MultiPolygon":
            for part in coords:
                polys.append([(lat, lon) for lon, lat in part[0]])
    return polys


def _fetch_uk_land():
    p = Path(UK_LAND_GEOJSON)
    if p.exists():
        return json.load(open(p))
    import urllib.request
    cp = Path("data/ne_50m_admin_0_countries.geojson")
    if not cp.exists():
        print("  Fetching country boundaries ...")
        cp.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(_UK_COUNTRIES_URL, cp)
    all_gj = json.load(open(cp))
    uk_features = [f for f in all_gj.get("features", [])
                   if f.get("properties", {}).get("ISO_A3") in ("GBR",)
                   or f.get("properties", {}).get("ADM0_A3") in ("GBR",)]
    uk_gj = {"type": "FeatureCollection", "features": uk_features}
    json.dump(uk_gj, open(p, "w"))
    return uk_gj


def _fetch_world_land():
    p = Path(WORLD_LAND_GEOJSON)
    if p.exists():
        return json.load(open(p))
    import urllib.request
    print(f"  Fetching world land data → {WORLD_LAND_GEOJSON} ...")
    p.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(WORLD_LAND_URL, p)
    return json.load(open(p))


def _grid_inside(gj, lats, lons, lat_step, lon_step):
    import numpy as np
    polys = _polys_from_geojson(gj)
    all_lats = np.array(lats)
    all_lons = np.array(lons)
    inside = np.zeros(len(all_lats), dtype=bool)
    for poly in polys:
        py = np.array([p[0] for p in poly])
        px = np.array([p[1] for p in poly])
        bb = ((all_lats >= py.min() - lat_step) & (all_lats <= py.max() + lat_step) &
              (all_lons >= px.min() - lon_step) & (all_lons <= px.max() + lon_step))
        idx = np.where(bb)[0]
        if not len(idx):
            continue
        sl, so = all_lats[idx], all_lons[idx]
        sub = np.zeros(len(idx), dtype=bool)
        n = len(poly)
        for i in range(n):
            j = (i - 1) % n
            yi, xi = py[i], px[i]
            yj, xj = py[j], px[j]
            c1 = (yi > sl) != (yj > sl)
            slope = (xj - xi) * (sl - yi) / (yj - yi + 1e-12) + xi
            sub ^= c1 & (so < slope)
        inside[idx] ^= sub
    return inside


def generate_uk_dots(lon_spacing=DOT_SPACING, lat_spacing=UK_DOT_LAT_SPACING):
    gj = _fetch_uk_land()
    row_lats, row_lons = [], []
    lat = 49.5
    while lat <= 61.0:
        lon = -9.0
        while lon <= 2.5:
            row_lats.append(round(lat, 4))
            row_lons.append(round(lon, 4))
            lon += lon_spacing
        lat += lat_spacing
    inside = _grid_inside(gj, row_lats, row_lons, lat_spacing, lon_spacing)
    return [(float(row_lats[i]), float(row_lons[i])) for i in range(len(row_lats)) if inside[i]]


def generate_world_dots(spacing=WORLD_DOT_SPACING):
    gj = _fetch_world_land()
    row_lats, row_lons = [], []
    lat = -58.0
    while lat <= 80.0:
        lon = -180.0
        while lon <= 180.0:
            row_lats.append(round(lat, 2))
            row_lons.append(round(lon, 2))
            lon += spacing
        lat += spacing
    inside = _grid_inside(gj, row_lats, row_lons, spacing, spacing)
    return [(float(row_lats[i]), float(row_lons[i])) for i in range(len(row_lats)) if inside[i]]


def _snap_to_grid(lat, lon, grid):
    best, best_d = grid[0], float("inf")
    for dlat, dlon in grid:
        d = (dlat - lat) ** 2 + (dlon - lon) ** 2
        if d < best_d:
            best_d = d
            best = (dlat, dlon)
    return best


def _snap_all_world(lats, lons, grid):
    sl, so = [], []
    for lat, lon in zip(lats, lons):
        s = _snap_to_grid(lat, lon, grid)
        sl.append(s[0]); so.append(s[1])
    return sl, so


def _snap_all_uk(lats, lons, grid):
    uk_lat = (49.0, 62.0); uk_lon = (-9.0, 3.0)
    sl, so = [], []
    for lat, lon in zip(lats, lons):
        if uk_lat[0] <= lat <= uk_lat[1] and uk_lon[0] <= lon <= uk_lon[1]:
            s = _snap_to_grid(lat, lon, grid)
            sl.append(s[0]); so.append(s[1])
        else:
            sl.append(lat); so.append(lon)
    return sl, so


# ── Data loading ──────────────────────────────────────────────────────────────

def load_mailing(path):
    df = pd.read_csv(path, sep="\t", dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df["date"]     = pd.to_datetime(df["Subscribed"], dayfirst=True, errors="coerce")
    df["Company"]  = df["Company"].fillna("").str.strip()
    df["Location"] = df["Location"].fillna("").str.strip()
    df["display"]  = df["Company"]
    df["source"]   = "mailing"
    df = df[df["date"].notna() & (df["Company"].str.len() > 0)]
    return df[["date", "Company", "Location", "display", "source"]].sort_values("date").reset_index(drop=True)


def load_events(path):
    df = pd.read_csv(path, sep="\t", header=None, dtype=str,
                     names=["date_str", "display", "Location"])
    df["date"] = pd.to_datetime(df["date_str"].str.strip(), format="%B %Y", errors="coerce")
    df["Company"] = df["Location"].str.strip()   # geocode by city/location
    df["Location"] = df["Location"].str.strip()
    df["display"]  = df["display"].str.strip()
    df["source"]   = "events"
    df = df[df["date"].notna() & df["Company"].str.len().gt(0)]
    return df[["date", "Company", "Location", "display", "source"]].sort_values("date").reset_index(drop=True)


def _parse_fellow_date(s):
    s = s.strip()
    for fmt in ["%b-%y", "%b, %Y", "%b %Y"]:
        try:
            return pd.to_datetime(s, format=fmt)
        except Exception:
            pass
    return pd.NaT


def load_fellows(path):
    df = pd.read_csv(path, sep="\t", header=None, dtype=str,
                     names=["date_str", "Company"])
    df["date"]    = df["date_str"].apply(_parse_fellow_date)
    df["Company"] = df["Company"].str.strip()
    df["display"] = df["Company"]
    df["Location"] = "United Kingdom"
    # drop online-only entries (will have no useful geocoordinate anyway)
    df = df[~df["Company"].str.contains(r"\(online\)", case=False, na=False)]
    df["source"]  = "fellows"
    df = df[df["date"].notna() & df["Company"].str.len().gt(0)]
    return df[["date", "Company", "Location", "display", "source"]].sort_values("date").reset_index(drop=True)


def load_all():
    print("Loading mailing list ...")
    dm = load_mailing(MAILING_PATH)
    print(f"  {len(dm)} rows, {dm['date'].min().date()} – {dm['date'].max().date()}")

    print("Loading events ...")
    de = load_events(EVENTS_PATH)
    print(f"  {len(de)} rows, {de['date'].min().date()} – {de['date'].max().date()}")

    print("Loading fellows ...")
    df = load_fellows(FELLOWS_PATH)
    print(f"  {len(df)} rows, {df['date'].min().date()} – {df['date'].max().date()}")

    merged = pd.concat([dm, de, df], ignore_index=True).sort_values("date").reset_index(drop=True)
    print(f"Combined: {len(merged)} rows")
    return merged


# ── Colour helpers ────────────────────────────────────────────────────────────

def _sample_palette(colors, n):
    if n == 1:
        return [colors[-1]]
    return [colors[round(i * (len(colors) - 1) / (n - 1))] for i in range(n)]


def _resolve_palette(palette_str, n):
    if palette_str in PALETTES:
        return _sample_palette(PALETTES[palette_str], n)
    colors = [c.strip() for c in palette_str.split(",") if c.strip()]
    return _sample_palette(colors, n) if len(colors) != n else colors


def _heat_color(count, thresholds, palette_colors):
    idx = 0
    for i, t in enumerate(thresholds):
        if count >= t:
            idx = i
    return palette_colors[idx]


def precompute_heatmap(sub_df, thresholds, palette_colors):
    """Return (colors_by_k, perms_by_k) indexed 0..n (k = number revealed)."""
    n = len(sub_df)
    lats = sub_df["lat"].tolist()
    lons = sub_df["lon"].tolist()
    loc_key = [f"{round(lats[i], 2)},{round(lons[i], 2)}" for i in range(n)]

    colors_by_k = [["rgba(0,0,0,0)"] * n]
    perms_by_k  = [list(range(n))]
    loc_count   = defaultdict(int)

    for k in range(1, n + 1):
        loc_count[loc_key[k - 1]] += 1
        colors = [
            _heat_color(loc_count[loc_key[i]], thresholds, palette_colors) if i < k
            else "rgba(0,0,0,0)"
            for i in range(n)
        ]
        count_at = [loc_count[loc_key[i]] if i < k else 0 for i in range(n)]
        perm = sorted(range(n), key=lambda i: count_at[i])
        colors_by_k.append(colors)
        perms_by_k.append(perm)

    return colors_by_k, perms_by_k


# ── Figure builder ────────────────────────────────────────────────────────────

def _interesting(label):
    return bool(label) and label not in BORING_LABELS


def build_figure(df, frame_ms=800, show_chart=False, thresholds=None,
                 palette_colors=None, dot_map=False):

    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    if palette_colors is None:
        palette_colors = _sample_palette(PALETTES["BlRd"], len(thresholds))

    # Split by source (already date-sorted in merged df)
    df_m = df[df["source"] == "mailing"].reset_index(drop=True)
    df_e = df[df["source"] == "events"].reset_index(drop=True)
    df_f = df[df["source"] == "fellows"].reset_index(drop=True)
    n, n_m, n_e, n_f = len(df), len(df_m), len(df_e), len(df_f)

    # Per-frame counts revealed of each source
    km_arr, ke_arr, kf_arr = [], [], []
    km = ke = kf = 0
    for src in df["source"]:
        if src == "mailing": km += 1
        elif src == "events": ke += 1
        else: kf += 1
        km_arr.append(km); ke_arr.append(ke); kf_arr.append(kf)

    dates     = df["date"].tolist()
    labels    = df["display"].tolist()
    sources   = df["source"].tolist()
    lats      = df["lat"].tolist()
    lons      = df["lon"].tolist()

    timestamps_ms_js = json.dumps([int(d.timestamp() * 1000) for d in dates])
    dates_js   = json.dumps([d.strftime("%d %b %Y") for d in dates])
    labels_js  = json.dumps(labels)
    sources_js = json.dumps(sources)

    hover_all = [
        f"<b>{labels[i]}</b><br>{dates[i].strftime('%d %b %Y')}"
        for i in range(n)
    ]
    hover_m = [f"<b>{df_m['display'].iloc[i]}</b><br>{df_m['date'].iloc[i].strftime('%d %b %Y')}" for i in range(n_m)]
    hover_e = [f"<b>{df_e['display'].iloc[i]}</b><br>{df_e['date'].iloc[i].strftime('%d %b %Y')}" for i in range(n_e)]
    hover_f = [f"<b>{df_f['display'].iloc[i]}</b><br>{df_f['date'].iloc[i].strftime('%d %b %Y')}" for i in range(n_f)]

    # Precompute UK heatmaps per source
    m_colors_by_k, m_perms_by_k = precompute_heatmap(df_m, thresholds, palette_colors)
    e_colors_by_k, e_perms_by_k = precompute_heatmap(df_e, thresholds, palette_colors)
    f_colors_by_k, f_perms_by_k = precompute_heatmap(df_f, thresholds, palette_colors)

    slider_steps = [
        dict(
            label=dates[i].strftime("%d %b %Y"),
            method="skip",
            args=[[f"frame_{i}"], dict(mode="immediate",
                                       frame=dict(duration=0, redraw=True),
                                       transition=dict(duration=0))],
        )
        for i in range(n)
    ]

    thresh_labels = [str(t) for t in thresholds[:-1]] + [f"{thresholds[-1]}+"]
    legend_html = (
        "  ".join(
            f'<span style="color:{c}">●</span> {lbl}'
            for c, lbl in zip(palette_colors, thresh_labels)
        ) + "&nbsp; engagements at location"
    )

    # ── Single row of 3 UK panels ─────────────────────────────────────────────
    geo_base = GEO_BLANK if dot_map else GEO_COMMON
    uk_geo   = dict(lonaxis=dict(range=[-9, 3]), lataxis=dict(range=[49, 62]),
                    resolution=50, projection_type="mercator")

    fig = make_subplots(
        rows=1, cols=3,
        horizontal_spacing=0.02,
        specs=[[{"type": "geo"}, {"type": "geo"}, {"type": "geo"}]],
        subplot_titles=[
            f"UK — {SOURCE_LABEL['mailing']}",
            f"UK — {SOURCE_LABEL['events']}",
            f"UK — {SOURCE_LABEL['fellows']}",
        ],
    )

    empty_sz = [0]
    empty_c  = ["rgba(0,0,0,0)"]

    def _scat(lat_, lon_, sz, c, tx, ht_, geo_ref, fs=10):
        return go.Scattergeo(
            lat=lat_, lon=lon_, mode="markers+text",
            marker=dict(size=sz, color=c, opacity=0.9,
                        line=dict(width=1, color="white")),
            text=tx, textposition="top center",
            textfont=dict(size=fs, color="#1e1b4b", family="Arial Bold"),
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

    if dot_map:
        print("  Building UK dot grid ...")
        uk_grid = generate_uk_dots()
        print(f"    {len(uk_grid)} UK dots")

        um_lats, um_lons = _snap_all_uk(df_m["lat"].tolist(), df_m["lon"].tolist(), uk_grid)
        ue_lats, ue_lons = _snap_all_uk(df_e["lat"].tolist(), df_e["lon"].tolist(), uk_grid)
        uf_lats, uf_lons = _snap_all_uk(df_f["lat"].tolist(), df_f["lon"].tolist(), uk_grid)

        # Background traces (indices 0–2), subscriber traces (indices 3–5)
        fig.add_trace(_bg(uk_grid, "geo"),  row=1, col=1)  # 0
        fig.add_trace(_bg(uk_grid, "geo2"), row=1, col=2)  # 1
        fig.add_trace(_bg(uk_grid, "geo3"), row=1, col=3)  # 2

        fig.add_trace(_scat(um_lats, um_lons, empty_sz, empty_c, [""], hover_m, "geo"),  row=1, col=1)  # 3
        fig.add_trace(_scat(ue_lats, ue_lons, empty_sz, empty_c, [""], hover_e, "geo2"), row=1, col=2)  # 4
        fig.add_trace(_scat(uf_lats, uf_lons, empty_sz, empty_c, [""], hover_f, "geo3"), row=1, col=3)  # 5

        fig.frames = []
        frame_json = json.dumps({
            "km": km_arr, "ke": ke_arr, "kf": kf_arr,
            "mc": m_colors_by_k, "mp": m_perms_by_k,
            "ec": e_colors_by_k, "ep": e_perms_by_k,
            "fc": f_colors_by_k, "fp": f_perms_by_k,
        })

    else:
        # Vector mode – subscriber traces only (indices 0–2)
        um_lats, um_lons = df_m["lat"].tolist(), df_m["lon"].tolist()
        ue_lats, ue_lons = df_e["lat"].tolist(), df_e["lon"].tolist()
        uf_lats, uf_lons = df_f["lat"].tolist(), df_f["lon"].tolist()

        fig.add_trace(_scat(um_lats, um_lons, empty_sz, empty_c, [""], hover_m, "geo"),  row=1, col=1)  # 0
        fig.add_trace(_scat(ue_lats, ue_lons, empty_sz, empty_c, [""], hover_e, "geo2"), row=1, col=2)  # 1
        fig.add_trace(_scat(uf_lats, uf_lons, empty_sz, empty_c, [""], hover_f, "geo3"), row=1, col=3)  # 2

        def ws(k, n_src, large, small):
            return [large if j == k-1 else small if j < k else 0 for j in range(n_src)]
        def pa(arr, perm): return [arr[j] for j in perm]

        UK_LARGE, UK_SMALL = 22, 12
        plotly_frames = []
        for i in range(n):
            km, ke, kf = km_arr[i], ke_arr[i], kf_arr[i]
            mp = m_perms_by_k[km]; ep = e_perms_by_k[ke]; fp = f_perms_by_k[kf]
            mc = m_colors_by_k[km]; ec = e_colors_by_k[ke]; fc = f_colors_by_k[kf]
            plotly_frames.append(go.Frame(
                name=f"frame_{i}",
                data=[
                    _scat(pa(um_lats, mp), pa(um_lons, mp), pa(ws(km, n_m, UK_LARGE, UK_SMALL), mp), pa(mc, mp), [""]*n_m, pa(hover_m, mp), "geo"),
                    _scat(pa(ue_lats, ep), pa(ue_lons, ep), pa(ws(ke, n_e, UK_LARGE, UK_SMALL), ep), pa(ec, ep), [""]*n_e, pa(hover_e, ep), "geo2"),
                    _scat(pa(uf_lats, fp), pa(uf_lons, fp), pa(ws(kf, n_f, UK_LARGE, UK_SMALL), fp), pa(fc, fp), [""]*n_f, pa(hover_f, fp), "geo3"),
                ],
            ))
        fig.frames = plotly_frames
        frame_json = "{}"

    fig.update_layout(
        geo=dict(**geo_base,  **uk_geo),
        geo2=dict(**geo_base, **uk_geo),
        geo3=dict(**geo_base, **uk_geo),
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
                      args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")])]
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
        annotations=[dict(
            x=0.5, y=-0.08, xref="paper", yref="paper",
            text=legend_html, showarrow=False,
            font=dict(size=12, color="#333"), align="center",
        )],
    )

    if not (dot_map or show_chart):
        return fig, None

    # ── JS post-script ────────────────────────────────────────────────────────

    UK_LARGE = 22;  UK_SMALL = 12
    bg_offset = 3 if dot_map else 0   # subscriber traces start at 3 (dot_map) or 0 (vector)

    post_script = f"""\
(function() {{
  var gd = document.querySelector('.plotly-graph-div');
  var wrap = gd.closest('.js-plotly-plot') || gd.parentElement;
  wrap.style.position = 'relative';

  var n   = {n};
  var n_m = {n_m}, n_e = {n_e}, n_f = {n_f};
  var ms  = {frame_ms};
  var tms = {timestamps_ms_js};
  var dateStrs = {dates_js};
  var labels   = {labels_js};
  var sources  = {sources_js};

  var COL_M = '{SOURCE_COLOR["mailing"]}', COL_E = '{SOURCE_COLOR["events"]}', COL_F = '{SOURCE_COLOR["fellows"]}';
  var UK_LARGE = {UK_LARGE}, UK_SMALL = {UK_SMALL};
  var BG = {bg_offset};

  var fdata = {frame_json};
  var km_arr = fdata.km, ke_arr = fdata.ke, kf_arr = fdata.kf;
  var mc_k = fdata.mc, mp_k = fdata.mp;
  var ec_k = fdata.ec, ep_k = fdata.ep;
  var fc_k = fdata.fc, fp_k = fdata.fp;

  var lat0_m = gd.data[BG+0].lat.slice(), lon0_m = gd.data[BG+0].lon.slice();
  var lat0_e = gd.data[BG+1].lat.slice(), lon0_e = gd.data[BG+1].lon.slice();
  var lat0_f = gd.data[BG+2].lat.slice(), lon0_f = gd.data[BG+2].lon.slice();
  var ht_m = gd.data[BG+0].hovertext.slice();
  var ht_e = gd.data[BG+1].hovertext.slice();
  var ht_f = gd.data[BG+2].hovertext.slice();

  // ── Info panel ─────────────────────────────────────────────────────────────
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

  var SRC_COL = {{mailing: COL_M, events: COL_E, fellows: COL_F}};
  var SRC_LBL = {{mailing: 'Mailing', events: 'Event', fellows: 'Fellow'}};

  function updatePanel(i) {{
    var lbl = labels[i], src = sources[i];
    if (lbl && lbl.length > 1) {{
      recent.unshift({{name: lbl, date: dateStrs[i], src: src}});
      if (recent.length > 14) recent.pop();
    }}
    if (!recent.length) {{ panel.innerHTML = ''; return; }}
    var html = '<div style="font-size:9px;opacity:0.55;margin-bottom:8px;'
             + 'letter-spacing:.08em;text-transform:uppercase">Recent</div>';
    recent.forEach(function(r, ri) {{
      var op = Math.max(0.3, 1 - ri * 0.06);
      var sz = ri === 0 ? '12px' : '11px';
      var wt = ri === 0 ? 'bold' : 'normal';
      var col = SRC_COL[r.src] || '#333';
      html += '<div style="margin-bottom:5px;opacity:' + op
            + ';border-left:2px solid ' + col + ';padding-left:6px">'
            + '<div style="font-size:8px;color:' + col + ';opacity:0.8">' + (SRC_LBL[r.src]||'') + '</div>'
            + '<span style="font-size:' + sz + ';font-weight:' + wt
            + ';color:#1e1b4b">' + r.name + '</span>'
            + '<br><span style="font-size:9px;opacity:0.6">' + r.date + '</span>'
            + '</div>';
    }});
    panel.innerHTML = html;
  }}

  function pa(arr, perm) {{ return perm.map(function(j) {{ return arr[j]; }}); }}

  function makeWorldSizes(k, n_src, large, small) {{
    var s = [];
    for (var j = 0; j < n_src; j++) {{
      s.push(j === k-1 ? large : j < k ? small : 0);
    }}
    return s;
  }}

  function applyData(i) {{
    var km = km_arr[i], ke = ke_arr[i], kf = kf_arr[i];
    var mp = mp_k[km], ep = ep_k[ke], fp = fp_k[kf];
    var mc = mc_k[km], ec = ec_k[ke], fc = fc_k[kf];

    updatePanel(i);

    var sz_m = mp.map(function(j) {{ return j===km-1?UK_LARGE:j<km?UK_SMALL:0; }});
    var sz_e = ep.map(function(j) {{ return j===ke-1?UK_LARGE:j<ke?UK_SMALL:0; }});
    var sz_f = fp.map(function(j) {{ return j===kf-1?UK_LARGE:j<kf?UK_SMALL:0; }});

    var p = Plotly.restyle(gd, {{
      'lat':          [pa(lat0_m,mp), pa(lat0_e,ep), pa(lat0_f,fp)],
      'lon':          [pa(lon0_m,mp), pa(lon0_e,ep), pa(lon0_f,fp)],
      'hovertext':    [pa(ht_m,mp),   pa(ht_e,ep),   pa(ht_f,fp)],
      'marker.size':  [sz_m, sz_e, sz_f],
      'marker.color': [pa(mc,mp), pa(ec,ep), pa(fc,fp)],
    }}, [BG, BG+1, BG+2]);

    return (p && p.then) ? p : Promise.resolve();
  }}

  function applyFull(i) {{
    recent = [];
    for (var j = 0; j <= i; j++) {{
      var lbl = labels[j];
      if (lbl && lbl.length > 1)
        recent.push({{name: lbl, date: dateStrs[j], src: sources[j]}});
    }}
    recent = recent.slice(-14).reverse();
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


# ── Map style helpers ─────────────────────────────────────────────────────────

GEO_COMMON = dict(
    showland=True,       landcolor="rgb(242, 237, 230)",
    showcoastlines=True, coastlinecolor="rgb(155, 155, 155)", coastlinewidth=1,
    showocean=True,      oceancolor="rgb(218, 232, 245)",
    showcountries=True,  countrycolor="rgb(200, 200, 200)",
    bgcolor="rgba(0,0,0,0)",
)
GEO_BLANK = dict(
    showland=False, showocean=False, showcoastlines=False,
    showcountries=False, showframe=False, bgcolor="rgba(0,0,0,0)",
)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Animated BioFAIR engagement map.")
    p.add_argument("--speed", default="normal",
                   choices=["slow", "normal", "fast", "instant"])
    p.add_argument("--chart", action="store_true",
                   help="Overlay cumulative chart (not yet implemented for multi-source)")
    p.add_argument("--thresholds", default="1,2,3,4,5")
    p.add_argument("--palette", default="BlRd",
                   help=f"Named palette ({', '.join(PALETTES)}) or comma-separated hex colours")
    p.add_argument("--dot-map", action="store_true",
                   help="Render maps as dot-grid silhouettes (recommended)")
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
        print("ERROR: --thresholds must be positive integers, e.g. 1,3,5,20")
        sys.exit(1)

    palette_colors = _resolve_palette(opts.palette, len(thresholds))
    frame_ms = SPEED_MS[opts.speed]
    dot_map  = opts.dot_map

    print(f"Building figure (dot-map={dot_map}, speed={opts.speed}) ...")
    fig, post_script = build_figure(
        df, frame_ms=frame_ms, show_chart=opts.chart,
        thresholds=thresholds, palette_colors=palette_colors,
        dot_map=dot_map,
    )

    write_kwargs = {"post_script": post_script} if post_script else {}
    fig.write_html(OUTPUT_HTML, **write_kwargs)
    print(f"Saved → {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
