"""Churn scorer: status routing and the fitted model's behaviour on scoring rows."""

import pandas as pd
import pytest

from signals import churn_scorer

SITE = 180_000.0


def _row(**overrides) -> dict:
    """A loyal, visible, undecided supplier with recent leads."""
    base = {
        "profile_id": "1",
        "renewal_status": "active",
        "num_paid_plans_before": 8,
        "days_since_last_login": 2,
        "profile_views_60d": 300,
        "site_views_60d": SITE,
        "engagement_trend": 0.0,
        "days_since_last_lead": 5,
        "days_until_renewal": 200,
        "plan_value": 500.0,
    }
    return {**base, **overrides}


def _score(**overrides) -> pd.Series:
    return churn_scorer.calculate(pd.DataFrame([_row(**overrides)])).iloc[0]


def test_loyal_visible_supplier_is_low_risk():
    r = _score()
    assert r["churn_probability"] < churn_scorer._THRESHOLDS["churn_p3"]
    assert r["priority_tier"] == "P4"


def test_probability_is_a_probability():
    p = _score(num_paid_plans_before=0, profile_views_60d=0, days_since_last_lead=None)
    assert 0.0 < p["churn_probability"] < 1.0


@pytest.mark.parametrize("status", ["will_churn", "already_renewed", "lapsed"])
def test_decided_suppliers_get_no_tier(status):
    r = _score(renewal_status=status, num_paid_plans_before=0, profile_views_60d=0)
    assert r["priority_tier"] is None or pd.isna(r["priority_tier"])


def test_status_does_not_change_probability():
    active = _score()["churn_probability"]
    for status in ["will_churn", "already_renewed", "lapsed"]:
        assert _score(renewal_status=status)["churn_probability"] == active


def test_risk_moves_in_the_expected_directions():
    loyal = _score()["churn_probability"]
    assert _score(num_paid_plans_before=0)["churn_probability"] > loyal
    assert _score(num_paid_plans_before=2)["churn_probability"] > loyal
    assert _score(profile_views_60d=5)["churn_probability"] > loyal
    assert _score(days_since_last_lead=None)["churn_probability"] > loyal


def test_view_share_not_raw_views():
    # Same share of site traffic, different site volume: same risk.
    a = _score(profile_views_60d=300, site_views_60d=SITE)["churn_probability"]
    b = _score(profile_views_60d=150, site_views_60d=SITE / 2)["churn_probability"]
    assert a == pytest.approx(b)


def test_ended_without_booking_is_p1():
    r = _score(days_until_renewal=-3)
    assert r["priority_tier"] == "P1"
    assert "Contract ended, no renewal booked" in r["risk_factors"]


def test_lapsed_and_will_churn_actions():
    assert _score(renewal_status="lapsed")["recommended_action"].startswith("CHURNED")
    assert _score(renewal_status="will_churn")["recommended_action"].startswith(
        "CANCELLATION SCHEDULED"
    )


def test_nan_and_missing_inputs_are_safe():
    r = _score(days_since_last_login=float("nan"), days_since_last_lead=pd.NA,
               num_paid_plans_before=float("nan"), site_views_60d=float("nan"),
               days_until_renewal=float("nan"))
    assert 0.0 < r["churn_probability"] < 1.0


def test_plan_value_does_not_affect_probability():
    assert (_score(plan_value=2000.0)["churn_probability"]
            == _score(plan_value=100.0)["churn_probability"])


def test_nullable_int_columns_from_pipeline():
    df = pd.DataFrame([_row(), _row(profile_id="2")])
    df["days_since_last_login"] = pd.array([None, 4], dtype="Int64")
    df["days_since_last_lead"] = pd.array([None, 3], dtype="Int64")
    df["num_paid_plans_before"] = pd.array([None, 3], dtype="Int64")
    out = churn_scorer.calculate(df)
    assert out["churn_probability"].between(0, 1).all()
    assert out.loc[0, "churn_probability"] > out.loc[1, "churn_probability"]
