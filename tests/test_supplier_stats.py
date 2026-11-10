"""supplier_stats feature definitions: trend windows, lead counts, missing values."""

import pandas as pd
import pytest

from analytics import supplier_stats
from signals import engagement


def _suppliers(**overrides) -> pd.DataFrame:
    row = {
        "profile_id": "1",
        "profile_name": "Test",
        "email": None,
        "phone": None,
        "category": "Trouwfotograaf",
        "plan_name": "Regionaal plus",
        "plan_value": 478.5,
        "plan_start": pd.Timestamp.now().normalize() - pd.Timedelta(days=100),
        "plan_end": pd.Timestamp.now().normalize() + pd.Timedelta(days=265),
        "business_status": "retention",
        "account_manager": None,
        "renewal_status": "active",
        "num_paid_plans_before": 3.0,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _daily_views(profile_id: str, per_day: dict[int, int], anchor: pd.Timestamp) -> pd.DataFrame:
    """per_day maps 'days before anchor' -> number of view events."""
    rows = []
    for days_back, n in per_day.items():
        day = anchor - pd.Timedelta(days=days_back)
        rows += [{"profile_id": profile_id, "event_date": day}] * n
    return pd.DataFrame(rows, columns=["profile_id", "event_date"])


EMPTY_LEADS = pd.DataFrame(columns=["profile_id", "event_date", "lead_count"])


def test_flat_traffic_has_zero_trend_even_with_data_lag():
    today = pd.Timestamp.now().normalize()
    anchor = today - pd.Timedelta(days=2)          # GA4 export lags the job
    activity = _daily_views("1", dict.fromkeys(range(0, 90), 2), anchor)
    out = supplier_stats.calculate(_suppliers(), activity, EMPTY_LEADS)
    assert out.loc[0, "engagement_trend"] == pytest.approx(0.0)


def test_halved_traffic_reads_minus_fifty_percent():
    anchor = pd.Timestamp.now().normalize()
    per_day = {d: (2 if d < 30 else 4) for d in range(0, 60)}
    activity = _daily_views("1", per_day, anchor)
    out = supplier_stats.calculate(_suppliers(), activity, EMPTY_LEADS)
    assert out.loc[0, "engagement_trend"] == pytest.approx(-0.5)
    assert len(engagement.detect_decline(out)) == 1


def test_small_base_gives_neutral_trend():
    anchor = pd.Timestamp.now().normalize()
    activity = _daily_views("1", {40: 2, 5: 9}, anchor)
    out = supplier_stats.calculate(_suppliers(), activity, EMPTY_LEADS)
    assert out.loc[0, "engagement_trend"] == 0.0


def test_leads_sum_lead_count_not_rows():
    today = pd.Timestamp.now().normalize()
    leads = pd.DataFrame([
        {"profile_id": "1", "event_date": today - pd.Timedelta(days=3), "lead_count": 4},
        {"profile_id": "1", "event_date": today - pd.Timedelta(days=10), "lead_count": 2},
    ])
    activity = _daily_views("1", {1: 1}, today)
    out = supplier_stats.calculate(_suppliers(), activity, leads)
    assert out.loc[0, "leads_60d"] == 6
    assert out.loc[0, "days_since_last_lead"] == 3


def test_missing_activity_is_null_not_999():
    activity = pd.DataFrame(columns=["profile_id", "event_date"])
    activity["event_date"] = pd.to_datetime(activity["event_date"])
    out = supplier_stats.calculate(_suppliers(), activity, EMPTY_LEADS)
    assert pd.isna(out.loc[0, "days_since_last_login"])
    assert pd.isna(out.loc[0, "days_since_last_lead"])
    assert out.loc[0, "profile_views_60d"] == 0
    assert len(engagement.detect_no_activity(out)) == 1


def test_metadata_nulls_are_kept_and_prior_plans_persisted():
    out = supplier_stats.calculate(
        _suppliers(), _daily_views("1", {1: 1}, pd.Timestamp.now().normalize()), EMPTY_LEADS
    )
    assert out.loc[0, "email"] is None or pd.isna(out.loc[0, "email"])
    assert out.loc[0, "account_manager"] is None or pd.isna(out.loc[0, "account_manager"])
    assert out.loc[0, "num_paid_plans_before"] == 3
    assert str(out["num_paid_plans_before"].dtype) == "Int64"
