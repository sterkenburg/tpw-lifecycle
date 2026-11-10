"""Churn risk scoring for suppliers whose renewal is still undecided.

Two separate things, kept separate:

- renewal_status is a FACT read from booked plans (will_churn = Gratis downgrade
  scheduled, already_renewed = paid renewal booked, lapsed = already on Gratis).
  It decides which queue a supplier belongs in, not how risky they are.
- churn_probability is the fitted churn model's probability that the supplier
  does not renew (signals/churn_model.py, config/churn_model.json): a logistic
  regression on past renewal decisions using loyalty (prior paid plans), share
  of site-wide profile views and lead recency, measured 60 days before plan end.
  It is calibrated at that horizon; read it as "x% chance of not renewing".

priority_tier (P1-P4) is assigned only to undecided suppliers
(renewal_status == 'active'), from probability cutoffs in config/settings.yaml
(`thresholds`). Decided suppliers get no tier, so tier-based queues contain only
suppliers whose outcome can still change. An undecided supplier whose plan has
already ended without any booked renewal is always P1.
"""

import os

import pandas as pd
import yaml

from signals import churn_model

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "settings.yaml")
with open(_CONFIG_PATH) as f:
    _CONFIG = yaml.safe_load(f)
_THRESHOLDS = _CONFIG["thresholds"]

UNDECIDED = "active"
LOW_VIEWS_60D = 10  # risk-factor text only


def _num(value) -> float | None:
    """A finite float, or None for missing/NaN/NA."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    return float(value)


def _tier(prob: float) -> str:
    if prob >= _THRESHOLDS["churn_p1"]:
        return "P1"
    if prob >= _THRESHOLDS["churn_p2"]:
        return "P2"
    if prob >= _THRESHOLDS["churn_p3"]:
        return "P3"
    return "P4"


def _risk_factors(row: pd.Series) -> str:
    factors = []
    status = row.get("renewal_status", UNDECIDED)
    if status == "lapsed":
        factors.append("Churned (now on Gratis)")
    elif status == "will_churn":
        factors.append("Cancellation scheduled (Gratis)")
    elif status == "already_renewed":
        factors.append("Already renewed")

    prior = _num(row.get("num_paid_plans_before"))
    if prior is None:
        factors.append("Unknown plan history")
    elif prior == 0:
        factors.append("First paid term")

    days_since_view = _num(row.get("days_since_last_login"))
    if days_since_view is None:
        factors.append("No profile views in 90 days")
    elif days_since_view > 30:
        factors.append("No profile views in 30+ days")
    elif (_num(row.get("profile_views_60d")) or 0) < LOW_VIEWS_60D:
        factors.append("Very low views")

    trend = _num(row.get("engagement_trend")) or 0.0
    if trend <= -0.5:
        factors.append("Views down 50%+")

    days_since_lead = _num(row.get("days_since_last_lead"))
    if days_since_lead is None or days_since_lead > 60:
        factors.append("No leads in 60+ days")

    days_to_renewal = _num(row.get("days_until_renewal"))
    if days_to_renewal is not None and status == UNDECIDED:
        if 0 <= days_to_renewal <= 30:
            factors.append("Renewal within 30 days")
        elif days_to_renewal < 0:
            factors.append("Contract ended, no renewal booked")

    return ", ".join(factors) if factors else "Stable"


def _action(row: pd.Series) -> str:
    status = row.get("renewal_status", UNDECIDED)
    if status == "lapsed":
        return "CHURNED: Winback, learn why"
    if status == "will_churn":
        return "CANCELLATION SCHEDULED: Save call before plan end, else exit interview"
    if status == "already_renewed":
        if row["churn_probability"] >= _THRESHOLDS["churn_p1"]:
            return "RENEWED, low engagement: Check-in call"
        return "RENEWED: Monitor engagement"
    tier = row.get("priority_tier")
    if tier == "P1":
        return "URGENT: Call within 24h"
    if tier == "P2":
        return "HIGH: Send re-engagement email + schedule call"
    if tier == "P3":
        return "MEDIUM: Include in monthly nurture"
    return "LOW: Standard nurture"


def calculate(stats: pd.DataFrame, model: dict | None = None) -> pd.DataFrame:
    """Add churn_probability, priority_tier, risk_factors and recommended_action."""
    df = stats.copy()
    if "renewal_status" not in df.columns:
        df["renewal_status"] = UNDECIDED
    df["renewal_status"] = df["renewal_status"].fillna(UNDECIDED)

    inputs = pd.DataFrame({
        "prior_paid_plans": df.get("num_paid_plans_before"),
        "profile_views_60d": df.get("profile_views_60d"),
        "site_views_60d": df.get("site_views_60d"),
        "days_since_last_lead": df.get("days_since_last_lead"),
    }, index=df.index)
    df["churn_probability"] = churn_model.predict(inputs, model).round(4)

    undecided = df["renewal_status"] == UNDECIDED
    tiers = df["churn_probability"].apply(_tier)
    days_to_renewal = pd.to_numeric(df.get("days_until_renewal"), errors="coerce")
    ended_unbooked = undecided & (days_to_renewal < 0)
    tiers = tiers.where(~ended_unbooked, "P1")
    df["priority_tier"] = tiers.where(undecided, None)

    df["risk_factors"] = df.apply(_risk_factors, axis=1)
    df["recommended_action"] = df.apply(_action, axis=1)
    return df
