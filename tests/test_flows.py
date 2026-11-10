"""Legacy email flow targeting with the status-routed tiers (no tier for decided)."""

import pandas as pd
import pytest

from actions import flows


def _row(**overrides) -> dict:
    base = {
        "profile_id": "1",
        "profile_name": "Test",
        "email": "a@example.com",
        "category": "Trouwfotograaf",
        "renewal_status": "active",
        "priority_tier": "P3",
        "days_since_last_lead": 50,
        "days_until_renewal": 200,
    }
    return {**base, **overrides}


@pytest.mark.parametrize("status", ["will_churn", "lapsed"])
def test_booked_outcomes_get_no_nurture_email(status):
    row = _row(renewal_status=status, priority_tier=None)
    assert flows._reengagement_action(row) is None
    assert flows._monthly_action(row, "november") is None


def test_renewed_supplier_still_gets_nurture():
    row = _row(renewal_status="already_renewed", priority_tier=None)
    assert flows._reengagement_action(row) is not None
    assert flows._monthly_action(row, "november") is not None


@pytest.mark.parametrize("missing", [None, float("nan"), pd.NA, 999])
def test_no_lead_in_window_qualifies_for_reengagement(missing):
    action = flows._reengagement_action(_row(days_since_last_lead=missing))
    assert action is not None
    assert action.payload["days_since_lead"] == "90+"


def test_recent_lead_does_not_qualify():
    assert flows._reengagement_action(_row(days_since_last_lead=10)) is None


def test_p1_is_left_to_a_human():
    assert flows._reengagement_action(_row(priority_tier="P1")) is None
