"""
Trajectory — Open Wearables API client.

Optional alternative to local Apple Health CSVs: pulls daily summaries from a
self-hosted open-wearables FastAPI service and normalizes them into the same
shape ingest.py expects (a DataFrame indexed by date).

Config (env first, then .streamlit/secrets.toml):
    OW_API_URL   — base URL, e.g. http://localhost:8000
    OW_API_KEY   — API key, e.g. ow_...
    OW_USER_ID   — user id whose summaries to fetch

Usage:
    import ow_client
    if ow_client.is_configured():
        df = ow_client.fetch_apple_metrics(start_date="2024-01-01")
"""
import os

import pandas as pd

try:
    import httpx
except ImportError:  # client unusable without httpx, but import must not crash
    httpx = None

try:
    import tomllib  # py3.11+
except ImportError:
    tomllib = None

HERE = os.path.dirname(os.path.abspath(__file__))
SECRETS_PATH = os.path.join(HERE, ".streamlit", "secrets.toml")
TIMEOUT = 10.0  # seconds


def _load_secrets():
    """Read .streamlit/secrets.toml into a dict, or {} if missing/unparseable."""
    if tomllib is None or not os.path.exists(SECRETS_PATH):
        return {}
    try:
        with open(SECRETS_PATH, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _config(key):
    """Return config value for key: env var first, then secrets.toml, else None."""
    val = os.environ.get(key)
    if val:
        return val
    return _load_secrets().get(key)


def is_configured() -> bool:
    """True only when URL, key, and user_id are all set."""
    return bool(
        _config("OW_API_URL")
        and _config("OW_API_KEY")
        and _config("OW_USER_ID")
    )


# --- defensive field extraction -------------------------------------------

def _first(d, *keys):
    """Return the first present, non-null value among keys in dict d, else None."""
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _num(v):
    """Coerce v to float, or None if not numeric."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_date(d):
    """Extract a python date from a summary record under several plausible keys."""
    raw = _first(d, "date", "day", "calendar_date", "calendarDate", "summary_date")
    if raw is None:
        return None
    try:
        return pd.to_datetime(raw).date()
    except Exception:
        return None


def _records(payload):
    """Normalize an endpoint payload into a list of per-day dicts.

    Accepts either a bare list, or a dict wrapping the list under common keys.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("summaries", "data", "results", "items"):
            if isinstance(payload.get(k), list):
                return payload[k]
        # A single-day dict response.
        return [payload]
    return []


def _to_lbs(weight):
    """Convert a weight value to lbs, assuming kg if it looks like kg (<150)."""
    w = _num(weight)
    if w is None:
        return None
    return w * 2.20462 if w < 150 else w


def _to_hours(sleep):
    """Convert a sleep value to hours, assuming seconds if value > 24."""
    s = _num(sleep)
    if s is None:
        return None
    return s / 3600.0 if s > 24 else s


# --- HTTP ------------------------------------------------------------------

def _get(client, user_id, summary, start_date, end_date):
    """GET one summary endpoint, returning a list of records ([] on failure)."""
    path = f"/api/v1/users/{user_id}/summaries/{summary}"
    params = {}
    if start_date:
        params["start_date"] = str(start_date)
    if end_date:
        params["end_date"] = str(end_date)
    resp = client.get(path, params=params)
    resp.raise_for_status()
    return _records(resp.json())


def fetch_apple_metrics(start_date=None, end_date=None) -> pd.DataFrame:
    """Fetch daily Apple-equivalent metrics from open-wearables.

    Returns a DataFrame indexed by python date (index name "date") with the same
    columns ingest.py uses: sleep_hours, steps, active_calories,
    exercise_minutes, resting_hr, hrv, weight_lbs, body_fat_pct, lean_mass_lbs.
    Missing metrics are simply absent. Never raises — on any error prints a
    "  ! open-wearables: <reason>, skipping" message and returns an empty frame.
    """
    if httpx is None:
        print("  ! open-wearables: httpx not installed, skipping")
        return pd.DataFrame()
    if not is_configured():
        print("  ! open-wearables: not configured (need OW_API_URL/OW_API_KEY/OW_USER_ID), skipping")
        return pd.DataFrame()

    url = _config("OW_API_URL")
    key = _config("OW_API_KEY")
    user_id = _config("OW_USER_ID")
    headers = {"X-Open-Wearables-API-Key": key}

    # date -> {metric: value}
    rows = {}

    def _set(date, metric, value):
        if date is None or value is None:
            return
        rows.setdefault(date, {})[metric] = value

    try:
        with httpx.Client(base_url=url, headers=headers, timeout=TIMEOUT) as client:
            # Activity: steps, active calories, exercise minutes.
            for rec in _get(client, user_id, "activity", start_date, end_date):
                d = _parse_date(rec)
                _set(d, "steps", _num(_first(rec, "steps", "step_count", "total_steps")))
                _set(d, "active_calories", _num(_first(
                    rec, "active_calories", "active_energy", "active_energy_burned",
                    "energy", "calories")))
                _set(d, "exercise_minutes", _num(_first(
                    rec, "exercise_minutes", "active_minutes", "exercise_time",
                    "exercise")))

            # Sleep: duration.
            for rec in _get(client, user_id, "sleep", start_date, end_date):
                d = _parse_date(rec)
                _set(d, "sleep_hours", _to_hours(_first(
                    rec, "sleep_hours", "sleep_duration", "total_sleep_seconds",
                    "total_sleep", "duration", "asleep_seconds")))

            # Recovery: resting HR, HRV (SDNN).
            for rec in _get(client, user_id, "recovery", start_date, end_date):
                d = _parse_date(rec)
                _set(d, "resting_hr", _num(_first(
                    rec, "resting_heart_rate", "resting_hr", "rhr")))
                _set(d, "hrv", _num(_first(
                    rec, "heart_rate_variability_sdnn", "hrv_sdnn", "hrv", "sdnn")))

            # Body: weight, body fat, lean mass.
            for rec in _get(client, user_id, "body", start_date, end_date):
                d = _parse_date(rec)
                _set(d, "weight_lbs", _to_lbs(_first(
                    rec, "weight", "weight_kg", "weight_lbs", "body_mass")))
                _set(d, "body_fat_pct", _num(_first(
                    rec, "body_fat_percentage", "body_fat_pct", "body_fat",
                    "fat_percentage")))
                _set(d, "lean_mass_lbs", _to_lbs(_first(
                    rec, "lean_body_mass", "lean_mass", "lean_mass_lbs",
                    "lean_body_mass_kg")))
    except Exception as e:
        print(f"  ! open-wearables: {e}, skipping")
        return pd.DataFrame()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame.from_dict(rows, orient="index").sort_index()
    df.index.name = "date"
    return df
