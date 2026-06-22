"""
Trajectory — Data ingestion pipeline.

Aggregates Apple Health CSV exports and Withings export into a single
daily_metrics table in health.db, and creates an experiments table.

Usage:
    python ingest.py
    python ingest.py --withings /path/to/withings_export_folder
"""
import argparse
import os
import sqlite3
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "health.db")
DEFAULT_WITHINGS_DIR = "/Users/amrutha/Downloads/data_APO_1782100246"


def _read_apple_csv(name):
    """Read an Apple Health CSV from the project directory, or return None."""
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        print(f"  ! {name} not found, skipping")
        return None
    return pd.read_csv(path)


def _apple_dates(df, col="startDate"):
    """Parse an Apple Health timestamp column to a date (UTC-normalized)."""
    return pd.to_datetime(df[col], utc=True).dt.date


def _prefer_watch(df):
    """Keep only Apple Watch rows when present.

    Several metrics (ActiveEnergyBurned, AppleExerciseTime) are logged by
    multiple sources simultaneously — e.g. the iPhone writes a flat 1440
    exercise-minutes/day and third-party apps occasionally write garbage
    calorie totals. Summing across sources double-counts. The Apple Watch is
    the authoritative wearable, so prefer it when any Watch rows exist.
    """
    is_watch = df["sourceName"].str.contains("Watch", case=False, na=False)
    return df[is_watch] if is_watch.any() else df


def aggregate_apple():
    """Return a dict of {date: {metric: value}} from Apple Health CSVs."""
    frames = []

    # Sleep: sum InBed durations, attributed to the wake (endDate) date.
    sleep = _read_apple_csv("SleepAnalysis.csv")
    if sleep is not None:
        sleep = sleep[sleep["value"] == "HKCategoryValueSleepAnalysisInBed"].copy()
        start = pd.to_datetime(sleep["startDate"], utc=True)
        end = pd.to_datetime(sleep["endDate"], utc=True)
        sleep["hours"] = (end - start).dt.total_seconds() / 3600.0
        sleep["date"] = end.dt.date
        s = sleep.groupby("date")["hours"].sum().rename("sleep_hours")
        frames.append(s)

    # Simple sum-per-day metrics. Calories/exercise are prone to multi-source
    # double-counting, so restrict those to the Apple Watch.
    for name, metric, watch_only in [
        ("StepCount.csv", "steps", False),
        ("ActiveEnergyBurned.csv", "active_calories", True),
        ("AppleExerciseTime.csv", "exercise_minutes", True),
    ]:
        df = _read_apple_csv(name)
        if df is not None:
            if watch_only:
                df = _prefer_watch(df)
            df["date"] = _apple_dates(df)
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            frames.append(df.groupby("date")["value"].sum().rename(metric))

    # Mean-per-day metrics.
    for name, metric in [
        ("RestingHeartRate.csv", "resting_hr"),
        ("HeartRateVariabilitySDNN.csv", "hrv"),
    ]:
        df = _read_apple_csv(name)
        if df is not None:
            df["date"] = _apple_dates(df)
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            frames.append(df.groupby("date")["value"].mean().rename(metric))

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1)


def aggregate_withings(withings_dir):
    """Return a DataFrame indexed by date with Withings body & BP metrics."""
    frames = []

    weight_path = os.path.join(withings_dir, "weight.csv")
    if os.path.exists(weight_path):
        w = pd.read_csv(weight_path)
        w["date"] = pd.to_datetime(w["Date"]).dt.date
        rename = {
            "Weight (lb)": "weight_lbs",
            "Fat mass (lb)": "fat_mass_lbs",
            "Muscle mass (lb)": "muscle_mass_lbs",
            "Bone mass (lb)": "bone_mass_lbs",
            "Hydration (lb)": "hydration_lbs",
        }
        cols = [c for c in rename if c in w.columns]
        # Last reading of the day for each metric.
        daily = w.sort_values("Date").groupby("date")[cols].last().rename(columns=rename)
        frames.append(daily)
    else:
        print(f"  ! weight.csv not found in {withings_dir}, skipping")

    bp_path = os.path.join(withings_dir, "bp.csv")
    if os.path.exists(bp_path):
        bp = pd.read_csv(bp_path)
        bp["date"] = pd.to_datetime(bp["Date"]).dt.date
        rename = {
            "Heart rate": "bp_heart_rate",
            "Systolic": "systolic",
            "Diastolic": "diastolic",
        }
        cols = [c for c in rename if c in bp.columns]
        for c in cols:
            bp[c] = pd.to_numeric(bp[c], errors="coerce")
        daily = bp.sort_values("Date").groupby("date")[cols].last().rename(columns=rename)
        frames.append(daily)
    else:
        print(f"  ! bp.csv not found in {withings_dir}, skipping")

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1)


def build_database(withings_dir):
    print("Aggregating Apple Health data...")
    apple = aggregate_apple()
    print(f"  -> {len(apple)} days from Apple Health")

    print("Aggregating Withings data...")
    withings = aggregate_withings(withings_dir)
    print(f"  -> {len(withings)} days from Withings")

    if apple.empty and withings.empty:
        print("No data found. Aborting.")
        sys.exit(1)

    daily = pd.concat([apple, withings], axis=1).sort_index()
    daily.index.name = "date"
    daily = daily.reset_index()
    daily["date"] = daily["date"].astype(str)

    conn = sqlite3.connect(DB_PATH)
    daily.to_sql("daily_metrics", conn, if_exists="replace", index=False)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            hypothesis TEXT,
            intervention TEXT,
            start_date TEXT,
            end_date TEXT,
            success_metric TEXT,
            notes TEXT,
            status TEXT DEFAULT 'active'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            entry_type TEXT NOT NULL,
            meal_type TEXT,
            rating INTEGER,
            notes TEXT,
            photo BLOB,
            photo_filename TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

    print(f"\nIngested {len(daily)} days of data into {DB_PATH}")
    print(f"Columns: {', '.join(c for c in daily.columns if c != 'date')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--withings", default=DEFAULT_WITHINGS_DIR,
                        help="Path to Withings export folder")
    args = parser.parse_args()
    build_database(args.withings)
