"""
Trajectory — In-context metric education.

Plain-language, patient-friendly explanations of every metric the dashboard
shows, so Ravi LEARNS what his numbers mean and what "good" looks like.
Pure data + small helpers; no Streamlit dependency.

Wiring:
    import education
    info = education.explain("time_in_range")   # dict or None
    md = education.help_text("time_in_range")    # markdown for popover/tooltip
    education.METRIC_INFO                         # full dict
    education.GLOSSARY                            # [(term, definition), ...]
"""

# Keyed by daily_metrics columns + key lab-test names. Each entry:
#   name   — friendly title
#   what   — one sentence: what it measures
#   why    — one sentence: why it matters (Type 2 diabetes flavored)
#   target — short healthy/goal range
#   tip    — one actionable lever the user controls
METRIC_INFO = {
    # --- Glucose / CGM ---
    "glucose_mean": {
        "name": "Average Glucose",
        "what": "Your average blood sugar across all CGM readings for the day.",
        "why": "It tracks closely with A1c and is the single best summary of how well your blood sugar is controlled.",
        "target": "Roughly 90–130 mg/dL; lower daily averages map to a healthier A1c.",
        "tip": "Walk 10–15 minutes after your largest meal to blunt the average.",
    },
    "time_in_range": {
        "name": "Time in Range",
        "what": "The percentage of the day your glucose stayed between 70 and 180 mg/dL.",
        "why": "More time in range means fewer harmful highs and lows and is a primary goal of diabetes care.",
        "target": "Aim for >70% of readings in range (about 17 of every 24 hours).",
        "tip": "Pairing carbs with protein, fiber, or a short walk keeps you in range longer.",
    },
    "gmi": {
        "name": "GMI (Estimated A1c)",
        "what": "Glucose Management Indicator — an A1c estimate calculated from your average CGM glucose.",
        "why": "It previews what your lab A1c is likely to be, so you can course-correct before the next blood draw.",
        "target": "<7.0% for most adults with Type 2 diabetes; discuss your personal goal with your doctor.",
        "tip": "Steady day-to-day glucose control over weeks is what moves GMI down.",
    },
    "glucose_std": {
        "name": "Glucose Variability",
        "what": "How much your glucose swings up and down during the day (the standard deviation of readings).",
        "why": "Big swings stress the body even when the average looks fine, so smoother is better for diabetes.",
        "target": "Lower is better; a coefficient of variation under ~36% (often std < ~50 mg/dL) is considered stable.",
        "tip": "Eat consistent meals at consistent times and avoid fast-digesting sugary drinks.",
    },
    "glucose_min": {
        "name": "Lowest Glucose",
        "what": "The lowest glucose reading recorded during the day.",
        "why": "Lows (hypoglycemia) can be dangerous, especially overnight or with certain medications.",
        "target": "Stay above 70 mg/dL; below 70 is a low worth noting.",
        "tip": "If you see repeated lows, flag the timing and any medication doses to your doctor.",
    },
    "glucose_max": {
        "name": "Highest Glucose",
        "what": "The highest glucose reading recorded during the day, usually a post-meal spike.",
        "why": "Frequent large spikes raise your average and your long-term complication risk.",
        "target": "Try to keep post-meal peaks under 180 mg/dL.",
        "tip": "Eat protein and veggies before the starchy part of a meal to flatten the peak.",
    },
    # --- Activity / wearable ---
    "steps": {
        "name": "Steps",
        "what": "Total steps your Apple Watch counted for the day.",
        "why": "Movement improves insulin sensitivity, so more steps generally mean better glucose control.",
        "target": "Build toward 7,000–10,000 steps/day; any increase from your baseline helps.",
        "tip": "Take a short walk after meals — it doubles as glucose control and step count.",
    },
    "sleep_hours": {
        "name": "Sleep",
        "what": "How many hours you slept, measured by your Apple Watch.",
        "why": "Short or poor sleep raises next-day glucose and cravings, working against your diabetes goals.",
        "target": "7–9 hours per night, kept consistent from day to day.",
        "tip": "Aim for a steady bedtime; consistency matters as much as total hours.",
    },
    "hrv": {
        "name": "Heart Rate Variability (HRV)",
        "what": "The tiny variation in time between heartbeats, a marker of recovery and stress balance.",
        "why": "Higher HRV signals good recovery and lower stress, which support steadier glucose.",
        "target": "Higher is generally better; track your own trend rather than a fixed number.",
        "tip": "Better sleep, less alcohol, and managing stress tend to raise HRV.",
    },
    "resting_hr": {
        "name": "Resting Heart Rate",
        "what": "Your heart rate at rest, typically measured overnight.",
        "why": "A lower resting heart rate usually reflects better fitness and cardiovascular health.",
        "target": "Roughly 50–70 bpm for most adults; trending down over time is a good sign.",
        "tip": "Regular aerobic activity (even brisk walking) gradually lowers resting heart rate.",
    },
    "active_calories": {
        "name": "Active Calories",
        "what": "Calories burned through movement and exercise, beyond your baseline.",
        "why": "Active energy burn supports weight management and insulin sensitivity in Type 2 diabetes.",
        "target": "Set a personal daily goal (e.g. 300–500 kcal) and aim to hit it most days.",
        "tip": "Stack small bouts of activity — they add up across the day.",
    },
    "exercise_minutes": {
        "name": "Exercise Minutes",
        "what": "Minutes your watch counted as brisk activity for the day.",
        "why": "Regular exercise is one of the strongest levers for lowering glucose and improving health.",
        "target": "About 30 minutes/day or 150 minutes/week of moderate activity.",
        "tip": "Spread it out — three 10-minute walks count just as much as one 30-minute walk.",
    },
    # --- Body composition ---
    "weight_lbs": {
        "name": "Weight",
        "what": "Your body weight in pounds.",
        "why": "Even modest weight loss can meaningfully improve blood sugar and A1c in Type 2 diabetes.",
        "target": "Discuss a personal goal with your doctor; a 5–10% loss often yields big metabolic gains.",
        "tip": "Weigh at the same time each day and watch the weekly trend, not daily noise.",
    },
    "body_fat_pct": {
        "name": "Body Fat",
        "what": "The share of your body weight that is fat tissue.",
        "why": "Excess fat, especially around the belly, drives insulin resistance.",
        "target": "Trend it downward over time; ask your doctor for a target appropriate for you.",
        "tip": "Combining strength work with walking preserves muscle while lowering fat.",
    },
    "lean_mass_lbs": {
        "name": "Lean Mass",
        "what": "The non-fat part of your body weight — mostly muscle, bone, and water.",
        "why": "More muscle stores more glucose and improves insulin sensitivity.",
        "target": "Aim to maintain or gently increase lean mass as you lose fat.",
        "tip": "Add light resistance training a couple of times a week and enough protein.",
    },
    # --- Blood pressure ---
    "systolic": {
        "name": "Systolic Blood Pressure",
        "what": "The top blood-pressure number — pressure when your heart beats.",
        "why": "High blood pressure compounds diabetes risk to the heart, eyes, and kidneys.",
        "target": "Generally under 130 mmHg; confirm your personal target with your doctor.",
        "tip": "Less sodium, more movement, and good sleep all help lower it.",
    },
    "diastolic": {
        "name": "Diastolic Blood Pressure",
        "what": "The bottom blood-pressure number — pressure when your heart rests between beats.",
        "why": "It is the other half of blood-pressure control, which protects diabetic kidneys and heart.",
        "target": "Generally under 80 mmHg.",
        "tip": "The same habits that help systolic — movement, less salt, less stress — help here too.",
    },
    # --- Labs (keyed by lab-test name) ---
    "Hemoglobin A1c": {
        "name": "Hemoglobin A1c",
        "what": "A blood test showing your average glucose over the past 2–3 months.",
        "why": "It is the gold-standard measure of long-term diabetes control.",
        "target": "<7.0% for most adults with Type 2 diabetes; your goal may differ.",
        "tip": "Consistent daily glucose control over months is what brings A1c down.",
    },
    "eGFR": {
        "name": "eGFR (Kidney Function)",
        "what": "An estimate of how well your kidneys filter waste from your blood.",
        "why": "Diabetes is a leading cause of kidney disease, so protecting eGFR is key.",
        "target": "Above 60 mL/min/1.73m² is generally healthy; higher is better.",
        "tip": "Good glucose and blood-pressure control are the best ways to protect your kidneys.",
    },
    "Creatinine": {
        "name": "Creatinine",
        "what": "A waste product in your blood that kidneys clear; used to gauge kidney function.",
        "why": "Rising creatinine can be an early sign of kidney strain in diabetes.",
        "target": "Roughly 0.7–1.3 mg/dL for adults; stable values are reassuring.",
        "tip": "Stay hydrated and keep glucose and blood pressure in check.",
    },
    "Triglycerides": {
        "name": "Triglycerides",
        "what": "A type of fat in your blood, measured by a lipid panel.",
        "why": "They run high in Type 2 diabetes and raise heart-disease risk.",
        "target": "Under 150 mg/dL.",
        "tip": "Cut sugary drinks and refined carbs and add activity — triglycerides respond fast.",
    },
    "Average Glucose": {
        "name": "Average Glucose (Lab)",
        "what": "An average blood-glucose value derived from your A1c lab result.",
        "why": "It translates A1c into the everyday glucose numbers you see on your CGM.",
        "target": "Lower averages map to a lower A1c; track it alongside Time in Range.",
        "tip": "The same levers that lower A1c — diet, movement, sleep — lower this too.",
    },
    "Microalbumin/Creatinine": {
        "name": "Microalbumin/Creatinine Ratio",
        "what": "A urine test for small amounts of protein leaking into urine.",
        "why": "It is one of the earliest warning signs of diabetic kidney damage.",
        "target": "Under 30 mg/g.",
        "tip": "Tight glucose and blood-pressure control can keep this low or even reverse early changes.",
    },
}


def explain(metric):
    """Return the METRIC_INFO entry for a metric key, or None if unknown."""
    return METRIC_INFO.get(metric)


def help_text(metric):
    """Return compact markdown for a Streamlit popover/tooltip, or "" if unknown."""
    info = METRIC_INFO.get(metric)
    if not info:
        return ""
    return (
        f"**What:** {info['what']}\n\n"
        f"**Why it matters:** {info['why']}\n\n"
        f"**Target:** {info['target']}\n\n"
        f"**Lever:** {info['tip']}"
    )


# Ordered layperson glossary of diabetes/CGM/wearable terms.
GLOSSARY = [
    ("CGM", "Continuous Glucose Monitor — a small sensor worn on the body that reads glucose around the clock, no finger pricks."),
    ("Time in Range", "The share of the day your glucose stays between 70 and 180 mg/dL; more is better."),
    ("GMI", "Glucose Management Indicator — an A1c estimate computed from your average CGM glucose."),
    ("A1c", "A blood test reflecting your average glucose over the past 2–3 months."),
    ("HRV", "Heart Rate Variability — the small beat-to-beat timing changes that signal recovery and stress balance."),
    ("Resting Heart Rate", "How fast your heart beats at rest; a lower rate usually means better fitness."),
    ("eGFR", "Estimated Glomerular Filtration Rate — a measure of how well your kidneys filter blood."),
    ("Microalbumin", "A tiny amount of protein in urine that can be an early sign of kidney damage from diabetes."),
    ("Glucose Variability", "How much your glucose swings up and down; smoother, steadier glucose is healthier."),
    ("N-of-1 experiment", "A personal experiment where you test one change on yourself and measure its effect on your own data."),
]
