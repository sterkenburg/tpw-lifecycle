"""Engagement trend detection — separate from churn scoring."""

import pandas as pd


def detect_decline(stats: pd.DataFrame, threshold: float = -0.5) -> pd.DataFrame:
    """Flag suppliers with significant engagement decline.

    engagement_trend compares profile views over two equal 30-day windows (see
    supplier_stats.TREND_WINDOW_DAYS), so a value <= -0.5 means views halved.
    """
    declining = stats[stats["engagement_trend"] <= threshold].copy()
    declining["signal_type"] = "engagement_decline"
    declining["signal_severity"] = declining["engagement_trend"].apply(
        lambda x: "severe" if x <= -0.75 else "moderate"
    )
    return declining


def detect_no_activity(stats: pd.DataFrame, days: int = 30) -> pd.DataFrame:
    """Flag suppliers whose profile had no visitor views in the last N days.

    days_since_last_login holds days since the last PROFILE VIEW (NULL = no views
    in the 90-day window, which counts as inactive).
    """
    since = pd.to_numeric(stats["days_since_last_login"], errors="coerce")
    inactive = stats[since.isna() | (since > days)].copy()
    inactive["signal_type"] = "no_activity"
    since_inactive = pd.to_numeric(inactive["days_since_last_login"], errors="coerce")
    inactive["signal_severity"] = [
        "severe" if pd.isna(d) or d > 60 else "moderate" for d in since_inactive
    ]
    return inactive
