"""
Trajectory — Low-friction quick data entry.

Captures subjective/contextual daily signals that wearables can't measure
(mood, energy, stress, medication adherence, water, weight, symptoms, notes)
so the dataset gets richer for correlations. Backed by a NEW SQLite table
`quick_entries`; the existing daily_log table is left untouched.

Wiring:
    import quick_log
    quick_log.QUICK_TYPES                          # registry to render inputs
    quick_log.add_entry(date, kind, value=, text=) # insert a logged signal
    df = quick_log.load_entries(date=, kind=)       # filtered history
    quick_log.delete_entry(entry_id)
    roll = quick_log.daily_rollup()                 # date-indexed numeric means
"""
import os
import sqlite3
from collections import OrderedDict

import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "health.db")

# Registry of loggable signals. The UI reads this to render the right input.
#   label  — friendly title
#   emoji  — small visual cue
#   input  — "scale_1_5" | "bool" | "number" | "text"
#   unit   — display unit ("" if none)
#   prompt — encouraging one-liner nudge ("easy input")
#   step/min/max — numeric input hints (numbers only)
QUICK_TYPES = OrderedDict([
    ("mood", {
        "label": "Mood", "emoji": "🙂", "input": "scale_1_5", "unit": "",
        "prompt": "How's your mood right now? (1 low – 5 great)",
    }),
    ("energy", {
        "label": "Energy", "emoji": "⚡", "input": "scale_1_5", "unit": "",
        "prompt": "How's your energy? (1 drained – 5 energized)",
    }),
    ("stress", {
        "label": "Stress", "emoji": "😣", "input": "scale_1_5", "unit": "",
        "prompt": "How stressed do you feel? (1 calm – 5 frazzled)",
    }),
    ("medication_taken", {
        "label": "Medication taken", "emoji": "💊", "input": "bool", "unit": "",
        "prompt": "Did you take your medication today?",
    }),
    ("water_cups", {
        "label": "Water", "emoji": "💧", "input": "number", "unit": "cups",
        "step": 1.0, "min": 0.0, "max": 30.0,
        "prompt": "How many cups of water have you had?",
    }),
    ("weight_lbs", {
        "label": "Weight", "emoji": "⚖️", "input": "number", "unit": "lbs",
        "step": 0.1, "min": 0.0, "max": 700.0,
        "prompt": "Log your weight (no smart scale needed).",
    }),
    ("symptom", {
        "label": "Symptom", "emoji": "🩺", "input": "text", "unit": "",
        "prompt": "Anything you're feeling? (e.g. headache, thirsty)",
    }),
    ("note", {
        "label": "Note", "emoji": "📝", "input": "text", "unit": "",
        "prompt": "Anything else worth remembering today?",
    }),
])

# Numeric kinds that roll up into daily means / fractions.
_NUMERIC_KINDS = [k for k, v in QUICK_TYPES.items() if v["input"] in ("scale_1_5", "bool", "number")]


def _connect(conn=None):
    """Return (conn, should_close). Reuse a passed conn; otherwise open one."""
    if conn is not None:
        return conn, False
    return sqlite3.connect(DB_PATH), True


def init_table(conn=None):
    """Create the quick_entries table if it doesn't exist. Idempotent."""
    c, should_close = _connect(conn)
    try:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS quick_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                logged_time TEXT,
                kind TEXT NOT NULL,
                value REAL,
                text TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        c.commit()
    finally:
        if should_close:
            c.close()


def add_entry(date, kind, value=None, text=None, logged_time=None):
    """Insert a quick entry. Ensures the table exists first."""
    conn = sqlite3.connect(DB_PATH)
    try:
        init_table(conn)
        num = None if value is None else float(value)
        conn.execute(
            "INSERT INTO quick_entries (date, logged_time, kind, value, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (str(date), logged_time, kind, num, text),
        )
        conn.commit()
    finally:
        conn.close()


def load_entries(date=None, kind=None):
    """Return filtered entries as a DataFrame, newest first. Never errors on a fresh DB."""
    conn = sqlite3.connect(DB_PATH)
    try:
        init_table(conn)
        query = "SELECT * FROM quick_entries"
        clauses, params = [], []
        if date is not None:
            clauses.append("date = ?")
            params.append(str(date))
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC"
        return pd.read_sql(query, conn, params=params)
    finally:
        conn.close()


def delete_entry(entry_id):
    """Delete a single entry by id."""
    conn = sqlite3.connect(DB_PATH)
    try:
        init_table(conn)
        conn.execute("DELETE FROM quick_entries WHERE id = ?", (entry_id,))
        conn.commit()
    finally:
        conn.close()


def daily_rollup():
    """Return a date-indexed DataFrame with one column per numeric kind.

    Scales and plain numbers roll up as the daily mean; medication_taken rolls
    up as an adherence fraction (mean of 1/0). Empty DataFrame if no entries.
    Ready to merge with daily_metrics for correlations.
    """
    df = load_entries()
    if df.empty:
        return pd.DataFrame()
    num = df[df["kind"].isin(_NUMERIC_KINDS) & df["value"].notna()].copy()
    if num.empty:
        return pd.DataFrame()
    roll = num.pivot_table(index="date", columns="kind", values="value", aggfunc="mean")
    roll.columns.name = None
    return roll.sort_index()
