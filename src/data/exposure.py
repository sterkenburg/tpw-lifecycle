"""Build `supplier_exposure_daily` — the per-supplier daily exposure rollup (WS-A).

Source: `ga4_dataform_reporting.monthly_profile_stats` — a (profile_id, date,
event_name) skeleton where the metric column **named after event_name** holds the
value (the `view_item` row populates `view_item`, the `view_item_list` row
populates `view_item_list`, etc.). We collapse the per-event rows into one
exposure row per (profile_id, date).

The aggregation runs **inside BigQuery** (the source is ~388M rows — never pulled
to pandas). Source and destination are both in the EU location, so it's a pure
server-side INSERT…SELECT.

Exposure is what drives retention (see docs/strategy/17). Category/segment and
Elastic rank are intentionally NOT joined here (different BQ region / source);
they're added downstream in the targeting step.

Lives in the EU `retention` dataset (co-located with the GA4 source so the
aggregation is a pure server-side INSERT…SELECT). Since the 2026-06-05 US→EU
migration the platform `retention` dataset is itself EU, so exposure and platform
tables now share one dataset (`dataset` == `dataset_eu` == `retention`).

COVERAGE CAVEAT: the source only populates the funnel metrics (view_item,
view_item_list, show_phone, select_item) from **2025-01 onward** — pre-2025 rows
exist but are null, so profile_views/impressions are 0 before 2025. Sufficient for
current/recent at-risk targeting; for a longer history, blend in raw
`ga4_dataform_output.view_item` (2023+) — see Spike 2 (YOO-229).
"""

import os
from datetime import date, timedelta

import yaml

from . import client

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "settings.yaml")
with open(_CONFIG_PATH) as _f:
    _CONFIG = yaml.safe_load(_f)

# Lives in the EU `retention` dataset (co-located with the GA4 source so the
# aggregation is a pure server-side INSERT…SELECT). Post-migration the platform
# dataset is also EU, so `DATASET_EU` and the platform dataset are the same.
_SOURCE = _CONFIG["sources"]["monthly_profile_stats"]
_TABLE = f"{client.PROJECT_ID}.{client.DATASET_EU}.{_CONFIG['tables']['supplier_exposure']}"

_COLUMNS = (
    "profile_id, date, profile_views, impressions, list_clicks, show_phone, "
    "website_open, wishlist, purchase, profile_total_time, ingested_at"
)


def ensure_table() -> None:
    """Create the EU dataset (if needed) and the partitioned destination table."""
    client.ensure_dataset(client.DATASET_EU, location="EU")
    client.execute(
        f"""
        CREATE TABLE IF NOT EXISTS `{_TABLE}` (
            profile_id STRING,
            date DATE,
            profile_views INT64,
            impressions INT64,
            list_clicks INT64,
            show_phone INT64,
            website_open INT64,
            wishlist INT64,
            purchase INT64,
            profile_total_time INT64,
            ingested_at TIMESTAMP
        )
        PARTITION BY date
        """
    )


def latest_date() -> date | None:
    """Latest date present in the rollup (None when empty)."""
    df = client.query_eu(f"SELECT MAX(date) AS d FROM `{_TABLE}`")
    value = df["d"].iloc[0] if len(df) else None
    if value is None or str(value) in ("NaT", "None", "nan"):
        return None
    return date.fromisoformat(str(value)[:10])


def refresh_start(today: date, latest: date | None, overlap_days: int = 3,
                  max_backfill_days: int = 120) -> date:
    """First day to rebuild: overlap the newest rows already present, so a
    multi-day outage is backfilled once the source catches up. Bounded so a
    long-empty table does not trigger an unbounded rebuild."""
    start = today - timedelta(days=overlap_days)
    if latest is not None:
        start = min(start, latest - timedelta(days=overlap_days))
    return max(start, today - timedelta(days=max_backfill_days))


# A day is only replaced when the rebuilt rows are at least this share of the
# rows already stored for it: a partial source result keeps the previous rows.
MIN_REPLACE_RATIO = 0.8


def build(start_date: str, end_date: str) -> int:
    """(Re)build supplier_exposure_daily for the inclusive [start_date, end_date].

    Safe to run daily and after outages:
    - the source aggregation is staged first, then DELETE + INSERT run in one
      BigQuery transaction, so a SQL failure leaves the previous rows intact;
    - a day is replaced only when the staged rows are at least MIN_REPLACE_RATIO
      of the rows already stored for it (new days are always written), so a
      partial source result cannot overwrite a complete day.
    Only profile-days with at least one event are written. Returns the number of
    rows in the window after the rebuild.

    Args:
        start_date / end_date: 'YYYY-MM-DD'.
    """
    start_date = str(date.fromisoformat(start_date))
    end_date = str(date.fromisoformat(end_date))
    ensure_table()

    client.execute(
        f"""
        CREATE TEMP TABLE staged AS
        SELECT
            profile_id, date, profile_views, impressions, list_clicks, show_phone,
            website_open, wishlist, purchase, profile_total_time,
            CURRENT_TIMESTAMP() AS ingested_at
        FROM (
            SELECT
                CAST(profile_id AS STRING) AS profile_id,
                date,
                CAST(COALESCE(SUM(view_item), 0) AS INT64)          AS profile_views,
                CAST(COALESCE(SUM(view_item_list), 0) AS INT64)     AS impressions,
                CAST(COALESCE(SUM(select_item), 0) AS INT64)        AS list_clicks,
                CAST(COALESCE(SUM(show_phone), 0) AS INT64)         AS show_phone,
                CAST(COALESCE(SUM(website_open), 0) AS INT64)       AS website_open,
                CAST(COALESCE(SUM(add_to_wishlist), 0) AS INT64)    AS wishlist,
                CAST(COALESCE(SUM(purchase), 0) AS INT64)           AS purchase,
                CAST(COALESCE(SUM(profile_total_time), 0) AS INT64) AS profile_total_time
            FROM `{_SOURCE}`
            WHERE date BETWEEN '{start_date}' AND '{end_date}'
              AND profile_id IS NOT NULL
            GROUP BY profile_id, date
        )
        WHERE profile_views > 0 OR impressions > 0 OR list_clicks > 0 OR show_phone > 0
           OR website_open > 0 OR wishlist > 0 OR purchase > 0;

        CREATE TEMP TABLE accepted AS
        SELECT s.date
        FROM (SELECT date, COUNT(*) AS n FROM staged GROUP BY date) AS s
        LEFT JOIN (
            SELECT date, COUNT(*) AS n FROM `{_TABLE}`
            WHERE date BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY date
        ) AS e USING (date)
        WHERE e.n IS NULL OR s.n >= {MIN_REPLACE_RATIO} * e.n;

        BEGIN TRANSACTION;
        DELETE FROM `{_TABLE}` WHERE date IN (SELECT date FROM accepted);
        INSERT INTO `{_TABLE}` ({_COLUMNS})
        SELECT {_COLUMNS} FROM staged WHERE date IN (SELECT date FROM accepted);
        COMMIT TRANSACTION;
        """
    )
    rows = client.query_eu(
        f"SELECT COUNT(*) AS n FROM `{_TABLE}` WHERE date BETWEEN '{start_date}' AND '{end_date}'"
    )
    return int(rows["n"].iloc[0])
