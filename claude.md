# Trajectory — Project Guide

An AI-powered **N-of-1 health experimentation platform**. A Streamlit dashboard for a single
participant (the author's father, "Ravi" — 56yo, Type 2 diabetes) that unifies CGM, Apple Watch,
and lab data into one SQLite database, surfaces trends/correlations, lets him run personal
experiments, and generates an AI weekly summary.

> This file is the canonical guide for coding agents. Keep it current when you change architecture,
> data flow, or add features.

---

## Environment & how to run

- **Use the project venv**: `./venv/bin/python` and `./venv/bin/streamlit`. The system `python3` is
  externally-managed and lacks `pandas`.
- **Ingest data** (build `health.db`): `./venv/bin/python ingest.py`
  - From open-wearables API instead of CSVs: `./venv/bin/python ingest.py --source ow`
- **Run the app**: `./venv/bin/streamlit run app.py`
- **Headless runtime test** (catches errors across all tabs without a browser):
  ```python
  from streamlit.testing.v1 import AppTest
  at = AppTest.from_file("app.py", default_timeout=60).run()
  assert not at.exception
  ```

---

## Architecture baseline

| Layer | Choice |
|---|---|
| Frontend | Streamlit (`app.py`) |
| Data pipeline | `ingest.py` → `health.db` (SQLite) |
| AI layer | Gemini via `google-generativeai` (note: UI caption says "Claude" but the call is Gemini) |
| Analysis | pandas; `scikit-learn`/`statsmodels` listed for future regression work |

### Files

| File | Role |
|---|---|
| `app.py` | Dashboard. 10 tabs (see below). Runs top-to-bottom on every interaction. |
| `ingest.py` | ETL → `daily_metrics` + `lab_results`. Apple source switchable via `--source {csv,ow}`. |
| `healthdata.py` | Standalone Apple Health `export.xml` → per-type CSV extractor. |
| `ow_client.py` | **(new)** open-wearables REST API client (httpx). Never raises; degrades to empty. |
| `goals.py` | **(new)** long-term goals backend (`goals` table) + progress/trajectory math. |
| `education.py` | **(new)** plain-language metric explanations + glossary. Pure data, no Streamlit. |
| `quick_log.py` | **(new)** low-friction daily check-ins (`quick_entries` table). |
| `.streamlit/secrets.toml` | `GEMINI_API_KEY`; optional `OW_API_URL`/`OW_API_KEY`/`OW_USER_ID`. |

### Database (`health.db`) tables

- `daily_metrics` — one row/date: `glucose_mean/min/max/std`, `time_in_range`, `gmi`, `steps`,
  `sleep_hours`, `hrv`, `resting_hr`, `active_calories`, `exercise_minutes`, `weight_lbs`,
  `body_fat_pct`, `lean_mass_lbs`, `systolic`, `diastolic`.
- `lab_results` — `date, panel, test, value, unit, ref_low, ref_high, flag`. Seeded from the
  hardcoded `LAB_DATA` list in `ingest.py`.
- `experiments` — N-of-1 experiment definitions (hypothesis, intervention, window, success_metric).
- `daily_log` — sleep-quality ratings + food photos (BLOB), with `logged_time` for CGM alignment.
- `goals` **(new)** — long-term targets. Created lazily by `goals.init_table()`.
- `quick_entries` **(new)** — subjective/contextual signals. Created lazily by `quick_log.init_table()`.

### Data sources (paths are hardcoded for the single user)

| Source | Method | Location |
|---|---|---|
| Apple Health | CSV (default) **or** open-wearables API (`--source ow`) | `RAVI_APPLE_DIR` / OW API |
| Libre3 CGM | LibreView CSV | `/Users/amrutha/Downloads/test results/libre3_cgm.csv` |
| Lab results | Manual (`LAB_DATA` in `ingest.py`) | n/a |

### `app.py` tabs

`Overview · Goals · Glucose · Labs · Trends · Correlations · Experiments · Daily Log · Learn · Weekly Summary`

---

## Open-Wearables integration (plan + status)

Reference: https://github.com/the-momentum/open-wearables — a self-hosted FastAPI platform exposing a
unified REST API for 13 wearable providers (Garmin, Polar, Whoop, Oura, Fitbit, Apple HealthKit, etc.),
with OAuth, webhooks, and mobile SDKs.

**Metric mapping (OW `SeriesType` → `daily_metrics` column):** `resting_heart_rate`→`resting_hr`,
`heart_rate_variability_sdnn`→`hrv`, `steps`→`steps`, `energy`→`active_calories`,
`exercise_time`→`exercise_minutes`, `weight`→`weight_lbs`, `body_fat_percentage`→`body_fat_pct`,
`lean_body_mass`→`lean_mass_lbs`, `blood_pressure_*`→`systolic`/`diastolic`, sleep summaries→`sleep_hours`.

**Status — Option B implemented.** `ingest.py --source ow` pulls Apple Health metrics from the OW
summary endpoints via `ow_client.fetch_apple_metrics()` instead of reading CSVs; on any failure it
prints a warning and **falls back to CSV**. CGM and lab ingestion are unchanged. Configure with env or
`.streamlit/secrets.toml` keys `OW_API_URL` / `OW_API_KEY` / `OW_USER_ID`.

**Not covered by OW** (keep custom ingestion): LibreView CGM, Withings scale, clinical labs.

**Future — Option C:** live sync via OW webhooks + mobile SDK (continuous HealthKit push), eliminating
manual exports entirely.

---

## Recent UX feature additions

Centered on **long-term health goals, education, and easy data collection** (richer datasets):

- **Goals tab** (`goals.py`): set targets (e.g. A1c < 7.0%, Time in Range > 70%, Weight < 180 lb),
  see per-goal progress bars, current→target, trend arrows, on-track/off-track via linear
  extrapolation to the target date, and an overall progress score. `GOALABLE` lists goal-able metrics
  + clinical defaults; `compute_progress()` is defensive and never raises.
- **Learn tab + hover help** (`education.py`): every metric card exposes an `ℹ️` tooltip
  (`st.metric(help=education.help_text(col))`). The Learn tab gives full What/Why/Target/Lever
  explanations plus a layperson glossary (CGM, TIR, GMI, A1c, HRV, eGFR, …).
- **Quick check-in** (Daily Log tab → `quick_log.py`): one-tap daily logging of mood, energy, stress,
  medication adherence, water, weight, symptoms, notes — the contextual signals wearables can't capture.
  Stored in `quick_entries`. `quick_log.daily_rollup()` returns a date-indexed numeric frame **ready to
  merge into `daily_metrics` for correlations** (a good next step, not yet wired into the Correlations tab).

---

## Conventions for agents

- Always use `./venv/bin/python` / `./venv/bin/streamlit`.
- New persistence modules own their table and create it lazily (`CREATE TABLE IF NOT EXISTS` in an
  idempotent `init_table()`), so a fresh DB never errors and no migration step is needed.
- Be defensive with health data: return `None`/empty rather than raising on missing values.
- Compute `DB_PATH` relative to the module file: `os.path.join(os.path.dirname(os.path.abspath(__file__)), "health.db")`.
- `app.py` runs entirely on each interaction — keep heavy loads behind `@st.cache_data`.
