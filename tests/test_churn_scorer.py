"""Churn scorer: status routing, missing-data handling and behavioural weights."""

import pandas as pd
import pytest

from signals import churn_scorer


def _row(**overrides) -> dict:
    """A healthy, loyal, undecided supplier; tests override what they need."""
    base = {
        "profile_id": "1",
        "renewal_status": "active",
        "num_paid_plans_before": 8,
        "days_since_last_login": 2,
        "profile_views_60d": 120,
        "engagement_trend": 0.0,
        "days_since_last_lead": 5,
        "days_until_renewal": 200,
        "plan_value": 500.0,
    }
    return {**base, **overrides}


def _score(**overrides) -> pd.Series:
    return churn_scorer.calculate(pd.DataFrame([_row(**overrides)])).iloc[0]


def test_healthy_loyal_supplier_is_low_risk():
    r = _score()
    assert r["churn_probability"] == pytest.approx(0.11 + 2 * 0.0025)
    assert r["priority_tier"] == "P4"
    assert r["risk_factors"] == "Stable"


@pytest.mark.parametrize("status", ["will_churn", "already_renewed", "lapsed"])
def test_decided_suppliers_get_no_tier(status):
    r = _score(renewal_status=status, days_since_last_login=None, profile_views_60d=0,
               num_paid_plans_before=0, days_since_last_lead=None)
    assert r["priority_tier"] is None or pd.isna(r["priority_tier"])
    # The score stays behavioural: a booked status never forces it to 1.0.
    assert r["churn_probability"] < 1.0


def test_status_does_not_change_score():
    active = _score()["churn_probability"]
    for status in ["will_churn", "already_renewed", "lapsed"]:
        assert _score(renewal_status=status)["churn_probability"] == active


def test_lapsed_routes_to_winback():
    r = _score(renewal_status="lapsed", days_until_renewal=-5)
    assert r["recommended_action"].startswith("CHURNED")
    assert "Churned (now on Gratis)" in r["risk_factors"]
    # The ended-term penalty is for undecided suppliers only.
    assert "Contract ended" not in r["risk_factors"]


def test_will_churn_gets_save_action():
    r = _score(renewal_status="will_churn")
    assert r["recommended_action"].startswith("CANCELLATION SCHEDULED")


def test_first_term_raises_base_rate():
    loyal = _score()["churn_probability"]
    first = _score(num_paid_plans_before=0)["churn_probability"]
    assert first - loyal == pytest.approx(0.40 - 0.11)
    assert "First paid term" in _score(num_paid_plans_before=0)["risk_factors"]


def test_missing_plan_history_uses_unknown_base():
    r = _score(num_paid_plans_before=None)
    assert r["churn_probability"] == pytest.approx(0.40 + 2 * 0.0025)
    assert "Unknown plan history" in r["risk_factors"]


def test_no_view_data_is_capped_not_maxed():
    r = _score(days_since_last_login=None, profile_views_60d=0)
    # base 0.11 + no views 0.15 + low views 0.05
    assert r["churn_probability"] == pytest.approx(0.31)
    assert "No profile views in 90 days" in r["risk_factors"]


def test_nan_inputs_never_produce_certainty():
    r = _score(days_since_last_login=float("nan"), engagement_trend=float("nan"),
               days_since_last_lead=pd.NA, days_until_renewal=float("nan"),
               num_paid_plans_before=float("nan"))
    assert 0.0 <= r["churn_probability"] < 0.8


def test_plan_value_does_not_affect_score():
    assert (_score(plan_value=2000.0)["churn_probability"]
            == _score(plan_value=100.0)["churn_probability"])


def test_renewal_bump_only_before_plan_end():
    assert "Renewal within 30 days" in _score(days_until_renewal=10)["risk_factors"]
    ended = _score(days_until_renewal=-3)
    assert "Renewal within 30 days" not in ended["risk_factors"]
    assert "Contract ended, no renewal booked" in ended["risk_factors"]
    assert ended["churn_probability"] == pytest.approx(0.11 + 2 * 0.0025 + 0.15)


def test_trend_penalties():
    flat = _score()["churn_probability"]
    assert _score(engagement_trend=-0.6)["churn_probability"] - flat == pytest.approx(0.08)
    assert _score(engagement_trend=-0.3)["churn_probability"] - flat == pytest.approx(0.03)


def test_nullable_int_columns_from_pipeline():
    df = pd.DataFrame([_row(), _row(profile_id="2")])
    df["days_since_last_login"] = pd.array([None, 4], dtype="Int64")
    df["days_since_last_lead"] = pd.array([None, None], dtype="Int64")
    df["num_paid_plans_before"] = pd.array([None, 3], dtype="Int64")
    out = churn_scorer.calculate(df)
    # unknown history 0.40 + no views 0.15 + no leads 0.05; 3 prior plans 0.19 + 4d*0.0025 + 0.05
    assert list(out["churn_probability"]) == pytest.approx([0.60, 0.25])
    assert list(out["priority_tier"]) == [churn_scorer._tier(0.60), churn_scorer._tier(0.25)]
