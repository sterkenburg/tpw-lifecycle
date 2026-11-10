"""Read supplier profile-view data from BigQuery.

Primary source (since 2026-11): `retention.supplier_exposure_daily`, the per
supplier daily rollup of GA4 `view_item` events (data/exposure.py, history from
2025-01). The pipeline features and the fitted churn model both use it.

The Dataform pageview table below misses many paying suppliers: in Mar-May 2026,
212 of the 280 paying suppliers with zero rows there had views in the exposure
rollup (median 43). It also has a gap Apr-Jun 2025. Kept only for legacy helpers.

Legacy source: tpw-ga4-bigquery.ga4_dataform_output.bedrijven_pageview_events
Schema (verified):
  event_date: DATE
  profile_id: INTEGER
  page_location: STRING
  page_title: STRING
  engagement_time_msec: INTEGER
  source: STRING
  medium: STRING
  device_category: STRING
"""

import pandas as pd

from .client import DATASET, PROJECT_ID, query

_PROCESSED_TABLE = "tpw-ga4-bigquery.ga4_dataform_output.bedrijven_pageview_events"
_EXPOSURE_TABLE = f"{PROJECT_ID}.{DATASET}.supplier_exposure_daily"


def get_views_last_90d() -> pd.DataFrame:
    """Daily profile views per supplier for the last 90 days of exposure data.

    Columns: profile_id, event_date, views (one row per supplier-day with at
    least one view). The window ends on the latest date in the rollup (the GA4
    source lags ~2 days), so feature windows are anchored on data, not today.
    """
    sql = f"""
    WITH anchor AS (SELECT MAX(date) AS d FROM `{_EXPOSURE_TABLE}`)
    SELECT
        profile_id,
        date AS event_date,
        profile_views AS views
    FROM `{_EXPOSURE_TABLE}`
    WHERE date > DATE_SUB((SELECT d FROM anchor), INTERVAL 90 DAY)
      AND profile_views > 0
    """
    df = query(sql)
    df["profile_id"] = df["profile_id"].astype(str)
    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
    return df


def get_contract_views(suppliers_df: pd.DataFrame) -> pd.DataFrame:
    """Total profile views since each supplier's plan_start (exposure rollup).

    Aggregated server-side. The rollup starts in 2025-01, so contracts that
    started earlier count views from 2025-01 onward.
    """
    if suppliers_df.empty:
        return pd.DataFrame(columns=["profile_id", "contract_views_total"])
    starts = suppliers_df[["profile_id", "plan_start"]].dropna().copy()
    starts = starts[starts["profile_id"].astype(str).str.isdigit()]
    if starts.empty:
        return pd.DataFrame(columns=["profile_id", "contract_views_total"])
    rows = ",".join(
        f"STRUCT('{int(pid)}' AS profile_id, DATE '{pd.Timestamp(ps).date()}' AS plan_start)"
        for pid, ps in zip(starts["profile_id"], starts["plan_start"], strict=True)
    )
    sql = f"""
    SELECT s.profile_id, SUM(e.profile_views) AS contract_views_total
    FROM UNNEST([{rows}]) s
    JOIN `{_EXPOSURE_TABLE}` e
      ON e.profile_id = s.profile_id AND e.date >= s.plan_start
    GROUP BY s.profile_id
    """
    df = query(sql)
    df["profile_id"] = df["profile_id"].astype(str)
    return df


def get_last_90d() -> pd.DataFrame:
    """Get pageview events for suppliers in the last 90 days."""
    sql = f"""
    SELECT
        CAST(profile_id AS STRING) AS profile_id,
        event_date,
        page_location,
        page_title,
        engagement_time_msec
    FROM `{_PROCESSED_TABLE}`
    WHERE event_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
                         AND CURRENT_DATE()
      AND profile_id IS NOT NULL
      AND profile_id > 0
    """
    df = query(sql)
    if "event_date" in df.columns:
        df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
    return df


def get_contract_period_views(suppliers_df: pd.DataFrame) -> pd.DataFrame:
    """Get total profile views since each supplier's plan_start."""
    if suppliers_df.empty:
        return pd.DataFrame(columns=["profile_id", "contract_views_total"])

    min_plan_start = suppliers_df["plan_start"].min()
    start_date = min_plan_start.strftime("%Y-%m-%d") if pd.notna(min_plan_start) else "2020-01-01"

    ids = [int(pid) for pid in suppliers_df["profile_id"].unique() if str(pid).isdigit()]
    if not ids:
        return pd.DataFrame(columns=["profile_id", "contract_views_total"])

    id_list = ",".join(repr(str(i)) for i in ids)

    sql = f"""
    SELECT
        CAST(profile_id AS STRING) AS profile_id,
        event_date
    FROM `{_PROCESSED_TABLE}`
    WHERE event_date >= '{start_date}'
      AND CAST(profile_id AS STRING) IN ({id_list})
    """
    df = query(sql)
    if df.empty:
        return pd.DataFrame(columns=["profile_id", "contract_views_total"])

    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
    suppliers_df = suppliers_df[["profile_id", "plan_start"]].copy()
    suppliers_df["plan_start"] = pd.to_datetime(suppliers_df["plan_start"], errors="coerce")

    merged = df.merge(suppliers_df, on="profile_id", how="left")
    valid = merged[merged["event_date"] >= merged["plan_start"]]

    counts = valid.groupby("profile_id").size().rename("contract_views_total").reset_index()
    return counts


def get_profile_views(profile_ids: list[str], days: int = 30) -> pd.DataFrame:
    """Get profile view counts per supplier for the last N days."""
    id_list = ",".join(f"{int(pid)}" for pid in profile_ids)
    sql = f"""
    SELECT
        CAST(profile_id AS STRING) AS profile_id,
        COUNT(*) AS view_count
    FROM `{_PROCESSED_TABLE}`
    WHERE event_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
                         AND CURRENT_DATE()
      AND profile_id IN ({id_list})
    GROUP BY profile_id
    """
    return query(sql)
