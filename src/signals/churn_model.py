"""Fitted churn model: features, prediction and fitting (no sklearn needed).

A logistic regression fitted on past renewal decisions (annual paid terms),
with every input measured 60 days before the term's plan_end. The output is a
calibrated probability that the supplier does NOT renew.

The feature definitions below are the single source for both the refit script
(jobs/fit_churn_model.py) and daily scoring (signals/churn_scorer.py), so
training and production can never drift apart.

Inputs (columns of the frame passed to `features`):
  prior_paid_plans     paid plans before the current one (derived from plan history)
  profile_views_60d    profile views in the last 60 days (exposure rollup)
  site_views_60d       all profiles' views in the same 60 days (normalises for
                       seasonality and site-wide traffic shifts)
  days_since_last_lead NULL when there was no lead in the 90-day window

Model file: config/churn_model.json (coefficients, intercept, training metadata).
"""

import json
import os
from datetime import date

import numpy as np
import pandas as pd

MODEL_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "config", "churn_model.json")
)

FEATURES = ["log_prior_plans", "first_term", "log_view_share", "no_leads_90d"]


def features(df: pd.DataFrame) -> pd.DataFrame:
    """Model inputs from the raw per-supplier columns. Missing values are explicit."""
    prior = pd.to_numeric(df["prior_paid_plans"], errors="coerce").astype(float)
    views = pd.to_numeric(df["profile_views_60d"], errors="coerce").astype(float).fillna(0.0)
    site = pd.to_numeric(df["site_views_60d"], errors="coerce").astype(float)
    lead_days = pd.to_numeric(df["days_since_last_lead"], errors="coerce").astype(float)

    share = (views / site.where(site > 0)) * 1e5
    out = pd.DataFrame(index=df.index)
    out["log_prior_plans"] = np.log1p(prior.fillna(0.0).clip(0, 20))
    out["first_term"] = (prior.fillna(0.0) == 0).astype(float)
    out["log_view_share"] = np.log1p(share.fillna(0.0).clip(lower=0))
    out["no_leads_90d"] = lead_days.isna().astype(float)
    return out[FEATURES]


def load(path: str = MODEL_PATH) -> dict:
    with open(path) as f:
        model = json.load(f)
    missing = set(FEATURES) - set(model["coefficients"])
    if missing:
        raise ValueError(f"churn model file lacks coefficients for {sorted(missing)}")
    return model


def predict(df: pd.DataFrame, model: dict | None = None) -> pd.Series:
    """Probability of non-renewal for each row."""
    model = model or load()
    x = features(df)
    coef = np.array([model["coefficients"][name] for name in FEATURES])
    logit = model["intercept"] + x.to_numpy() @ coef
    return pd.Series(1.0 / (1.0 + np.exp(-logit)), index=df.index)


def fit(x: pd.DataFrame, y: pd.Series, l2: float = 1.0, iters: int = 100) -> tuple[float, dict]:
    """L2-regularised logistic regression by Newton's method (intercept unpenalised).

    Same objective as sklearn's LogisticRegression(C=1/l2): log-loss summed over
    rows plus (l2 / 2) * ||w||^2.
    """
    design = np.column_stack([np.ones(len(x)), x[FEATURES].to_numpy(dtype=float)])
    t = y.to_numpy(dtype=float)
    w = np.zeros(design.shape[1])
    penalty = np.full(design.shape[1], float(l2))
    penalty[0] = 0.0
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-(design @ w)))
        grad = design.T @ (p - t) + penalty * w
        hess = (design * (p * (1 - p))[:, None]).T @ design + np.diag(penalty)
        step = np.linalg.solve(hess, grad)
        w -= step
        if np.max(np.abs(step)) < 1e-10:
            break
    return float(w[0]), {name: float(c) for name, c in zip(FEATURES, w[1:], strict=True)}


def save(intercept: float, coefficients: dict, meta: dict, path: str = MODEL_PATH) -> None:
    model = {
        "model": "logistic_regression",
        "version": meta.get("version", date.today().isoformat()),
        "target": "P(paid term not renewed within 45 days of plan_end)",
        "horizon": "inputs measured 60 days before plan_end",
        "features": FEATURES,
        "intercept": round(intercept, 6),
        "coefficients": {k: round(v, 6) for k, v in coefficients.items()},
        "training": meta,
    }
    with open(path, "w") as f:
        json.dump(model, f, indent=2)
        f.write("\n")
