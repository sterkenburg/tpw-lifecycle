"""Aggregate per-supplier statistics from raw data. One table to rule them all."""

import pandas as pd

# Engagement trend compares two EQUAL windows of this many days, both anchored on
# the latest date present in the GA4 activity feed (the Dataform export lands
# after the daily job runs, so "today" would leave the recent window short and
# read as a decline for everyone).
TREND_WINDOW_DAYS = 30
# Below this many views in the earlier window the ratio is noise; trend = 0.
TREND_MIN_BASE_VIEWS = 5

# Count columns where "no rows" genuinely means zero. Other columns (metadata,
# email, plan history) keep their NULLs.
_COUNT_COLUMNS = ["profile_views_60d", "profile_views_60_90d", "leads_60d"]


def calculate(
    suppliers: pd.DataFrame,
    activity: pd.DataFrame,
    leads: pd.DataFrame,
    contract_activity: pd.DataFrame | None = None,
    contract_leads: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build supplier_stats_daily from raw data.

    Returns one row per active supplier with all metrics needed by
    dashboard, emails, churn scoring, and notifications.
    """
    today = pd.Timestamp.now().normalize()
    df = suppliers.copy()

    # --- Profile views ---
    # `activity` is either one row per view event (legacy pageview feed) or one
    # row per supplier-day with a `views` count (exposure rollup). All view
    # windows end on the latest date in the feed: the GA4 export lags the job by
    # ~2 days, and "today"-anchored windows would read as a decline for everyone.
    anchor = activity["event_date"].max() if not activity.empty else today
    if pd.isna(anchor):
        anchor = today

    def _views_between(after_days: int, until_days: int, name: str) -> pd.Series:
        """Views with anchor - after_days < event_date <= anchor - until_days."""
        rows = activity[
            (activity["event_date"] > anchor - pd.Timedelta(days=after_days))
            & (activity["event_date"] <= anchor - pd.Timedelta(days=until_days))
        ]
        grouped = rows.groupby("profile_id")
        counts = grouped["views"].sum() if "views" in rows.columns else grouped.size()
        return counts.rename(name)

    views_60d = _views_between(60, 0, "profile_views_60d")
    views_60_90d = _views_between(90, 60, "profile_views_60_90d")
    # Equal-window engagement trend: last 30 days vs the 30 days before.
    views_recent = _views_between(TREND_WINDOW_DAYS, 0, "_views_recent")
    views_prior = _views_between(2 * TREND_WINDOW_DAYS, TREND_WINDOW_DAYS, "_views_prior")
    # All profiles' views in the same 60 days (the activity feed covers every
    # profile, not only paying suppliers): the churn model uses each supplier's
    # SHARE of site views, which is robust to seasonality and site-wide shifts.
    site_views_60d = float(views_60d.sum())

    # --- Leads (last 60d) ---
    # Lead rows are pre-aggregated per supplier/day/type (leads.get_last_90d), so
    # the count is the SUM of lead_count, not the number of rows.
    leads_60d = leads[leads["event_date"] >= today - pd.Timedelta(days=60)]
    if "lead_count" in leads_60d.columns:
        lead_counts = leads_60d.groupby("profile_id")["lead_count"].sum().rename("leads_60d")
    else:
        lead_counts = leads_60d.groupby("profile_id").size().rename("leads_60d")

    # --- Merge ---
    df = df.set_index("profile_id")
    df = df.join(views_60d, how="left")
    df = df.join(views_60_90d, how="left")
    df = df.join(lead_counts, how="left")
    df = df.join(views_recent, how="left")
    df = df.join(views_prior, how="left")
    df = df.reset_index()
    for col in [*_COUNT_COLUMNS, "_views_recent", "_views_prior"]:
        df[col] = df[col].fillna(0)

    # --- Contract-period totals ---
    if contract_activity is not None and not contract_activity.empty:
        contract_activity = contract_activity.set_index("profile_id")["contract_views_total"]
        df = df.set_index("profile_id").join(contract_activity, how="left").reset_index()
    else:
        df["contract_views_total"] = 0

    if contract_leads is not None and not contract_leads.empty:
        contract_leads = contract_leads.set_index("profile_id")["contract_leads_total"]
        df = df.set_index("profile_id").join(contract_leads, how="left").reset_index()
    else:
        df["contract_leads_total"] = 0

    df["contract_views_total"] = df.get("contract_views_total", 0).fillna(0).astype(int)
    df["contract_leads_total"] = df.get("contract_leads_total", 0).fillna(0).astype(int)

    # --- Category benchmarks (avg last 60d) ---
    category_avgs = (
        df.groupby("category")
        .agg({"profile_views_60d": "mean", "leads_60d": "mean"})
        .reset_index()
    )
    category_avgs.columns = [
        "category",
        "category_avg_views_60d",
        "category_avg_leads_60d",
    ]
    df = df.merge(category_avgs, on="category", how="left")

    # --- Derived metrics ---
    df["profile_views_60d"] = df["profile_views_60d"].astype(int)
    df["profile_views_60_90d"] = df["profile_views_60_90d"].astype(int)
    df["leads_60d"] = df["leads_60d"].astype(int)

    # Engagement trend: % change in views, last 30 days vs the 30 days before
    # (equal windows). Was 60d vs the prior 30d, which read +100% for a supplier
    # with perfectly flat traffic.
    prior = df["_views_prior"].astype(float)
    trend = (df["_views_recent"].astype(float) - prior) / prior.where(prior > 0)
    df["engagement_trend"] = trend.where(prior >= TREND_MIN_BASE_VIEWS, 0.0).fillna(0.0)
    df = df.drop(columns=["_views_recent", "_views_prior"])

    # Days until renewal
    df["plan_end"] = pd.to_datetime(df["plan_end"], errors="coerce")
    df["days_until_renewal"] = (df["plan_end"] - today).dt.days

    # Days since last lead (if any in 90d window)
    last_lead = (
        leads.groupby("profile_id")["event_date"]
        .max()
        .rename("last_lead_date")
    )
    df = df.set_index("profile_id").join(last_lead, how="left").reset_index()
    # NULL (not a 999 sentinel) when there was no lead in the 90-day window.
    df["days_since_last_lead"] = (
        (today - pd.to_datetime(df["last_lead_date"], errors="coerce")).dt.days.astype("Int64")
    )

    # Days since the last PROFILE VIEW by a visitor. The column keeps its
    # historical name (days_since_last_login) for schema compatibility, but GA4
    # has no supplier-login signal: this measures couple demand, not supplier
    # engagement. NULL when the profile had no views in the 90-day window.
    viewed = activity[activity["views"] > 0] if "views" in activity.columns else activity
    last_view = (
        viewed.groupby("profile_id")["event_date"]
        .max()
        .rename("last_activity_date")
    )
    df = df.set_index("profile_id").join(last_view, how="left").reset_index()
    # Relative to the data anchor (0 = viewed on the latest day with data).
    df["days_since_last_login"] = (
        (anchor - pd.to_datetime(df["last_activity_date"], errors="coerce")).dt.days.astype("Int64")
    )

    # Paid plans before the current one (loyalty). Prefer the count derived from
    # the plan history (suppliers.get_current: prior_paid_plans), which is what
    # the churn model was trained on; fall back to the source column.
    source_col = "prior_paid_plans" if "prior_paid_plans" in df.columns else "num_paid_plans_before"
    if source_col in df.columns:
        df["num_paid_plans_before"] = (
            pd.to_numeric(df[source_col], errors="coerce").round().astype("Int64")
        )

    df["site_views_60d"] = site_views_60d

    # Meta
    df["stats_date"] = today

    # Column order
    cols = [
        "profile_id",
        "profile_name",
        "email",
        "phone",
        "category",
        "plan_name",
        "plan_value",
        "plan_start",
        "plan_end",
        "days_until_renewal",
        "business_status",
        "account_manager",
        "profile_views_60d",
        "profile_views_60_90d",
        "engagement_trend",
        "leads_60d",
        "days_since_last_lead",
        "days_since_last_login",
        "contract_views_total",
        "contract_leads_total",
        "category_avg_views_60d",
        "category_avg_leads_60d",
        "renewal_status",
        "num_paid_plans_before",
        "site_views_60d",
        "stats_date",
    ]
    return df[[c for c in cols if c in df.columns]]
