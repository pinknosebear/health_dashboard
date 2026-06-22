"""
Trajectory — N-of-1 Health Experimentation Dashboard.

Run:
    streamlit run app.py
"""
import os
import sqlite3
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

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
    "fat_mass_lbs": "Fat Mass (lb)",
    "muscle_mass_lbs": "Muscle Mass (lb)",
    "bone_mass_lbs": "Bone Mass (lb)",
    "hydration_lbs": "Hydration (lb)",
    "bp_heart_rate": "BP Heart Rate (bpm)",
    "systolic": "Systolic (mmHg)",
    "diastolic": "Diastolic (mmHg)",
}

st.set_page_config(page_title="Trajectory", page_icon="📈", layout="wide")


@st.cache_data
def load_metrics():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM daily_metrics", conn, parse_dates=["date"])
    conn.close()
    return df.sort_values("date").reset_index(drop=True)


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


def add_daily_log(date, entry_type, meal_type, rating, notes, photo_bytes, photo_filename):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO daily_log
           (date, entry_type, meal_type, rating, notes, photo, photo_filename)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (str(date), entry_type, meal_type, rating, notes, photo_bytes, photo_filename),
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


if not os.path.exists(DB_PATH):
    st.error("health.db not found. Run `python ingest.py` first.")
    st.stop()

df = load_metrics()
metric_cols = [c for c in df.columns if c != "date" and df[c].notna().any()]

st.title("📈 Trajectory")
st.caption("An AI-powered N-of-1 health experimentation platform")

tab_overview, tab_trends, tab_corr, tab_exp, tab_log = st.tabs(
    ["Overview", "Trends", "Correlations", "Experiments", "Daily Log"]
)

# ---------------------------------------------------------------- Overview
with tab_overview:
    st.subheader("Last 7 days")
    last_date = df["date"].max()
    recent = df[df["date"] > last_date - pd.Timedelta(days=7)]
    prior = df[(df["date"] <= last_date - pd.Timedelta(days=7)) &
               (df["date"] > last_date - pd.Timedelta(days=14))]

    card_metrics = [m for m in [
        "steps", "sleep_hours", "hrv", "resting_hr", "active_calories",
        "exercise_minutes", "weight_lbs", "fat_mass_lbs", "muscle_mass_lbs",
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
        cols[i % 3].metric(label(m), f"{cur:,.1f}", delta)

    st.divider()
    st.caption(f"Data spans {df['date'].min():%Y-%m-%d} to {df['date'].max():%Y-%m-%d} "
               f"({len(df)} days)")

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
        default=[m for m in ["steps", "sleep_hours", "weight_lbs"] if m in metric_cols],
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
        st.plotly_chart(fig, width="stretch")

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
        entry_type = st.radio("What are you logging?", ["Sleep", "Food"], horizontal=True, label_visibility="collapsed")

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

        else:  # Food
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

    else:  # View log
        st.markdown("#### 📋 View Log")
        view_date = st.date_input("Filter by date", value=datetime.today(), key="view_date")
        logs = load_daily_log(str(view_date))

        if logs.empty:
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
