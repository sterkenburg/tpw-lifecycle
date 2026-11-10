"""Rule-based churn risk scoring for suppliers whose renewal is still undecided.

Two separate things, kept separate:

- renewal_status is a FACT read from booked plans (will_churn = Gratis downgrade
  scheduled, already_renewed = paid renewal booked, lapsed = already on Gratis).
  It decides which queue a supplier belongs in, not how risky they are.
- churn_probability is a behavioural RISK SCORE: the historical non-renewal rate
  for the supplier's loyalty level (number of prior paid plans) plus adjustments
  for low profile demand, falling views, no leads and renewal timing. It is a
  hand-set relative ranking, not a calibrated probability (despite the column
  name, kept for schema compatibility).

priority_tier (P1-P4) is assigned only to undecided suppliers
(renewal_status == 'active'); everyone else gets no tier, so tier-based queues
(P1 calls, revenue at risk) contain only suppliers whose outcome can still change.

Weights live in config/settings.yaml (`churn_scoring`, `thresholds`).
"""

import os

import pandas as pd
import yaml

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "settings.yaml")
with open(_CONFIG_PATH) as f:
    _CONFIG = yaml.safe_load(f)
_THRESHOLDS = _CONFIG["thresholds"]
_W = _CONFIG["churn_scoring"]

# Prior-plan buckets, highest minimum first: (min_prior_plans, base_rate)
_PRIOR_BASE = sorted(
    ((int(k), float(v)) for k, v in _W["prior_plan_base"].items()), reverse=True
)

UNDECIDED = "active"


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


def _base_rate(prior_plans: float | None) -> float:
    if prior_plans is None or prior_plans < 0:
        return float(_W["unknown_plan_history_base"])
    for min_plans, rate in _PRIOR_BASE:
        if prior_plans >= min_plans:
            return rate
    return float(_W["unknown_plan_history_base"])


def _calculate_raw_score(row: pd.Series) -> float:
    """Behavioural risk score in [0, 1]. Higher = more likely not to renew.

    Ignores renewal_status on purpose: booked outcomes are routed by status,
    not folded into the score.
    """
    score = _base_rate(_num(row.get("num_paid_plans_before")))

    # Profile demand (visitor views). NULL days = no views in the 90-day window.
    days_since_view = _num(row.get("days_since_last_login"))
    if days_since_view is None:
        score += _W["no_views_90d"]
    else:
        capped = min(max(days_since_view, 0.0), float(_W["view_recency_cap_days"]))
        score += capped * _W["per_day_since_last_view"]

    views_60d = _num(row.get("profile_views_60d")) or 0.0
    if views_60d < _W["low_views_threshold"]:
        score += _W["low_views_60d"]

    trend = _num(row.get("engagement_trend")) or 0.0
    if trend <= -0.5:
        score += _W["views_down_50pct"]
    elif trend <= -0.2:
        score += _W["views_down_20pct"]

    days_since_lead = _num(row.get("days_since_last_lead"))
    if days_since_lead is None or days_since_lead > 60:
        score += _W["no_leads_60d"]

    days_to_renewal = _num(row.get("days_until_renewal"))
    if days_to_renewal is not None:
        if 0 <= days_to_renewal <= 30:
            score += _W["renewal_within_30d"]
        elif days_to_renewal < 0 and row.get("renewal_status", UNDECIDED) == UNDECIDED:
            score += _W["ended_no_renewal"]

    return max(0.0, min(1.0, score))


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
    elif (_num(row.get("profile_views_60d")) or 0) < _W["low_views_threshold"]:
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


def calculate(stats: pd.DataFrame) -> pd.DataFrame:
    """Add churn_probability, priority_tier, risk_factors and recommended_action."""
    df = stats.copy()
    if "renewal_status" not in df.columns:
        df["renewal_status"] = UNDECIDED
    df["renewal_status"] = df["renewal_status"].fillna(UNDECIDED)

    df["churn_probability"] = df.apply(_calculate_raw_score, axis=1).round(4)

    undecided = df["renewal_status"] == UNDECIDED
    df["priority_tier"] = df["churn_probability"].apply(_tier).where(undecided, None)

    df["risk_factors"] = df.apply(_risk_factors, axis=1)
    df["recommended_action"] = df.apply(_action, axis=1)
    return df
