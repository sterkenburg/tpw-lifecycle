"""Streamlit dashboard for the sales team.

Shows:
- At-risk suppliers (P1/P2)
- Revenue at risk
- Action queue
- Outcome tracking

Clean, fast, functional. No 500-line CSS blocks.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

from data import client

st.set_page_config(page_title="TPW Lifecycle", layout="wide")


def load_latest_signals():
    """Load today's signals from BigQuery."""
    sql = """
    SELECT *
    FROM `tpw-ga4-bigquery.retention.supplier_stats_daily`
    WHERE stats_date = (
        SELECT MAX(stats_date) FROM `tpw-ga4-bigquery.retention.supplier_stats_daily`
    )
    ORDER BY churn_probability DESC
    """
    return client.query(sql)


def load_actions():
    """Load recent actions."""
    sql = """
    SELECT *
    FROM `tpw-ga4-bigquery.retention.actions_log`
    WHERE action_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    ORDER BY action_date DESC
    """
    return client.query(sql)


# ------------------------------------------------------------------
# Header
# ------------------------------------------------------------------
st.title("TPW Lifecycle Dashboard")
st.caption("At-risk suppliers requiring attention")

# ------------------------------------------------------------------
# Load data
# ------------------------------------------------------------------
df = load_latest_signals()
if df.empty:
    st.warning("No data found. Run the daily pipeline first.")
    st.stop()

actions = load_actions()

# ------------------------------------------------------------------
# KPIs
# ------------------------------------------------------------------
# Decided suppliers carry no risk tier; show their booked status instead so a
# scheduled cancellation stays visible (it is a save call, not a tier).
_STATUS_LABELS = {"will_churn": "Cancelling", "already_renewed": "Renewed", "lapsed": "Churned"}
df["tier_or_status"] = df["priority_tier"].where(
    df["priority_tier"].notna(), df["renewal_status"].map(_STATUS_LABELS)
)

p1 = df[df["priority_tier"] == "P1"]
p2 = df[df["priority_tier"] == "P2"]
p3 = df[df["priority_tier"] == "P3"]

revenue_at_risk = p1["plan_value"].sum() + p2["plan_value"].sum()

k1, k2, k3, k4 = st.columns(4)
k1.metric("Suppliers", len(df))
k2.metric("Revenue at Risk", f"€{revenue_at_risk:,.0f}")
k3.metric("P1 (Urgent)", len(p1))
k4.metric("P2 (High)", len(p2))

# ------------------------------------------------------------------
# Filters
# ------------------------------------------------------------------
st.sidebar.header("Filters")
show_tier = st.sidebar.multiselect(
    "Priority",
    ["P1", "P2", "P3", "P4", "Cancelling", "Renewed", "Churned"],
    default=["P1", "P2", "Cancelling"],
)
show_category = st.sidebar.multiselect(
    "Category",
    sorted(df["category"].dropna().unique()),
    default=list(df["category"].dropna().unique()),
)
show_am = st.sidebar.multiselect(
    "Account Manager",
    sorted(df["account_manager"].dropna().unique()),
    default=list(df["account_manager"].dropna().unique()),
)

filtered = df[
    (df["tier_or_status"].isin(show_tier))
    & (df["category"].isin(show_category) | df["category"].isna())
    & (df["account_manager"].isin(show_am) | df["account_manager"].isna())
]

# ------------------------------------------------------------------
# Main table
# ------------------------------------------------------------------
st.subheader(f"{len(filtered)} Suppliers Need Attention")

# Add profile link
filtered = filtered.copy()
filtered["profile_link"] = filtered["profile_id"].apply(
    lambda pid: f"https://admin.theperfectwedding.nl/profiles/edit/{pid}"
)

# Color by tier
def color_tier(val):
    colors = {"P1": "color: red", "P2": "color: orange", "P3": "color: gold", "P4": "color: green",
              "Cancelling": "color: red"}
    return colors.get(val, "")

# Select display columns
display_cols = [
    "tier_or_status",
    "profile_name",
    "account_manager",
    "category",
    "plan_value",
    "days_until_renewal",
    "churn_probability",
    "risk_factors",
    "recommended_action",
    "profile_link",
]

st.dataframe(
    filtered[display_cols].style.map(color_tier, subset=["tier_or_status"]),
    column_config={
        "tier_or_status": st.column_config.TextColumn("Tier", width="small"),
        "profile_name": st.column_config.TextColumn("Supplier", width="medium"),
        "account_manager": st.column_config.TextColumn("AM", width="small"),
        "category": st.column_config.TextColumn("Category", width="small"),
        "plan_value": st.column_config.NumberColumn("Value", format="€%d", width="small"),
        "days_until_renewal": st.column_config.NumberColumn("Renewal (days)", width="small"),
        "churn_probability": st.column_config.ProgressColumn(
            "Risk", format="%.0%%", min_value=0, max_value=1, width="small"
        ),
        "risk_factors": st.column_config.TextColumn("Why at risk?", width="large"),
        "recommended_action": st.column_config.TextColumn("Action", width="medium"),
        "profile_link": st.column_config.LinkColumn("Open", display_text="Open", width="small"),
    },
    use_container_width=True,
    hide_index=True,
)

# ------------------------------------------------------------------
# CSV export
# ------------------------------------------------------------------
csv = filtered[display_cols].to_csv(index=False).encode("utf-8")
st.download_button(
    "Download list",
    csv,
    f"at_risk_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
    mime="text/csv",
)

# ------------------------------------------------------------------
# Recent actions
# ------------------------------------------------------------------
if not actions.empty:
    st.subheader("Recent Actions (Last 7 Days)")
    st.dataframe(
        actions[["profile_id", "action_type", "action_detail", "executed", "action_date"]],
        use_container_width=True,
        hide_index=True,
    )

# ------------------------------------------------------------------
# Refresh
# ------------------------------------------------------------------
if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()
    st.rerun()
