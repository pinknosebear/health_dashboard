"""
Trajectory — N-of-1 Health Experimentation Dashboard.

Run:
    streamlit run app.py
"""
import os
import sqlite3
from datetime import datetime

import google.generativeai as genai
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import education
import goals
import quick_log

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "health.db")

# Human-readable labels for metric columns.
METRIC_LABELS = {
    "steps": "Steps",
    "sleep_hours": "Sleep (hrs)",
    "hrv": "HRV (ms)",
    "resting_hr": "Resting HR (bpm)",
    "active_calories": "Active Calories",
    "exercise_minutes": "Exercise (min)",
    "weight_lbs": "Weight (lb)",
    "systolic": "Systolic (mmHg)",
    "diastolic": "Diastolic (mmHg)",
    "glucose_mean": "Avg Glucose (mg/dL)",
    "glucose_min": "Min Glucose (mg/dL)",
    "glucose_max": "Max Glucose (mg/dL)",
    "glucose_std": "Glucose Variability (mg/dL)",
    "time_in_range": "Time in Range (%)",
    "gmi": "GMI (est. A1c %)",
    "body_fat_pct": "Body Fat (%)",
    "lean_mass_lbs": "Lean Mass (lb)",
}

st.set_page_config(page_title="Trajectory", page_icon="📈", layout="wide")


@st.cache_data
def load_metrics():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM daily_metrics", conn, parse_dates=["date"])
    conn.close()
    return df.sort_values("date").reset_index(drop=True)


@st.cache_data
def load_labs():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM lab_results ORDER BY date DESC", conn, parse_dates=["date"])
    conn.close()
    return df


CGM_PATH = "/Users/amrutha/Downloads/test results/libre3_cgm.csv"


@st.cache_data
def load_cgm_raw():
    if not os.path.exists(CGM_PATH):
        return pd.DataFrame()
    cgm = pd.read_csv(CGM_PATH, skiprows=1, low_memory=False)
    cgm["timestamp"] = pd.to_datetime(cgm["Device Timestamp"], format="%m-%d-%Y %I:%M %p")
    cgm = cgm[cgm["Record Type"] == 0].copy()
    cgm["glucose"] = pd.to_numeric(cgm["Historic Glucose mg/dL"], errors="coerce")
    return cgm[["timestamp", "glucose"]].dropna().sort_values("timestamp")


def load_experiments():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM experiments", conn)
    conn.close()
    return df


def add_experiment(name, hypothesis, intervention, start, end, metric, notes):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO experiments
           (name, hypothesis, intervention, start_date, end_date, success_metric, notes, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'active')""",
        (name, hypothesis, intervention, str(start), str(end), metric, notes),
    )
    conn.commit()
    conn.close()


def load_daily_log(date_str=None):
    conn = sqlite3.connect(DB_PATH)
    q = "SELECT * FROM daily_log"
    if date_str:
        q += f" WHERE date = '{date_str}'"
    q += " ORDER BY created_at DESC"
    df = pd.read_sql(q, conn)
    conn.close()
    return df


def add_daily_log(date, entry_type, meal_type, rating, notes, photo_bytes, photo_filename, logged_time=None):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO daily_log
           (date, logged_time, entry_type, meal_type, rating, notes, photo, photo_filename)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(date), logged_time, entry_type, meal_type, rating, notes, photo_bytes, photo_filename),
    )
    conn.commit()
    conn.close()


def delete_daily_log(log_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM daily_log WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()


def label(col):
    return METRIC_LABELS.get(col, col)


def compute_insight_cards(df, metric_cols, last_date):
    """Return list of (metric, r, sentence) for top 3 glucose correlations."""
    if "glucose_mean" not in df.columns or df["glucose_mean"].notna().sum() < 10:
        return []

    numeric = [c for c in metric_cols if c != "glucose_mean" and df[c].notna().sum() > 10]
    corrs = []
    for m in numeric:
        pair = df[["glucose_mean", m]].dropna()
        if len(pair) > 10:
            r = pair["glucose_mean"].corr(pair[m])
            if pd.notna(r):
                corrs.append((m, r))

    corrs.sort(key=lambda x: abs(x[1]), reverse=True)
    top3 = corrs[:3]

    recent = df[df["date"] > last_date - pd.Timedelta(days=7)]

    cards = []
    for m, r in top3:
        week_val = recent[m].mean()
        week_str = f" ({label(m)} this week: {week_val:.1f})" if pd.notna(week_val) else ""

        if m == "sleep_hours":
            direction = "More sleep → lower glucose." if r < 0 else "Less sleep → lower glucose."
            sentence = f"Sleep predicts glucose (r={r:+.2f}). {direction}{week_str}"
        elif m == "steps":
            more_less = "More" if r < 0 else "Fewer"
            high_low = "lower" if r < 0 else "higher"
            sentence = f"{more_less} steps → {high_low} glucose (r={r:+.2f}).{week_str}"
        elif m == "weight_lbs":
            direction = "negatively" if r < 0 else "positively"
            sentence = f"Weight {direction} tracks glucose (r={r:+.2f}).{week_str}"
        elif m == "exercise_minutes":
            direction = "reduces" if r < 0 else "raises"
            sentence = f"Exercise {direction} glucose (r={r:+.2f}).{week_str}"
        elif m == "hrv":
            direction = "inversely" if r < 0 else "positively"
            sentence = f"HRV {direction} tracks glucose (r={r:+.2f}).{week_str}"
        else:
            sentence = f"{label(m)} correlates with glucose (r={r:+.2f}).{week_str}"

        cards.append((m, r, sentence))

    return cards


def get_available_gemini_models(api_key: str):
    """List available Gemini models for generateContent."""
    try:
        genai.configure(api_key=api_key)
        models = [m.name.replace("models/", "") for m in genai.list_models()
                  if "generateContent" in m.supported_generation_methods]
        return sorted(models)
    except Exception:
        return []


@st.cache_data(ttl=86400)
def generate_weekly_summary(week_stats: dict, lab_trend: str, correlations: str) -> str:
    """Call Gemini API to generate a weekly health summary."""
    api_key = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
    if not api_key:
        return "_No API key configured. Add GEMINI_API_KEY to .streamlit/secrets.toml_"

    prompt = f"""You are a health coach assistant for a 56-year-old male with Type 2 diabetes (Ravi).
Analyze this week's health data and provide a concise, actionable summary.

PATIENT CONTEXT: Type 2 diabetic, on medication, using Libre3 CGM + Apple Watch.

THIS WEEK'S DATA:
{week_stats}

LAB HISTORY:
{lab_trend}

TOP CORRELATIONS (all-time):
{correlations}

Respond in exactly this format with these 4 sections:

## What went well this week
[1-2 sentences on positive patterns — e.g. glucose in range, good sleep, active days]

## What to watch
[1-2 sentences on warning signs — high glucose days, poor sleep, trends to monitor]

## One experiment to run next week
[One specific, time-bound hypothesis to test. Format: "Try X for Y days to see if Z improves."]

## One question for your doctor
[One specific clinical question based on lab trends or current data — e.g. eGFR declining, creatinine elevated]

Keep each section to 2-3 sentences max. Be specific, not generic."""

    genai.configure(api_key=api_key)

    # Get list of available models for generateContent
    available = get_available_gemini_models(api_key)
    if not available:
        return "_Could not list available models. Check API key and network connection._"

    # Try available models (prefer latest)
    for model_name in available:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            if model_name == available[-1]:  # Last model failed
                return f"Error: Could not generate summary with available models: {available}. Error: {str(e)}"
            continue


if not os.path.exists(DB_PATH):
    st.error("health.db not found. Run `python ingest.py` first.")
    st.stop()

df = load_metrics()
metric_cols = [c for c in df.columns if c != "date" and df[c].notna().any()]

st.title("📈 Trajectory")
st.caption("An AI-powered N-of-1 health experimentation platform")

(tab_overview, tab_goals, tab_glucose, tab_labs, tab_trends, tab_corr,
 tab_exp, tab_log, tab_learn, tab_summary) = st.tabs(
    ["Overview", "Goals", "Glucose", "Labs", "Trends", "Correlations",
     "Experiments", "Daily Log", "Learn", "Weekly Summary"]
)

# ---------------------------------------------------------------- Overview
with tab_overview:
    last_date = df["date"].max()

    insight_cards = compute_insight_cards(df, metric_cols, last_date)
    if insight_cards:
        st.markdown("#### Key Insights")
        ins_cols = st.columns(len(insight_cards))
        for i, (m, r, sentence) in enumerate(insight_cards):
            ins_cols[i].info(sentence)
        st.divider()

    st.subheader("Last 7 days")
    recent = df[df["date"] > last_date - pd.Timedelta(days=7)]
    prior = df[(df["date"] <= last_date - pd.Timedelta(days=7)) &
               (df["date"] > last_date - pd.Timedelta(days=14))]

    card_metrics = [m for m in [
        "glucose_mean", "time_in_range", "gmi", "steps", "sleep_hours", "hrv", "resting_hr",
        "active_calories", "exercise_minutes", "weight_lbs",
    ] if m in metric_cols]

    cols = st.columns(3)
    for i, m in enumerate(card_metrics):
        cur = recent[m].mean()
        prev = prior[m].mean()
        if pd.isna(cur):
            continue
        delta = None
        if not pd.isna(prev) and prev != 0:
            delta = f"{(cur - prev) / prev * 100:+.1f}%"
        cols[i % 3].metric(label(m), f"{cur:,.1f}", delta,
                           help=education.help_text(m) or None)

    # Show latest A1c from labs
    labs_df = load_labs()
    if not labs_df.empty:
        a1c_data = labs_df[labs_df["test"] == "Hemoglobin A1c"]
        if not a1c_data.empty:
            latest_a1c = a1c_data.iloc[0]
            st.divider()
            col1, col2, col3 = st.columns(3)
            col1.metric("Latest A1c", f"{latest_a1c['value']:.1f}%",
                       f"({latest_a1c['date'].strftime('%Y-%m-%d')})",
                       help=education.help_text("Hemoglobin A1c"))

    st.divider()
    st.caption(f"Data spans {df['date'].min():%Y-%m-%d} to {df['date'].max():%Y-%m-%d} "
               f"({len(df)} days)")

# ---------------------------------------------------------------- Goals
with tab_goals:
    st.subheader("🎯 Long-term Goals")
    st.caption("Set the targets that matter to you and watch your trajectory toward them.")

    labs_for_goals = load_labs()
    goals_df = goals.load_goals()

    score = goals.overall_score(goals_df, df, labs_for_goals)
    if score is not None:
        st.progress(min(1.0, score / 100.0),
                    text=f"Overall progress across goals: {score:.0f}%")
        st.divider()

    if goals_df.empty:
        st.info("No goals yet. Add one below to start tracking your trajectory.")
    else:
        for _, g in goals_df.iterrows():
            prog = goals.compute_progress(g, df, labs_for_goals)
            with st.container(border=True):
                c1, c2 = st.columns([0.88, 0.12])
                with c1:
                    title = g.get("label") or g.get("metric")
                    badge = ""
                    if prog.get("met"):
                        badge = " &nbsp;✅ **met**"
                    elif prog.get("on_track") is True:
                        badge = " &nbsp;🟢 on track"
                    elif prog.get("on_track") is False:
                        badge = " &nbsp;🟠 off track"
                    st.markdown(f"**{title}**{badge}")
                    pct = prog.get("pct_to_goal")
                    if pct is not None:
                        st.progress(pct / 100.0)
                    sub = []
                    if prog.get("current") is not None:
                        sub.append(f"Now: **{prog['current']:.1f}**")
                    if prog.get("target") is not None:
                        sub.append(f"Target: {prog['target']:.1f}")
                    if g.get("target_date"):
                        sub.append(f"By: {g['target_date']}")
                    delta = prog.get("delta_recent")
                    if delta is not None and abs(delta) > 1e-9:
                        improving = (delta > 0) if prog["direction"] == "above" else (delta < 0)
                        sub.append("📈 improving" if improving else "📉 worsening")
                    st.caption("  ·  ".join(sub))
                with c2:
                    if st.button("🗑", key=f"del_goal_{g['id']}", help="Delete goal"):
                        goals.delete_goal(g["id"])
                        st.rerun()

    st.divider()
    with st.expander("➕ New goal", expanded=goals_df.empty):
        opts = goals.GOALABLE
        idx = st.selectbox(
            "Metric", range(len(opts)),
            format_func=lambda i: f"{opts[i]['label']} ({opts[i]['unit']})",
            key="goal_metric_idx",
        )
        chosen = opts[idx]
        help_md = education.help_text(chosen["key"])
        if help_md:
            st.caption(help_md.split("\n\n")[0])  # show the "What:" line as a hint
        c1, c2 = st.columns(2)
        direction = c1.radio(
            "Direction", ["below", "above"],
            index=0 if chosen["direction"] == "below" else 1,
            horizontal=True, key=f"goal_dir_{chosen['key']}",
        )
        target_value = c2.number_input(
            "Target value", value=float(chosen["default"]),
            key=f"goal_target_{chosen['key']}",
        )
        c3, c4 = st.columns(2)
        target_date = c3.date_input("Target date", value=datetime.today(),
                                    key="goal_target_date")
        notes = c4.text_input("Notes", placeholder="Optional", key="goal_notes")
        if st.button("Create goal", type="primary"):
            goals.add_goal(
                chosen["key"], chosen["source"], direction, float(target_value),
                str(target_date), unit=chosen["unit"], label=chosen["label"],
                notes=notes or None,
            )
            st.success(f"Goal added: {chosen['label']}")
            st.rerun()

# ---------------------------------------------------------------- Glucose
with tab_glucose:
    st.subheader("Glucose Metrics")

    # KPI cards
    col1, col2, col3 = st.columns(3)

    try:
        if "glucose_mean" in metric_cols:
            glucose_data = df[df["glucose_mean"].notna()]
            if not glucose_data.empty:
                latest_glucose = glucose_data.iloc[-1]
                col1.metric("Latest Avg Glucose", f"{latest_glucose['glucose_mean']:.1f} mg/dL",
                           f"({pd.Timestamp(latest_glucose['date']).strftime('%Y-%m-%d')})",
                           help=education.help_text("glucose_mean"))
    except Exception as e:
        col1.error(f"Error loading glucose: {str(e)[:50]}")

    try:
        if "time_in_range" in metric_cols:
            tir_data = df[df["time_in_range"].notna()]
            if not tir_data.empty:
                latest_tir = tir_data.iloc[-1]
                col2.metric("Latest Time in Range", f"{latest_tir['time_in_range']:.1f}%",
                           f"({pd.Timestamp(latest_tir['date']).strftime('%Y-%m-%d')})",
                           help=education.help_text("time_in_range"))
    except Exception as e:
        col2.error(f"Error loading TIR: {str(e)[:50]}")

    labs_df = load_labs()
    if not labs_df.empty:
        a1c_data = labs_df[labs_df["test"] == "Hemoglobin A1c"]
        if not a1c_data.empty:
            latest_a1c = a1c_data.iloc[0]
            col3.metric("Latest A1c", f"{latest_a1c['value']:.1f}%",
                       f"({latest_a1c['date'].strftime('%Y-%m-%d')})",
                       help=education.help_text("Hemoglobin A1c"))

    st.divider()

    # Date range selector for both glucose charts — always defined if df is non-empty
    if not df.empty:
        min_d, max_d = df["date"].min().date(), df["date"].max().date()
        default_start = max(min_d, (df["date"].max() - pd.Timedelta(days=180)).date())
        date_range = st.slider(
            "Date range", min_value=min_d, max_value=max_d,
            value=(default_start, max_d), format="YYYY-MM-DD", key="glucose_date_range"
        )
        mask = (df["date"].dt.date >= date_range[0]) & (df["date"].dt.date <= date_range[1])
    else:
        mask = pd.Series(dtype=bool)

    # Glucose mean over time with 70-180 shaded band
    if "glucose_mean" in metric_cols:
        st.markdown("#### Glucose Mean (mg/dL)")
        try:
            glucose_sub = df[mask][["date", "glucose_mean"]].dropna()
        except Exception as e:
            st.error(f"Error filtering glucose data: {e}")
            glucose_sub = pd.DataFrame()

        if not glucose_sub.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=glucose_sub["date"], y=glucose_sub["glucose_mean"],
                                    mode="lines+markers", name="Glucose Mean", opacity=0.6))
            fig.add_hrect(y0=70, y1=180, fillcolor="green", opacity=0.1, line_width=0,
                         annotation_text="Target Range", annotation_position="right")
            fig.update_layout(title="Glucose Mean Over Time", height=400,
                            yaxis_title="Glucose (mg/dL)", xaxis_title="Date")
            st.plotly_chart(fig, use_container_width=True)

    # Time in range over time
    if "time_in_range" in metric_cols:
        st.markdown("#### Time in Range (%)")
        tir_sub = df[mask][["date", "time_in_range"]].dropna()
        if not tir_sub.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=tir_sub["date"], y=tir_sub["time_in_range"],
                                    mode="lines+markers", name="Time in Range", opacity=0.6,
                                    line=dict(color="green")))
            fig.add_hline(y=70, line_dash="dash", line_color="gray",
                         annotation_text="Target: 70%", annotation_position="right")
            fig.update_layout(title="Time in Range Over Time", height=400,
                            yaxis_title="Time in Range (%)", xaxis_title="Date")
            st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.markdown("#### Post-Meal Glucose Response")

    food_logs_all = load_daily_log()
    if not food_logs_all.empty and "logged_time" in food_logs_all.columns:
        food_logs_timed = food_logs_all[
            (food_logs_all["entry_type"] == "food") &
            (food_logs_all["logged_time"].notna()) &
            (food_logs_all["logged_time"] != "")
        ].copy()
    else:
        food_logs_timed = pd.DataFrame()

    cgm_raw = load_cgm_raw()

    if not food_logs_timed.empty and not cgm_raw.empty:
        meal_colors = {
            "Breakfast": "blue",
            "Lunch": "green",
            "Dinner": "orange",
            "Snack": "purple",
        }
        fig_meal = go.Figure()
        traces_added = 0
        seen_meal_types = set()

        for _, row in food_logs_timed.iterrows():
            try:
                meal_dt = pd.to_datetime(str(row["date"]) + " " + str(row["logged_time"]))
            except Exception:
                continue
            window_start = meal_dt - pd.Timedelta(minutes=30)
            window_end = meal_dt + pd.Timedelta(minutes=120)
            segment = cgm_raw[
                (cgm_raw["timestamp"] >= window_start) &
                (cgm_raw["timestamp"] <= window_end)
            ].copy()
            if segment.empty:
                continue
            segment["minutes"] = (segment["timestamp"] - meal_dt).dt.total_seconds() / 60
            meal_type = str(row.get("meal_type", "Meal")) if pd.notna(row.get("meal_type")) else "Meal"
            color = meal_colors.get(meal_type, "gray")
            show_legend = meal_type not in seen_meal_types
            seen_meal_types.add(meal_type)
            fig_meal.add_trace(go.Scatter(
                x=segment["minutes"],
                y=segment["glucose"],
                mode="lines",
                name=meal_type,
                line=dict(color=color),
                opacity=0.6,
                legendgroup=meal_type,
                showlegend=show_legend,
            ))
            traces_added += 1

        if traces_added > 0:
            fig_meal.add_vline(x=0, line_dash="dash", line_color="gray",
                               annotation_text="Meal time", annotation_position="top right")
            fig_meal.add_hrect(y0=70, y1=180, fillcolor="green", opacity=0.08, line_width=0,
                               annotation_text="Target Range", annotation_position="right")
            fig_meal.update_layout(
                title="CGM Response by Meal (-30 to +120 min)",
                height=420,
                xaxis_title="Minutes from meal",
                yaxis_title="Glucose (mg/dL)",
            )
            st.plotly_chart(fig_meal, use_container_width=True)
        else:
            st.info("No CGM data found near logged meal times.")
    else:
        st.info("Log meals with times in the Daily Log tab to see glucose response curves.")

# ---------------------------------------------------------------- Labs
with tab_labs:
    st.subheader("Laboratory Results")

    labs_df = load_labs()
    if labs_df.empty:
        st.info("No laboratory results available.")
    else:
        # Get unique panels and tests
        panels = sorted(labs_df["panel"].unique())
        selected_panel = st.selectbox("Panel", panels)

        panel_data = labs_df[labs_df["panel"] == selected_panel]
        tests = sorted(panel_data["test"].unique())
        selected_test = st.selectbox("Test", tests)

        test_data = labs_df[labs_df["test"] == selected_test].sort_values("date")

        if not test_data.empty:
            # Get reference range if available
            ref_low = test_data["ref_low"].iloc[0] if "ref_low" in test_data.columns else None
            ref_high = test_data["ref_high"].iloc[0] if "ref_high" in test_data.columns else None

            # Color code points based on range
            colors = []
            for _, row in test_data.iterrows():
                value = row["value"]
                if ref_low is not None and ref_high is not None:
                    if pd.notna(ref_low) and pd.notna(ref_high):
                        if ref_low <= value <= ref_high:
                            colors.append("green")
                        else:
                            colors.append("red")
                    else:
                        colors.append("blue")
                else:
                    colors.append("blue")

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=test_data["date"], y=test_data["value"],
                                    mode="lines+markers", name=selected_test,
                                    marker=dict(color=colors, size=8)))

            # Add reference range as shaded band
            if ref_low is not None and ref_high is not None:
                if pd.notna(ref_low) and pd.notna(ref_high):
                    fig.add_hrect(y0=ref_low, y1=ref_high, fillcolor="green", opacity=0.1,
                                 line_width=0, annotation_text="Normal Range",
                                 annotation_position="right")

            fig.update_layout(title=f"{selected_test} Over Time", height=400,
                            yaxis_title="Value", xaxis_title="Date")
            st.plotly_chart(fig, use_container_width=True)

            # Show recent results table
            st.markdown("#### Recent Results")
            recent_results = test_data[["date", "value", "ref_low", "ref_high"]].tail(5).sort_values("date", ascending=False)
            st.dataframe(recent_results, use_container_width=True)

# ---------------------------------------------------------------- Trends
with tab_trends:
    st.subheader("Metric trends")
    min_d, max_d = df["date"].min().date(), df["date"].max().date()
    if min_d == max_d:
        st.info("Only one day of data available.")
        date_range = (min_d, max_d)
    else:
        default_start = max(min_d, (df["date"].max() - pd.Timedelta(days=90)).date())
        date_range = st.slider(
            "Date range", min_value=min_d, max_value=max_d,
            value=(default_start, max_d), format="YYYY-MM-DD",
        )
    selected = st.multiselect(
        "Metrics", metric_cols,
        default=[m for m in ["glucose_mean", "steps", "sleep_hours"] if m in metric_cols],
        format_func=label,
    )

    mask = (df["date"].dt.date >= date_range[0]) & (df["date"].dt.date <= date_range[1])
    window = df[mask]

    for m in selected:
        sub = window[["date", m]].dropna()
        if sub.empty:
            continue
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=sub["date"], y=sub[m], mode="markers+lines",
                                 name=label(m), opacity=0.4))
        fig.add_trace(go.Scatter(x=sub["date"], y=sub[m].rolling(7, min_periods=1).mean(),
                                 mode="lines", name="7-day avg",
                                 line=dict(width=3)))
        fig.update_layout(title=label(m), height=320, margin=dict(t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------- Correlations
with tab_corr:
    if not metric_cols:
        st.info("No metric data available for correlations.")
    else:
        st.subheader("Correlation matrix")
        corr_df = df[metric_cols].corr()
        fig = px.imshow(corr_df, text_auto=".2f", aspect="auto",
                        color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
                        labels=dict(color="Pearson r"))
        fig.update_xaxes(tickvals=list(range(len(metric_cols))),
                         ticktext=[label(c) for c in metric_cols])
        fig.update_yaxes(tickvals=list(range(len(metric_cols))),
                         ticktext=[label(c) for c in metric_cols])
        st.plotly_chart(fig, width="stretch")

        st.divider()
        st.subheader("Explore a relationship (with lag)")
        c1, c2, c3 = st.columns(3)
        x_metric = c1.selectbox("X metric", metric_cols, format_func=label)
        y_metric = c2.selectbox("Y metric", metric_cols,
                                index=min(1, len(metric_cols) - 1), format_func=label)
        lag = c3.slider("Lag (days): X today → Y in N days", 0, 3, 0)

        pair = df[["date", x_metric, y_metric]].copy()
        pair[y_metric] = pair[y_metric].shift(-lag)
        pair = pair.dropna()
        if len(pair) > 2:
            r = pair[x_metric].corr(pair[y_metric])
            st.metric(f"Pearson r (lag={lag})", f"{r:+.3f}")
            fig = px.scatter(pair, x=x_metric, y=y_metric, trendline="ols",
                             labels={x_metric: label(x_metric), y_metric: label(y_metric)})
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("Not enough overlapping data points for this pair.")

# ---------------------------------------------------------------- Experiments
with tab_exp:
    st.subheader("Experiments")
    exp_df = load_experiments()
    if exp_df.empty:
        st.info("No experiments yet. Create one below.")
    else:
        st.dataframe(exp_df.drop(columns=["id"]), width="stretch")

    with st.expander("➕ New experiment", expanded=exp_df.empty):
        with st.form("new_experiment", clear_on_submit=True):
            name = st.text_input("Name", placeholder="Post-dinner walk")
            hypothesis = st.text_area(
                "Hypothesis", placeholder="A 15-min walk after dinner reduces resting HR")
            intervention = st.text_area("Intervention", placeholder="Walk 15 min after dinner")
            c1, c2 = st.columns(2)
            start = c1.date_input("Start date", value=datetime.today())
            end = c2.date_input("End date", value=datetime.today())
            success_metric = st.selectbox(
                "Success metric", metric_cols or ["(no metrics)"], format_func=label)
            notes = st.text_area("Notes", placeholder="Optional")
            submitted = st.form_submit_button("Create experiment")
            if submitted and name:
                add_experiment(name, hypothesis, intervention, start, end,
                               success_metric, notes)
                st.success(f"Created '{name}'")
                st.rerun()

    # Plot success metric over the experiment window.
    if not exp_df.empty:
        st.divider()
        choice = st.selectbox("Visualize experiment", exp_df["name"].tolist())
        row = exp_df[exp_df["name"] == choice].iloc[0]
        metric = row["success_metric"]
        if metric in df.columns:
            sub = df[["date", metric]].dropna()
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=sub["date"], y=sub[metric],
                                     mode="lines+markers", name=label(metric)))
            try:
                sd = pd.to_datetime(row["start_date"])
                ed = pd.to_datetime(row["end_date"])
                fig.add_vrect(x0=sd, x1=ed, fillcolor="green", opacity=0.15,
                              line_width=0, annotation_text="intervention")
            except Exception:
                pass
            fig.update_layout(title=f"{choice}: {label(metric)}", height=380)
            st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------- Daily Log
with tab_log:
    st.subheader("Daily Log")
    st.caption("Log sleep quality and food photos to track daily patterns")

    view_mode = st.radio("Mode", ["Log entry", "View log"], horizontal=True, label_visibility="collapsed")

    if view_mode == "Log entry":
        entry_type = st.radio("What are you logging?", ["Sleep", "Food", "Quick check-in"], horizontal=True, label_visibility="collapsed")

        if entry_type == "Sleep":
            st.markdown("#### 😴 Log Sleep")
            with st.form("sleep_log_form"):
                log_date = st.date_input("Date", value=datetime.today())
                quality = st.slider("Sleep quality", 1, 5, 3,
                                    help="1=Poor, 5=Excellent")
                photo = st.file_uploader("Upload sleep screenshot (optional)", type=["png", "jpg", "jpeg"])
                notes = st.text_area("Notes", placeholder="e.g., fell asleep at 11pm, woke at 7am")
                if st.form_submit_button("Log sleep"):
                    photo_bytes = photo.read() if photo else None
                    photo_name = photo.name if photo else None
                    add_daily_log(log_date, "sleep", None, quality, notes,
                                  photo_bytes, photo_name)
                    st.success("Sleep logged!")
                    st.rerun()

        elif entry_type == "Food":
            st.markdown("#### 🍽️ Log Food")
            with st.form("food_log_form"):
                log_date = st.date_input("Date", value=datetime.today())
                meal = st.selectbox("Meal", ["Breakfast", "Lunch", "Dinner", "Snack"])
                photo = st.file_uploader("Upload food photo", type=["png", "jpg", "jpeg"], key="food_photo")
                notes = st.text_area("Notes", placeholder="e.g., ingredients, portion size, restaurant")
                if st.form_submit_button("Log food"):
                    if photo:
                        photo_bytes = photo.read()
                        photo_name = photo.name
                        add_daily_log(log_date, "food", meal, None, notes,
                                      photo_bytes, photo_name)
                        st.success(f"{meal} logged!")
                        st.rerun()
                    else:
                        st.error("Please upload a food photo.")

        else:  # Quick check-in
            st.markdown("#### ⚡ Quick Check-in")
            st.caption("Tiny daily inputs wearables can't capture — they make your "
                       "dataset richer for spotting patterns. Log whatever's quick.")
            ql_date = st.date_input("Date", value=datetime.today(), key="ql_date")
            with st.form("quick_log_form", clear_on_submit=True):
                pending = {}
                for kind, spec in quick_log.QUICK_TYPES.items():
                    lbl = f"{spec['emoji']} {spec['prompt']}"
                    kind_in = spec["input"]
                    if kind_in == "scale_1_5":
                        pending[kind] = ("scale", st.slider(lbl, 1, 5, 3, key=f"ql_{kind}"))
                    elif kind_in == "bool":
                        pending[kind] = ("bool", st.checkbox(lbl, key=f"ql_{kind}"))
                    elif kind_in == "number":
                        pending[kind] = ("number", st.number_input(
                            lbl, min_value=spec.get("min", 0.0),
                            max_value=spec.get("max"), step=spec.get("step", 1.0),
                            value=0.0, key=f"ql_{kind}"))
                    else:  # text
                        pending[kind] = ("text", st.text_input(lbl, key=f"ql_{kind}"))
                if st.form_submit_button("Save check-in"):
                    saved = 0
                    for kind, (typ, val) in pending.items():
                        if typ == "text":
                            if val and val.strip():
                                quick_log.add_entry(ql_date, kind, text=val.strip())
                                saved += 1
                        elif typ == "bool":
                            quick_log.add_entry(ql_date, kind, value=1 if val else 0)
                            saved += 1
                        elif typ == "number":
                            if val and val > 0:
                                quick_log.add_entry(ql_date, kind, value=val)
                                saved += 1
                        else:  # scale
                            quick_log.add_entry(ql_date, kind, value=val)
                            saved += 1
                    st.success(f"Saved {saved} check-in entries for {ql_date}.")
                    st.rerun()

    else:  # View log
        st.markdown("#### 📋 View Log")
        view_date = st.date_input("Filter by date", value=datetime.today(), key="view_date")
        logs = load_daily_log(str(view_date))
        quick_today = quick_log.load_entries(str(view_date))

        if logs.empty and quick_today.empty:
            st.info("No entries for this date.")
        else:
            sleep_logs = logs[logs["entry_type"] == "sleep"]
            food_logs = logs[logs["entry_type"] == "food"]

            if not sleep_logs.empty:
                st.markdown("**Sleep Entries**")
                for _, row in sleep_logs.iterrows():
                    c1, c2 = st.columns([0.8, 0.2])
                    with c1:
                        stars = "⭐" * int(row["rating"]) if pd.notna(row["rating"]) else "—"
                        st.write(f"{stars} {row['notes']}")
                        if pd.notna(row["photo_filename"]):
                            st.image(row["photo"], width=150)
                    with c2:
                        if st.button("Delete", key=f"del_sleep_{row['id']}"):
                            delete_daily_log(row["id"])
                            st.rerun()
                    st.divider()

            if not food_logs.empty:
                st.markdown("**Food Entries**")
                cols = st.columns(2)
                for i, (_, row) in enumerate(food_logs.iterrows()):
                    with cols[i % 2]:
                        st.write(f"**{row['meal_type']}**")
                        if pd.notna(row["photo"]):
                            st.image(row["photo"], width=200, caption=row.get("notes", ""))
                        else:
                            st.write(row.get("notes", "—"))
                        if st.button("Delete", key=f"del_food_{row['id']}"):
                            delete_daily_log(row["id"])
                            st.rerun()

            if not quick_today.empty:
                st.markdown("**Quick Check-ins**")
                for _, row in quick_today.iterrows():
                    spec = quick_log.QUICK_TYPES.get(row["kind"], {})
                    emoji = spec.get("emoji", "•")
                    name = spec.get("label", row["kind"])
                    if pd.notna(row["value"]):
                        disp = f"{emoji} **{name}:** {row['value']:g} {spec.get('unit', '')}".strip()
                    else:
                        disp = f"{emoji} **{name}:** {row['text']}"
                    c1, c2 = st.columns([0.85, 0.15])
                    c1.markdown(disp)
                    if c2.button("Delete", key=f"del_quick_{row['id']}"):
                        quick_log.delete_entry(row["id"])
                        st.rerun()

# ---------------------------------------------------------------- Learn
with tab_learn:
    st.subheader("📚 Learn")
    st.caption("Plain-language explanations of every number on your dashboard.")

    metric_keys = list(education.METRIC_INFO.keys())
    pick = st.selectbox("Explain a metric", metric_keys,
                        format_func=lambda k: education.METRIC_INFO[k]["name"])
    info = education.explain(pick)
    if info:
        st.markdown(f"### {info['name']}")
        st.markdown(education.help_text(pick))

    st.divider()
    st.markdown("#### Glossary")
    for term, definition in education.GLOSSARY:
        st.markdown(f"**{term}** — {definition}")

# ---------------------------------------------------------------- Weekly Summary
with tab_summary:
    st.subheader("AI Weekly Summary")
    st.caption("Powered by Claude — synthesizes your last 7 days into actionable insights")

    try:
        last_date = df["date"].max()
        week = df[df["date"] > last_date - pd.Timedelta(days=7)]
        prev_week = df[(df["date"] <= last_date - pd.Timedelta(days=7)) &
                       (df["date"] > last_date - pd.Timedelta(days=14))]

        def fmt(series, decimals=1):
            v = series.mean()
            return f"{v:.{decimals}f}" if pd.notna(v) else "N/A"

        def fmt_delta(cur_series, prev_series, decimals=1):
            c, p = cur_series.mean(), prev_series.mean()
            if pd.isna(c) or pd.isna(p) or p == 0:
                return ""
            return f" (vs {p:.{decimals}f} last week)"

        week_stats = f"""Date range: {(last_date - pd.Timedelta(days=7)).strftime('%Y-%m-%d')} to {last_date.strftime('%Y-%m-%d')}
- Average glucose: {fmt(week['glucose_mean'])} mg/dL{fmt_delta(week['glucose_mean'], prev_week['glucose_mean'])}
- Time in range: {fmt(week['time_in_range'])}%{fmt_delta(week['time_in_range'], prev_week['time_in_range'])}
- GMI (est. A1c): {fmt(week['gmi'], 2)}%
- Sleep: {fmt(week['sleep_hours'])} hrs/night
- Steps: {fmt(week['steps'], 0)}/day
- Exercise: {fmt(week['exercise_minutes'], 0)} min/day
- Weight: {fmt(week['weight_lbs'])} lbs"""

        labs_df_s = load_labs()
        a1c_rows = labs_df_s[labs_df_s["test"] == "Hemoglobin A1c"].sort_values("date")
        if not a1c_rows.empty:
            a1c_trend = " → ".join(
                f"{row['value']:.1f}% ({pd.Timestamp(row['date']).strftime('%b %Y')})"
                for _, row in a1c_rows.iterrows()
            )
            lab_trend = f"A1c: {a1c_trend}"
            egfr_rows = labs_df_s[labs_df_s["test"] == "eGFR"].sort_values("date")
            if not egfr_rows.empty:
                latest_egfr = egfr_rows.iloc[-1]
                lab_trend += f"\nLatest eGFR: {latest_egfr['value']:.0f} mL/min ({pd.Timestamp(latest_egfr['date']).strftime('%b %Y')})"
            creat_rows = labs_df_s[labs_df_s["test"] == "Creatinine"].sort_values("date")
            if not creat_rows.empty:
                latest_creat = creat_rows.iloc[-1]
                lab_trend += f"\nLatest Creatinine: {latest_creat['value']:.2f} mg/dL"
        else:
            lab_trend = "No lab data available"

        corr_df = df[metric_cols].corr()
        if "glucose_mean" in corr_df.columns:
            glucose_corr = corr_df["glucose_mean"].drop("glucose_mean").sort_values(key=abs, ascending=False).head(3)
            correlations = "\n".join(
                f"- {label(m)} → glucose_mean: r = {r:+.2f}"
                for m, r in glucose_corr.items()
            )
        else:
            correlations = "No correlation data available"

        col_btn, col_note = st.columns([1, 3])
        if col_btn.button("Generate Summary", type="primary"):
            st.cache_data.clear()

        with st.spinner("Asking Claude to analyze your week..."):
            summary = generate_weekly_summary(week_stats, lab_trend, correlations)

        st.markdown(summary)
        st.divider()
        st.caption("**This week's data sent to Claude:**")
        with st.expander("View prompt data"):
            st.code(f"{week_stats}\n\nLabs:\n{lab_trend}\n\nCorrelations:\n{correlations}")
    except Exception as e:
        st.error(f"Error in Weekly Summary tab: {str(e)}")
        st.write(f"Debug info: last_date = {last_date if 'last_date' in locals() else 'N/A'}")
