"""
Trajectory — Long-term health goals backend.

Lets the user set long-term targets (e.g. "A1c below 7.0%", "Time in Range
above 70%") and track progress + trajectory toward them. Goals live in a
`goals` table in health.db. Progress is computed against the already-loaded
daily_metrics / lab_results DataFrames the app holds.

Public interface:
    GOALABLE                         — orderable metrics that can have goals
    init_table(conn=None)            — create goals table (idempotent)
    add_goal(...)                    — insert a goal
    load_goals(active_only=True)     — DataFrame of goals
    delete_goal(goal_id)
    set_goal_status(goal_id, status)
    compute_progress(goal_row, metrics_df, labs_df) -> dict
    overall_score(goals_df, metrics_df, labs_df)    -> float | None
"""
import os
import sqlite3
from datetime import date, datetime

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "health.db")

# Recent-value / trend windows (days).
RECENT_WINDOW = 7
TREND_WINDOW = 30

# Metrics that can have a long-term goal. Order is display order.
# Each entry:
#   key       — daily_metrics column name OR lab test name
#   label     — human label
#   source    — "metric" (daily_metrics column) or "lab" (lab_results test)
#   direction — default goal direction: "below" or "above"
#   unit      — display unit
#   default   — clinically reasonable default target value
GOALABLE = [
    {"key": "glucose_mean",     "label": "Average Glucose",   "source": "metric", "direction": "below", "unit": "mg/dL",     "default": 140.0},
    {"key": "time_in_range",    "label": "Time in Range",     "source": "metric", "direction": "above", "unit": "%",         "default": 70.0},
    {"key": "gmi",              "label": "GMI",               "source": "metric", "direction": "below", "unit": "%",         "default": 7.0},
    {"key": "glucose_std",      "label": "Glucose Variability","source": "metric","direction": "below", "unit": "mg/dL",     "default": 30.0},
    {"key": "weight_lbs",       "label": "Weight",            "source": "metric", "direction": "below", "unit": "lbs",       "default": 180.0},
    {"key": "steps",            "label": "Steps",             "source": "metric", "direction": "above", "unit": "steps/day", "default": 8000.0},
    {"key": "sleep_hours",      "label": "Sleep",             "source": "metric", "direction": "above", "unit": "hrs/night", "default": 7.5},
    {"key": "exercise_minutes", "label": "Exercise",          "source": "metric", "direction": "above", "unit": "min/day",   "default": 30.0},
    {"key": "hrv",              "label": "HRV",               "source": "metric", "direction": "above", "unit": "ms",        "default": 50.0},
    {"key": "resting_hr",       "label": "Resting Heart Rate","source": "metric", "direction": "below", "unit": "bpm",       "default": 60.0},
    {"key": "Hemoglobin A1c",   "label": "A1c",               "source": "lab",    "direction": "below", "unit": "%",         "default": 7.0},
    {"key": "Triglycerides",    "label": "Triglycerides",     "source": "lab",    "direction": "below", "unit": "mg/dL",     "default": 150.0},
    {"key": "eGFR",             "label": "eGFR",              "source": "lab",    "direction": "above", "unit": "mL/min",    "default": 60.0},
]

# Quick lookup by key.
GOALABLE_BY_KEY = {g["key"]: g for g in GOALABLE}


def _connect(conn=None):
    """Return (conn, owns) where owns is True if we opened it and must close it."""
    if conn is not None:
        return conn, False
    return sqlite3.connect(DB_PATH), True


def init_table(conn=None):
    """Create the goals table if it doesn't exist. Idempotent."""
    conn, owns = _connect(conn)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric TEXT NOT NULL,
                source TEXT NOT NULL,
                label TEXT,
                direction TEXT,
                target_value REAL,
                unit TEXT,
                start_date TEXT,
                target_date TEXT,
                notes TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()
    finally:
        if owns:
            conn.close()


def add_goal(metric, source, direction, target_value, target_date,
             unit=None, label=None, notes=None, start_date=None):
    """Insert a goal. start_date defaults to today. Returns the new goal id."""
    conn = sqlite3.connect(DB_PATH)
    try:
        init_table(conn)
        if start_date is None:
            start_date = date.today().isoformat()
        # Fall back to GOALABLE metadata for label/unit when not provided.
        meta = GOALABLE_BY_KEY.get(metric, {})
        if label is None:
            label = meta.get("label", metric)
        if unit is None:
            unit = meta.get("unit")
        cur = conn.execute(
            """
            INSERT INTO goals
                (metric, source, label, direction, target_value, unit,
                 start_date, target_date, notes, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (metric, source, label, direction, target_value, unit,
             start_date, target_date, notes),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def load_goals(active_only=True):
    """Return goals as a DataFrame. Calls init_table so it never errors on a fresh DB."""
    conn = sqlite3.connect(DB_PATH)
    try:
        init_table(conn)
        sql = "SELECT * FROM goals"
        if active_only:
            sql += " WHERE status = 'active'"
        sql += " ORDER BY created_at DESC, id DESC"
        return pd.read_sql_query(sql, conn)
    finally:
        conn.close()


def delete_goal(goal_id):
    """Permanently delete a goal."""
    conn = sqlite3.connect(DB_PATH)
    try:
        init_table(conn)
        conn.execute("DELETE FROM goals WHERE id = ?", (int(goal_id),))
        conn.commit()
    finally:
        conn.close()


def set_goal_status(goal_id, status):
    """Update a goal's status (e.g. 'active', 'achieved', 'archived')."""
    conn = sqlite3.connect(DB_PATH)
    try:
        init_table(conn)
        conn.execute(
            "UPDATE goals SET status = ? WHERE id = ?", (status, int(goal_id))
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Progress computation helpers
# ---------------------------------------------------------------------------

def _get(row, key, default=None):
    """Read a key from a dict or pandas Series safely."""
    try:
        if isinstance(row, dict):
            val = row.get(key, default)
        else:
            val = row[key] if key in row else default
    except (KeyError, IndexError, TypeError):
        return default
    if val is None:
        return default
    try:
        if pd.isna(val):
            return default
    except (TypeError, ValueError):
        pass
    return val


def _to_float(val):
    """Best-effort float conversion; None on failure."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if pd.isna(f):
        return None
    return f


def _parse_date(val):
    """Parse a date-ish value to a pandas Timestamp; None on failure."""
    if val is None:
        return None
    try:
        ts = pd.to_datetime(val)
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    return ts


def _metric_series(metrics_df, column):
    """Return a clean (date-sorted) Series indexed by Timestamp for a daily_metrics column.

    Returns an empty Series if the column / data is unavailable.
    """
    empty = pd.Series(dtype=float)
    if metrics_df is None or len(metrics_df) == 0 or column not in metrics_df.columns:
        return empty
    df = metrics_df[["date", column]].copy() if "date" in metrics_df.columns else None
    if df is None:
        return empty
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=[column]).sort_values("date")
    if df.empty:
        return empty
    return pd.Series(df[column].values, index=df["date"].values)


def _lab_series(labs_df, test):
    """Return a clean (date-sorted) Series indexed by Timestamp for a lab test.

    Returns an empty Series if the data is unavailable.
    """
    empty = pd.Series(dtype=float)
    if labs_df is None or len(labs_df) == 0:
        return empty
    needed = {"date", "test", "value"}
    if not needed.issubset(set(labs_df.columns)):
        return empty
    df = labs_df[labs_df["test"] == test][["date", "value"]].copy()
    if df.empty:
        return empty
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"]).sort_values("date")
    if df.empty:
        return empty
    return pd.Series(df["value"].values, index=df["date"].values)


def _value_at_or_after(series, when):
    """First value on/after `when`; if none, the earliest value. None if empty."""
    if series is None or series.empty:
        return None
    if when is not None:
        after = series[series.index >= when]
        if not after.empty:
            return float(after.iloc[0])
    return float(series.iloc[0])


def _value_around(series, when):
    """Value closest in time to `when`. None if empty."""
    if series is None or series.empty:
        return None
    if when is None:
        return float(series.iloc[-1])
    idx = (pd.Series(series.index) - when).abs().idxmin()
    return float(series.iloc[idx])


def compute_progress(goal_row, metrics_df, labs_df):
    """Compute progress/trajectory for a single goal.

    Parameters
    ----------
    goal_row : dict or pandas.Series
        One goal row (must have metric, source, direction, target_value;
        optionally start_date, target_date, unit, label).
    metrics_df : pandas.DataFrame
        daily_metrics rows. Should contain a `date` column plus metric columns.
    labs_df : pandas.DataFrame
        lab_results rows with columns date, test, value.

    Returns
    -------
    dict with keys: current, baseline, target, direction, met, pct_to_goal,
    delta_recent, on_track, summary. Every value may be None on missing data;
    this function never raises.
    """
    result = {
        "current": None,
        "baseline": None,
        "target": None,
        "direction": None,
        "met": None,
        "pct_to_goal": None,
        "delta_recent": None,
        "on_track": None,
        "summary": "",
    }

    metric = _get(goal_row, "metric")
    source = _get(goal_row, "source")
    direction = _get(goal_row, "direction") or "below"
    target = _to_float(_get(goal_row, "target_value"))
    unit = _get(goal_row, "unit") or ""
    label = _get(goal_row, "label") or metric or "Goal"
    start_ts = _parse_date(_get(goal_row, "start_date"))
    target_ts = _parse_date(_get(goal_row, "target_date"))

    result["direction"] = direction
    result["target"] = target

    # Build the relevant time series.
    if source == "lab":
        series = _lab_series(labs_df, metric)
    else:
        series = _metric_series(metrics_df, metric)

    if series is None or series.empty:
        result["summary"] = f"{label}: no data yet"
        return result

    last_ts = series.index[-1]

    # ---- current ----------------------------------------------------------
    if source == "lab":
        current = float(series.iloc[-1])  # most recent lab value
    else:
        recent = series[series.index >= (last_ts - pd.Timedelta(days=RECENT_WINDOW))]
        current = float(recent.mean()) if not recent.empty else float(series.iloc[-1])
    result["current"] = current

    # ---- baseline ---------------------------------------------------------
    baseline = _value_at_or_after(series, start_ts)
    result["baseline"] = baseline

    # ---- met --------------------------------------------------------------
    if target is not None:
        if direction == "above":
            result["met"] = current >= target
        else:
            result["met"] = current <= target

    # ---- pct_to_goal ------------------------------------------------------
    if target is not None and baseline is not None:
        if direction == "above":
            already = baseline >= target
            span = target - baseline
            progressed = current - baseline
        else:
            already = baseline <= target
            span = baseline - target
            progressed = baseline - current
        if already:
            pct = 100.0
        elif span <= 0:
            # Baseline equals/past target but not flagged above — treat as done.
            pct = 100.0
        else:
            pct = (progressed / span) * 100.0
        result["pct_to_goal"] = max(0.0, min(100.0, pct))
    elif target is not None and result["met"]:
        result["pct_to_goal"] = 100.0

    # ---- delta_recent (vs ~TREND_WINDOW days ago) -------------------------
    past_cutoff = last_ts - pd.Timedelta(days=TREND_WINDOW)
    past = series[series.index <= past_cutoff]
    past_val = float(past.iloc[-1]) if not past.empty else None
    if past_val is None and len(series) >= 2:
        # Not enough history for a full window: fall back to earliest point.
        past_val = float(series.iloc[0])
    if past_val is not None:
        result["delta_recent"] = current - past_val

    # ---- on_track (linear extrapolation to target_date) -------------------
    if (target is not None and target_ts is not None and past_val is not None):
        # Time elapsed between the past reference point and the latest point.
        past_idx_ts = series[series.index <= past_cutoff].index[-1] if not past.empty else series.index[0]
        elapsed_days = (last_ts - past_idx_ts).days
        if elapsed_days > 0:
            rate = (current - past_val) / elapsed_days  # units/day
            days_left = (target_ts - last_ts).days
            if days_left > 0:
                projected = current + rate * days_left
                if direction == "above":
                    result["on_track"] = projected >= target
                else:
                    result["on_track"] = projected <= target
            else:
                # Target date already passed: on track only if already met.
                result["on_track"] = bool(result["met"])

    # ---- summary ----------------------------------------------------------
    result["summary"] = _summarize(label, unit, result)
    return result


def _fmt(val, unit):
    """Format a number compactly with its unit."""
    if val is None:
        return "n/a"
    txt = f"{val:.0f}" if abs(val) >= 100 else f"{val:.1f}"
    return f"{txt}{unit}" if unit in ("%",) else (f"{txt} {unit}".strip())


def _summarize(label, unit, r):
    """Build a one-line human summary from a partial result dict."""
    cur = r.get("current")
    tgt = r.get("target")
    if cur is None:
        return f"{label}: no data yet"
    parts = f"{label} {_fmt(cur, unit)}"
    if tgt is not None:
        parts += f" → target {_fmt(tgt, unit)}"
    extras = []
    if r.get("met"):
        extras.append("met")
    elif r.get("pct_to_goal") is not None:
        extras.append(f"{r['pct_to_goal']:.0f}% there")
    delta = r.get("delta_recent")
    if delta is not None and abs(delta) > 1e-9:
        improving = (delta > 0) if r.get("direction") == "above" else (delta < 0)
        extras.append("improving" if improving else "worsening")
    if not r.get("met"):
        if r.get("on_track") is True:
            extras.append("on track")
        elif r.get("on_track") is False:
            extras.append("off track")
    if extras:
        parts += " (" + ", ".join(extras) + ")"
    return parts


def overall_score(goals_df, metrics_df, labs_df):
    """Average pct_to_goal across active goals. None if no goals / no measurable progress."""
    if goals_df is None or len(goals_df) == 0:
        return None
    pcts = []
    for _, goal in goals_df.iterrows():
        prog = compute_progress(goal, metrics_df, labs_df)
        if prog.get("pct_to_goal") is not None:
            pcts.append(prog["pct_to_goal"])
    if not pcts:
        return None
    return sum(pcts) / len(pcts)
