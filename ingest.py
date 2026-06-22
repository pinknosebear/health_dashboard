"""
Trajectory — Data ingestion pipeline.

Aggregates Apple Health CSV exports, Ravi's body composition data, CGM data,
and lab results into daily_metrics and lab_results tables in health.db.

Usage:
    python ingest.py
    python ingest.py --cgm /path/to/cgm.csv
"""
import argparse
import os
import sqlite3
import sys

import pandas as pd

# Optional open-wearables REST source. Guard the import so CSV mode still works
# even if httpx (ow_client's dependency) is not installed.
try:
    import ow_client
    HAS_OW_CLIENT = True
except ImportError:
    HAS_OW_CLIENT = False

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "health.db")
RAVI_APPLE_DIR = "/Users/amrutha/Downloads/test results"
CGM_PATH = "/Users/amrutha/Downloads/test results/libre3_cgm.csv"


def _read_apple_csv(name, apple_dir=None):
    """Read an Apple Health CSV from apple_dir (or project dir if None), or return None."""
    if apple_dir is None:
        apple_dir = HERE
    path = os.path.join(apple_dir, name)
    if not os.path.exists(path):
        print(f"  ! {name} not found in {apple_dir}, skipping")
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


def aggregate_apple(apple_dir=None):
    """Return a DataFrame indexed by date with Apple Health metrics and body composition."""
    if apple_dir is None:
        apple_dir = RAVI_APPLE_DIR
    frames = []

    # Sleep: sum InBed durations, attributed to the wake (endDate) date.
    sleep = _read_apple_csv("SleepAnalysis.csv", apple_dir)
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
        df = _read_apple_csv(name, apple_dir)
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
        df = _read_apple_csv(name, apple_dir)
        if df is not None:
            df["date"] = _apple_dates(df)
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            frames.append(df.groupby("date")["value"].mean().rename(metric))

    # Body composition: last value per day.
    for name, metric in [
        ("BodyMass.csv", "weight_lbs"),
        ("BodyFatPercentage.csv", "body_fat_pct"),
        ("LeanBodyMass.csv", "lean_mass_lbs"),
    ]:
        df = _read_apple_csv(name, apple_dir)
        if df is not None:
            df["date"] = _apple_dates(df)
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            frames.append(df.sort_values("date").groupby("date")["value"].last().rename(metric))

    # Blood pressure: last value per day.
    for name, metric in [
        ("BloodPressureSystolic.csv", "systolic"),
        ("BloodPressureDiastolic.csv", "diastolic"),
    ]:
        df = _read_apple_csv(name, apple_dir)
        if df is not None:
            df["date"] = _apple_dates(df)
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            frames.append(df.sort_values("date").groupby("date")["value"].last().rename(metric))

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1)


def aggregate_cgm(cgm_path):
    """Return a DataFrame indexed by date with CGM metrics.

    Filters to Historic Glucose records (Record Type 0) and computes:
    - glucose_mean, glucose_min, glucose_max, glucose_std
    - time_in_range (% in 70-180)
    - gmi (3.31 + 0.02392 * glucose_mean)

    Only includes dates >= 2023-09-01 (CGM start date).
    """
    if not os.path.exists(cgm_path):
        print(f"  ! CGM file not found at {cgm_path}, skipping")
        return pd.DataFrame()

    cgm = pd.read_csv(cgm_path, skiprows=1, low_memory=False)

    # Parse timestamp: format is "%m-%d-%Y %I:%M %p"
    cgm["timestamp"] = pd.to_datetime(cgm["Device Timestamp"], format="%m-%d-%Y %I:%M %p")

    # Filter to Historic Glucose (Record Type 0)
    cgm = cgm[cgm["Record Type"] == 0].copy()

    # Extract date and glucose value (use Historic Glucose as primary)
    cgm["date"] = cgm["timestamp"].dt.date
    cgm["glucose"] = pd.to_numeric(cgm["Historic Glucose mg/dL"], errors="coerce")

    # Filter to dates >= 2023-09-01
    cgm = cgm[cgm["date"] >= pd.to_datetime("2023-09-01").date()]

    # Group by date
    daily = cgm.groupby("date").agg({
        "glucose": ["mean", "min", "max", "std"]
    }).reset_index()
    daily.columns = ["date", "glucose_mean", "glucose_min", "glucose_max", "glucose_std"]

    # Time in range (70-180 mg/dL)
    cgm["in_range"] = (cgm["glucose"] >= 70) & (cgm["glucose"] <= 180)
    tir = cgm.groupby("date")["in_range"].apply(lambda x: 100.0 * x.sum() / len(x))
    daily["time_in_range"] = daily["date"].map(tir)

    # GMI calculation: 3.31 + 0.02392 * average_glucose
    daily["gmi"] = 3.31 + 0.02392 * daily["glucose_mean"]

    return daily.set_index("date")


def build_database(cgm_path, source="csv"):
    if source == "ow":
        print("Fetching Apple Health data from open-wearables...")
        apple = ow_client.fetch_apple_metrics() if HAS_OW_CLIENT else pd.DataFrame()
        if apple.empty:
            print("  ! open-wearables returned no data, falling back to CSV")
            apple = aggregate_apple(RAVI_APPLE_DIR)
    else:
        print("Aggregating Apple Health data...")
        apple = aggregate_apple(RAVI_APPLE_DIR)
    print(f"  -> {len(apple)} days from Apple Health")

    print("Aggregating CGM data...")
    cgm = aggregate_cgm(cgm_path)
    print(f"  -> {len(cgm)} days from CGM")

    if apple.empty and cgm.empty:
        print("No data found. Aborting.")
        sys.exit(1)

    # Merge apple and cgm on date. Both indexes are date objects, so sort works.
    daily = pd.concat([apple, cgm], axis=1).sort_index()
    daily.index.name = "date"
    daily = daily.reset_index()
    daily["date"] = daily["date"].astype(str)  # Convert to string for SQLite

    conn = sqlite3.connect(DB_PATH)

    # Write daily_metrics
    daily.to_sql("daily_metrics", conn, if_exists="replace", index=False)

    # Create experiments table
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

    # Create daily_log table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            logged_time TEXT,
            entry_type TEXT NOT NULL,
            meal_type TEXT,
            rating INTEGER,
            notes TEXT,
            photo BLOB,
            photo_filename TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Create and seed lab_results table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lab_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            panel TEXT,
            test TEXT,
            value REAL,
            unit TEXT,
            ref_low REAL,
            ref_high REAL,
            flag TEXT
        )
    """)

    # Delete existing rows and insert lab data
    conn.execute("DELETE FROM lab_results")

    LAB_DATA = [
        # A1c panel (9 dates)
        ('2021-10-04', 'A1c', 'Hemoglobin A1c', 7.4, '%', 3.5, 5.6, 'HIGH'),
        ('2022-05-14', 'A1c', 'Hemoglobin A1c', 8.5, '%', 3.5, 5.6, 'HIGH'),
        ('2023-03-31', 'A1c', 'Hemoglobin A1c', 7.2, '%', 3.5, 5.6, 'HIGH'),
        ('2023-08-21', 'A1c', 'Hemoglobin A1c', 7.9, '%', 3.5, 5.6, 'HIGH'),
        ('2024-01-19', 'A1c', 'Hemoglobin A1c', 6.4, '%', 3.5, 5.6, 'HIGH'),
        ('2025-05-27', 'A1c', 'Hemoglobin A1c', 8.2, '%', 3.5, 5.6, 'HIGH'),
        ('2025-10-29', 'A1c', 'Hemoglobin A1c', 8.4, '%', 3.5, 5.6, 'HIGH'),
        ('2026-03-02', 'A1c', 'Hemoglobin A1c', 7.5, '%', 3.5, 5.6, 'HIGH'),
        ('2026-06-06', 'A1c', 'Hemoglobin A1c', 5.6, '%', 3.5, 5.6, 'NORMAL'),
        # Derived average glucose (same dates as A1c)
        ('2021-10-04', 'A1c', 'Average Glucose', 166, 'mg/dL', 0, 0, None),
        ('2022-05-14', 'A1c', 'Average Glucose', 197, 'mg/dL', 0, 0, None),
        ('2023-03-31', 'A1c', 'Average Glucose', 160, 'mg/dL', 0, 0, None),
        ('2023-08-21', 'A1c', 'Average Glucose', 180, 'mg/dL', 0, 0, None),
        ('2024-01-19', 'A1c', 'Average Glucose', 137, 'mg/dL', 0, 0, None),
        ('2025-05-27', 'A1c', 'Average Glucose', 189, 'mg/dL', 0, 0, None),
        ('2025-10-29', 'A1c', 'Average Glucose', 194, 'mg/dL', 0, 0, None),
        ('2026-03-02', 'A1c', 'Average Glucose', 169, 'mg/dL', 0, 0, None),
        ('2026-06-06', 'A1c', 'Average Glucose', 114, 'mg/dL', 0, 0, None),
        # BMP (6 dates): Glucose, Creatinine, eGFR only
        ('2021-10-04', 'BMP', 'Glucose', 173, 'mg/dL', 70, 99, 'HIGH'),
        ('2022-05-14', 'BMP', 'Glucose', 166, 'mg/dL', 70, 99, 'HIGH'),
        ('2023-03-31', 'BMP', 'Glucose', 136, 'mg/dL', 70, 99, 'HIGH'),
        ('2024-12-23', 'BMP', 'Glucose', 175, 'mg/dL', 70, 99, 'HIGH'),
        ('2025-05-27', 'BMP', 'Glucose', 153, 'mg/dL', 70, 99, 'HIGH'),
        ('2026-03-02', 'BMP', 'Glucose', 188, 'mg/dL', 70, 99, 'HIGH'),
        ('2021-10-04', 'BMP', 'Creatinine', 1.30, 'mg/dL', 0.50, 1.30, 'NORMAL'),
        ('2022-05-14', 'BMP', 'Creatinine', 1.13, 'mg/dL', 0.50, 1.30, 'NORMAL'),
        ('2023-03-31', 'BMP', 'Creatinine', 1.13, 'mg/dL', 0.50, 1.30, 'NORMAL'),
        ('2024-12-23', 'BMP', 'Creatinine', 1.37, 'mg/dL', 0.50, 1.30, 'HIGH'),
        ('2025-05-27', 'BMP', 'Creatinine', 1.25, 'mg/dL', 0.50, 1.30, 'NORMAL'),
        ('2026-03-02', 'BMP', 'Creatinine', 1.48, 'mg/dL', 0.50, 1.30, 'HIGH'),
        ('2023-03-31', 'BMP', 'eGFR', 77, 'mL/min', 60, 999, 'NORMAL'),
        ('2024-12-23', 'BMP', 'eGFR', 61, 'mL/min', 60, 999, 'NORMAL'),
        ('2025-05-27', 'BMP', 'eGFR', 68, 'mL/min', 60, 999, 'NORMAL'),
        ('2026-03-02', 'BMP', 'eGFR', 55, 'mL/min', 60, 999, 'LOW'),
        # Lipids (4 dates)
        ('2021-10-04', 'Lipids', 'Triglycerides', 182, 'mg/dL', 0, 150, 'HIGH'),
        ('2023-08-21', 'Lipids', 'Triglycerides', 152, 'mg/dL', 0, 150, 'HIGH'),
        ('2024-12-23', 'Lipids', 'Triglycerides', 293, 'mg/dL', 0, 150, 'HIGH'),
        ('2026-03-02', 'Lipids', 'Triglycerides', 233, 'mg/dL', 0, 150, 'HIGH'),
        # Microalbumin (6 dates)
        ('2021-10-04', 'Microalbumin', 'Microalbumin/Creatinine', 41, 'mg/g', 0, 30, 'HIGH'),
        ('2022-05-14', 'Microalbumin', 'Microalbumin/Creatinine', 27, 'mg/g', 0, 30, 'NORMAL'),
        ('2023-03-31', 'Microalbumin', 'Microalbumin/Creatinine', 40, 'mg/g', 0, 30, 'HIGH'),
        ('2024-01-19', 'Microalbumin', 'Microalbumin/Creatinine', 6, 'mg/g', 0, 30, 'NORMAL'),
        ('2025-05-27', 'Microalbumin', 'Microalbumin/Creatinine', 22, 'mg/g', 0, 30, 'NORMAL'),
        ('2026-03-02', 'Microalbumin', 'Microalbumin/Creatinine', 12, 'mg/g', 0, 30, 'NORMAL'),
    ]

    for row in LAB_DATA:
        conn.execute(
            "INSERT INTO lab_results (date, panel, test, value, unit, ref_low, ref_high, flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            row
        )

    conn.commit()
    conn.close()

    print(f"\nIngested {len(daily)} days of data into {DB_PATH}")
    print(f"Columns: {', '.join(c for c in daily.columns if c != 'date')}")
    print(f"\nDaily metrics sample (first 3 rows):")
    print(daily.head(3).to_string())
    print(f"\nDaily metrics sample (last 3 rows):")
    print(daily.tail(3).to_string())
    print(f"\nLab results sample (first 5 rows):")
    conn = sqlite3.connect(DB_PATH)
    lab_sample = pd.read_sql("SELECT * FROM lab_results LIMIT 5", conn)
    print(lab_sample.to_string(index=False))
    conn.close()
    print(f"\nLab results count: {len(LAB_DATA)} rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cgm", default=CGM_PATH,
                        help="Path to CGM CSV file")
    parser.add_argument("--source", choices=["csv", "ow"], default="csv",
                        help="Apple Health source: local CSVs (csv) or open-wearables API (ow)")
    args = parser.parse_args()
    build_database(args.cgm, source=args.source)
