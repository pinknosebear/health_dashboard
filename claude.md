# Project Plan: Trajectory

## An AI-Powered N-of-1 Health Experimentation Platform

### Project Goal

Build a platform that transforms wearable and biomarker data into scientifically structured personal health experiments.

The initial user is a single participant (my father) with:

* Type 2 diabetes
* Continuous glucose monitoring
* Apple Watch
* Withings scale
* Laboratory testing

The objective is to determine whether AI can help identify causal relationships between behaviors and health outcomes more effectively than existing health dashboards.

---

# Problem

Healthcare has become extremely effective at collecting data.

Examples:

* Continuous glucose monitors
* Smart watches
* Smart scales
* Laboratory testing

However, patients still struggle to answer:

* Which habits improve my health?
* Which interventions matter most?
* How do I know if a change actually worked?

Current products focus on observation.

Very few products focus on experimentation.

---

# Hypothesis

Individuals can meaningfully improve health outcomes when provided with:

1. Continuous biological data
2. Structured experimentation frameworks
3. AI-generated insight synthesis
4. Longitudinal feedback loops

---

# Phase 1: Data Collection

## Objective

Create a unified health dataset.

### Data Sources

#### LibreView

Metrics:

* Glucose
* Time in Range
* Average glucose
* GMI
* Glucose variability

Collection Method:

* CSV export

#### Apple Health

Metrics:

* Sleep duration
* Sleep consistency
* Resting heart rate
* HRV
* Steps
* Exercise

Collection Method:

* Apple Health XML export

#### Withings

Metrics:

* Weight
* Body fat
* Muscle mass
* Visceral fat estimate

Collection Method:

* CSV export initially
* API later

#### Laboratory Results

Metrics:

* A1c
* Lipid panel
* Kidney function
* Fasting glucose

Collection Method:

* Manual entry

---

# Deliverable 1

Unified dataset.

Schema:

Date

Glucose Metrics
Sleep Metrics
Exercise Metrics
Body Composition Metrics
Medication Changes
Nutrition Notes

---

# Phase 2: Analytics Layer

## Objective

Identify meaningful predictors.

### Questions

What predicts:

* improved Time in Range?
* lower glucose variability?
* lower average glucose?
* weight loss?

### Analysis Methods

Correlation

Example:

Sleep vs Glucose

Regression

Example:

Sleep
Steps
Weight

Predicting:

Average Glucose

Time-Series Analysis

Identify delayed effects.

Example:

Poor sleep today

Affects glucose tomorrow

---

# Deliverable 2

Personal Metabolic Report

Outputs:

Top positive predictors

Top negative predictors

Potential confounders

Behavior ranking

---

# Phase 3: Experiment Framework

## Objective

Build a structured experimentation engine.

### Experiment Components

Hypothesis

Intervention

Duration

Success Metric

Compliance Threshold

---

### Example

Hypothesis:

15-minute walk after dinner reduces glucose spikes.

Intervention:

Walk after dinner.

Duration:

14 days.

Success Metric:

Peak glucose.

Compliance:

80%.

---

# Deliverable 3

Experiment Builder Interface

User selects:

* sleep
* exercise
* nutrition
* timing
* medication discussion topics

System generates protocol.

---

# Phase 4: AI Research Assistant

## Objective

Automate interpretation.

Inputs:

* biomarker data
* experiment data
* compliance data

Outputs:

Research-style report.

Example:

Experiment #4

Hypothesis:

Earlier bedtime improves glucose control.

Result:

Average glucose improved 12%.

Confidence:

Moderate.

Recommendation:

Continue intervention.

---

# Phase 5: Prediction Layer

## Objective

Build personalized health models.

Questions:

What happens if:

* bedtime shifts by 1 hour?
* weight decreases by 10 pounds?
* post-meal walking increases?

Outputs:

Projected effects on:

* glucose
* A1c
* weight
* Time in Range

---

# Technical Architecture

Frontend

Streamlit

Version 1

React

Version 2

Backend

Python

Libraries:

Pandas

Scikit-Learn

Statsmodels

Database

SQLite

Version 1

Postgres

Version 2

AI Layer

OpenAI API

Functions:

Insight generation

Experiment design

Report generation

---

# Success Metrics

Clinical

Improved Time in Range

Lower glucose variability

Reduced A1c

Behavioral

Experiments completed

Intervention adherence

Weekly engagement

Product

Actionable insights generated

Prediction accuracy

Retention

---

# Portfolio Outcome

Demonstrate ability to:

* Integrate healthcare data systems
* Design AI products
* Apply systems thinking to medicine
* Translate biological signals into interventions
* Build a precision-health platform

This project serves as a bridge between biology, healthcare, product management, AI, and digital health innovation.
