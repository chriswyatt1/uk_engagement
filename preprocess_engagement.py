#!/usr/bin/env python3
"""
preprocess_engagement.py
------------------------
Converts a raw engagement spreadsheet into the CSV format expected by
uk_engagement_map.py (columns: name, lat, lon, <period1>, <period2>, ...).

What it does
  1. Reads a TSV, CSV, or Excel file
  2. Picks out the period, location, and engagement-count columns
  3. Normalises period strings  →  "Oct 2025"  (handles "Oct, 2025", "October 2025", etc.)
  4. Geocodes location names via OpenStreetMap/Nominatim (free, no API key)
     and caches results so repeated runs don't re-query
  5. Aggregates (sums) engagement per location × period
  6. Pivots to wide format and writes the output CSV

Usage:
    python3 preprocess_engagement.py raw_data.tsv
    python3 preprocess_engagement.py raw_data.xlsx -o data/engagement.csv
    python3 preprocess_engagement.py raw_data.tsv --geocache data/geocache.json
    python3 preprocess_engagement.py raw_data.tsv \\
        --col-period "Month, Year" \\
        --col-location "Location" \\
        --col-engagement "Number of people or views"

Requirements:
    pip install pandas geopy openpyxl
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd


# ── Fuzzy column detection ────────────────────────────────────────────────────
# Patterns matched (case-insensitive) against column names.
# First match wins; override with --col-* flags if auto-detection is wrong.

COL_PERIOD_HINTS     = ["month", "date", "period", "year"]
COL_LOCATION_HINTS   = ["location", "venue", "place", "city"]
COL_ENGAGEMENT_HINTS = ["number of people", "people", "views", "attendance", "count"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_col_name(name):
    """Strip surrounding quotes and collapse whitespace/newlines."""
    return re.sub(r"\s+", " ", str(name).replace('"', "").replace("\n", " ")).strip()


def find_col(df, hints):
    """Return the first column name whose cleaned form contains any hint."""
    for col in df.columns:
        cleaned = _clean_col_name(col).lower()
        for hint in hints:
            if hint in cleaned:
                return col
    return None


def load_input(path):
    path = Path(path)
    if path.suffix in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=str)
    # Try tab-separated first (most common for copied spreadsheets)
    try:
        df = pd.read_csv(path, sep="\t", dtype=str)
        if df.shape[1] > 1:
            return df
    except Exception:
        pass
    return pd.read_csv(path, dtype=str)


def normalise_period(raw):
    """
    Normalise a variety of period strings to 'Mon YYYY' format.

    Handles: "Oct, 2025"  "Oct 2025"  "October 2025"  "Jan 2026"  "01/2026"
    Returns None if the string cannot be parsed.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip()
    # Remove commas and collapse whitespace
    s = re.sub(r",", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Try common formats
    for fmt in ("%b %Y", "%B %Y", "%m/%Y", "%m %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%b %Y")
        except ValueError:
            pass
    return None


def period_sort_key(period_str):
    try:
        return datetime.strptime(period_str, "%b %Y")
    except ValueError:
        return datetime.min


# ── Geocoding ─────────────────────────────────────────────────────────────────

def geocode_locations(locations, cache_path):
    """
    Geocode a list of location strings using Nominatim (OpenStreetMap).

    Results are persisted to a JSON cache so re-running the script doesn't
    re-query the API.  Nominatim's terms require ≤ 1 request per second.

    Returns dict: {location_str: (lat, lon)}  — missing entries were not found.
    """
    try:
        from geopy.geocoders import Nominatim
        from geopy.exc import GeocoderTimedOut
    except ImportError:
        print("ERROR: geopy is required.  Install with:  pip install geopy")
        sys.exit(1)

    cache = {}
    cache_path = Path(cache_path) if cache_path else None
    if cache_path and cache_path.exists():
        with open(cache_path) as f:
            cache = json.load(f)
        print(f"  Loaded {len(cache)} cached geocoding results from {cache_path}")

    geolocator = Nominatim(user_agent="uk_engagement_map_preprocess/1.0")
    results    = {}
    new_hits   = 0

    for loc in locations:
        loc = loc.strip()
        if not loc:
            continue

        if loc in cache:
            entry = cache[loc]
            results[loc] = tuple(entry) if entry else None
            continue

        # Respect Nominatim rate limit
        if new_hits > 0:
            time.sleep(1.1)

        print(f"  Geocoding {loc!r} ...", end=" ", flush=True)
        try:
            # Try UK first (most events are in the UK)
            geo = geolocator.geocode(loc, country_codes="gb", timeout=10)
            if not geo:
                geo = geolocator.geocode(loc, timeout=10)

            if geo:
                results[loc] = (geo.latitude, geo.longitude)
                cache[loc]   = [geo.latitude, geo.longitude]
                print(f"({geo.latitude:.4f}, {geo.longitude:.4f})")
            else:
                results[loc] = None
                cache[loc]   = None
                print("NOT FOUND")
        except GeocoderTimedOut:
            results[loc] = None
            cache[loc]   = None
            print("TIMEOUT")

        new_hits += 1

    if cache_path and new_hits > 0:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(cache, f, indent=2)
        print(f"  Geocache updated → {cache_path}")

    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Convert raw engagement data to uk_engagement_map.py CSV format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Column auto-detection looks for these keywords (case-insensitive):
  period     : month, date, period, year
  location   : location, venue, place, city
  engagement : number of people, people, views, attendance, count

Override detection with --col-period / --col-location / --col-engagement if needed.

examples:
  python3 preprocess_engagement.py raw_data.tsv
  python3 preprocess_engagement.py raw_data.xlsx -o data/engagement.csv
  python3 preprocess_engagement.py raw_data.tsv --geocache data/geocache.json
        """,
    )
    p.add_argument("input",
                   help="Input file: TSV, CSV, or Excel (.xlsx/.xls)")
    p.add_argument("-o", "--output", default="data/engagement.csv",
                   help="Output CSV path (default: data/engagement.csv)")
    p.add_argument("--geocache", default="data/geocache.json",
                   help="Geocoding cache file (default: data/geocache.json)")
    p.add_argument("--col-period",
                   help="Exact column name for the time period")
    p.add_argument("--col-location",
                   help="Exact column name for the event location")
    p.add_argument("--col-engagement",
                   help="Exact column name for the engagement/attendance count")
    opts = p.parse_args()

    # ── Load ──────────────────────────────────────────────────────────────────
    print(f"Loading {opts.input} ...")
    df = load_input(opts.input)
    print(f"  {len(df)} rows, columns: {[_clean_col_name(c) for c in df.columns]}")

    # ── Find columns ──────────────────────────────────────────────────────────
    col_period     = opts.col_period     or find_col(df, COL_PERIOD_HINTS)
    col_location   = opts.col_location   or find_col(df, COL_LOCATION_HINTS)
    col_engagement = opts.col_engagement or find_col(df, COL_ENGAGEMENT_HINTS)

    missing = [(label, col) for label, col in [
        ("period",     col_period),
        ("location",   col_location),
        ("engagement", col_engagement),
    ] if col is None]

    if missing:
        labels = ", ".join(l for l, _ in missing)
        print(f"\nERROR: Could not auto-detect column(s) for: {labels}")
        print(f"Available columns:")
        for c in df.columns:
            print(f"  {_clean_col_name(c)!r}")
        print("\nUse --col-period / --col-location / --col-engagement to specify.")
        sys.exit(1)

    print(f"  Period column     : {_clean_col_name(col_period)!r}")
    print(f"  Location column   : {_clean_col_name(col_location)!r}")
    print(f"  Engagement column : {_clean_col_name(col_engagement)!r}")

    # ── Extract and clean ─────────────────────────────────────────────────────
    work = df[[col_period, col_location, col_engagement]].copy()
    work.columns = ["period_raw", "location", "engagement_raw"]

    work["period"]     = work["period_raw"].apply(normalise_period)
    work["location"]   = work["location"].astype(str).str.strip()
    work["engagement"] = (
        pd.to_numeric(
            work["engagement_raw"].astype(str).str.replace(",", "").str.strip(),
            errors="coerce",
        )
        .fillna(0)
        .astype(int)
    )

    # Drop rows without a parseable period or a blank location
    n_before = len(work)
    work = work[work["period"].notna()]
    work = work[work["location"].str.len() > 0]
    work = work[work["location"] != "nan"]
    n_dropped = n_before - len(work)
    if n_dropped:
        print(f"  Dropped {n_dropped} row(s) with missing/unparseable period or location")

    if work.empty:
        print("ERROR: No usable rows after cleaning. Check your column names and period format.")
        sys.exit(1)

    # ── Aggregate ─────────────────────────────────────────────────────────────
    agg = (
        work.groupby(["location", "period"], as_index=False)["engagement"]
        .sum()
    )

    # ── Pivot to wide format ──────────────────────────────────────────────────
    pivot = agg.pivot_table(
        index="location", columns="period",
        values="engagement", aggfunc="sum", fill_value=0,
    ).reset_index()

    # Sort period columns chronologically
    period_cols   = [c for c in pivot.columns if c != "location"]
    period_cols   = sorted(period_cols, key=period_sort_key)
    pivot         = pivot[["location"] + period_cols]

    # ── Geocode ───────────────────────────────────────────────────────────────
    unique_locs = pivot["location"].tolist()
    print(f"\nGeocoding {len(unique_locs)} unique location(s) ...")
    geo = geocode_locations(unique_locs, opts.geocache)

    # ── Build output ──────────────────────────────────────────────────────────
    rows    = []
    skipped = []
    for _, row in pivot.iterrows():
        loc    = row["location"]
        coords = geo.get(loc)
        if not coords:
            skipped.append(loc)
            continue
        lat, lon = coords
        entry = {"name": loc, "lat": round(lat, 5), "lon": round(lon, 5)}
        for period in period_cols:
            entry[period] = int(row[period])
        rows.append(entry)

    if skipped:
        print(f"\nWARNING: {len(skipped)} location(s) could not be geocoded and were excluded:")
        for s in skipped:
            print(f"  - {s!r}")
        print(
            "  Fix: edit the geocache JSON to add coordinates manually, or rename the\n"
            "  location in your spreadsheet to something Nominatim can find."
        )

    if not rows:
        print("ERROR: No geocoded rows to write. Exiting.")
        sys.exit(1)

    out = pd.DataFrame(rows)
    Path(opts.output).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(opts.output, index=False)

    print(f"\nOutput → {opts.output}")
    print(f"  {len(out)} location(s), {len(period_cols)} period(s): {period_cols}")
    print()
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()