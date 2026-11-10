"""Daily lifecycle pipeline. THE main job.

Runs at 7 AM via Cloud Scheduler.
1. Load data
2. Calculate supplier stats
3. Calculate signals (churn, engagement, renewal)
4. Determine actions (LEGACY — gated OFF, see below)
5. Save everything to BigQuery
6. Slack summary (aggregate counts only — never names suppliers)
7. Rebuild the `outcomes` table (renewal labels for ended terms; best-effort)

The per-supplier emitters in stage 4 (P1 CRM tasks + the deprecated SendGrid
email flows) PREDATE the holdout system and used to log crm_task intents for
stage1 CONTROL suppliers (doc 29 §5). They are gated behind
`legacy_actions.enabled` (settings.yaml, default false): dispatch is owned by
the directives system (WS-D), which enforces the holdout structurally. If the
flag is temporarily re-enabled, stage 4 excludes every supplier enrolled in any
experiment (both arms) via cohort.enrolled_ids().
"""

import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pandas as pd
import yaml

from actions import crm, emails, flows, slack
from analytics import outcomes, projected_value, supplier_stats
from data import activity, client, exposure, leads, suppliers
from signals import churn_scorer, cohort, engagement

# The GA4 view source normally lags ~2 days. Beyond this, the view inputs would
# describe a past period while the snapshot is dated today: stop before writing
# so the dashboard keeps the last good snapshot and the failed run is visible.
MAX_VIEW_DATA_AGE_DAYS = 5
VIEW_WINDOW_DAYS = 90   # activity.get_views_last_90d window; every day must have data

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"
with open(_CONFIG_PATH) as _f:
    _LEGACY_ON = yaml.safe_load(_f).get("legacy_actions", {}).get("enabled", False)


def check_view_freshness(df_activity: pd.DataFrame, today: date) -> pd.Timestamp:
    """Latest view date in the feed; raise if it is too old or has missing days.

    The feed covers every profile, so each day of the 90-day window normally has
    thousands of rows; a day without any row is a gap in the rollup.
    """
    latest = df_activity["event_date"].max() if not df_activity.empty else pd.NaT
    age = (pd.Timestamp(today) - latest).days if pd.notna(latest) else None
    if age is None or age > MAX_VIEW_DATA_AGE_DAYS:
        raise RuntimeError(
            f"Profile-view data is stale (latest {latest}, age {age} days, "
            f"limit {MAX_VIEW_DATA_AGE_DAYS}). Not publishing a snapshot; check the GA4 "
            "monthly_profile_stats source and the exposure refresh."
        )
    expected = pd.date_range(latest - pd.Timedelta(days=VIEW_WINDOW_DAYS - 1), latest, freq="D")
    present = set(pd.to_datetime(df_activity["event_date"]).dt.normalize())
    missing = [d.date() for d in expected if d not in present]
    if missing:
        raise RuntimeError(
            f"Profile-view data has {len(missing)} missing day(s) in the "
            f"{VIEW_WINDOW_DAYS}-day window (first: {missing[0]}). Not publishing; "
            "backfill with jobs/build_exposure_daily.py <start> <end>."
        )
    return latest


def run():
    print(f"\n{'=' * 60}")
    print(f"TPW Lifecycle Pipeline — {datetime.now().isoformat()}")
    print(f"{'=' * 60}\n")

    # ------------------------------------------------------------------
    # 1. Load data
    # ------------------------------------------------------------------
    print("[1/7] Loading data...")
    # Refresh the profile-view rollup first. The window starts 3 days before the
    # newest date already present (the GA4 source lags ~2 days), so days missed
    # during an outage are rebuilt once the source catches up. Atomic (one
    # transaction): a failure leaves the previous rows intact, and the check
    # below decides whether the feed is complete and recent enough to publish.
    try:
        start = exposure.refresh_start(date.today(), exposure.latest_date())
        refreshed = exposure.build(start.isoformat(), date.today().isoformat())
        print(f"        Exposure rollup refreshed from {start}: {refreshed:,} rows")
    except Exception as e:
        print(f"        Exposure refresh failed (non-fatal): {e}")
    df_suppliers = suppliers.get_current()
    df_activity = activity.get_views_last_90d()
    df_leads = leads.get_last_90d()
    df_contract_activity = activity.get_contract_views(df_suppliers)
    df_contract_leads = leads.get_contract_period_leads(df_suppliers)
    print(f"        Suppliers: {len(df_suppliers)}")
    latest_view_date = check_view_freshness(df_activity, date.today())
    print(f"        View rows (supplier-days): {len(df_activity)}, "
          f"latest data date: {latest_view_date.date()}")
    print(f"        Leads: {len(df_leads)}")
    print(f"        Contract views: {len(df_contract_activity)}")
    print(f"        Contract leads: {len(df_contract_leads)}")

    # ------------------------------------------------------------------
    # 2. Calculate supplier stats
    # ------------------------------------------------------------------
    print("[2/7] Calculating supplier stats...")
    stats = supplier_stats.calculate(
        df_suppliers,
        df_activity,
        df_leads,
        contract_activity=df_contract_activity,
        contract_leads=df_contract_leads,
    )
    stats = projected_value.add_benchmarks(stats)
    stats["estimated_value_30d"] = projected_value.calculate(stats)
    print(f"        Stats rows: {len(stats)}")

    # ------------------------------------------------------------------
    # 3. Calculate signals
    # ------------------------------------------------------------------
    print("[3/7] Calculating signals...")
    signals = churn_scorer.calculate(stats)
    print(f"        P1: {(signals['priority_tier'] == 'P1').sum()}")
    print(f"        P2: {(signals['priority_tier'] == 'P2').sum()}")
    print(f"        P3: {(signals['priority_tier'] == 'P3').sum()}")
    print(f"        P4: {(signals['priority_tier'] == 'P4').sum()}")
    decided = signals["priority_tier"].isna()
    print(f"        No tier (decided): {decided.sum()} "
          f"{signals.loc[decided, 'renewal_status'].value_counts().to_dict()}")

    declining = engagement.detect_decline(signals)
    inactive = engagement.detect_no_activity(signals)
    print(f"        Declining engagement: {len(declining)}")
    print(f"        No activity 30d: {len(inactive)}")

    # ------------------------------------------------------------------
    # 4. Determine actions
    # ------------------------------------------------------------------
    print("[4/7] Determining actions...")
    actions_taken = []

    if not _LEGACY_ON:
        print("        Legacy per-supplier emitters OFF (legacy_actions.enabled=false).")
        print("        Dispatch is owned by the directives system (WS-D, holdout-")
        print("        enforced); these pre-holdout flows logged crm_task intents for")
        print("        control suppliers (doc 29 §5). Stats/signals/Slack still run.")
    else:
        # Holdout guard: legacy emitters never touch an enrolled supplier (either
        # arm) — control must stay untouched, and treatment must not receive
        # uncontrolled extra touches outside its experiment's lever set.
        enrolled = cohort.enrolled_ids()
        pool = signals[~signals["profile_id"].astype(str).isin(enrolled)]
        if len(pool) < len(signals):
            print(f"        Holdout guard: {len(signals) - len(pool)} enrolled "
                  f"suppliers excluded from legacy actions")

        # P1 → CRM tasks
        for _, row in pool[pool["priority_tier"] == "P1"].iterrows():
            created = crm.create_retention_task(
                profile_id=row["profile_id"],
                profile_name=row["profile_name"],
                category=row["category"],
                plan_value=row["plan_value"],
                plan_end=row["plan_end"],
                churn_probability=row["churn_probability"],
                risk_factors=row["risk_factors"],
                account_manager=row.get("account_manager", ""),
            )
            actions_taken.append(
                {
                    "profile_id": row["profile_id"],
                    "action_type": "crm_task",
                    "action_detail": "P1 retention task",
                    "executed": created,
                    "action_date": pd.Timestamp.now(),
                }
            )
        print(f"        CRM tasks created: {sum(a['executed'] for a in actions_taken)}")

        # Email flows → renewal prep, re-engagement, monthly results.
        # Sends are gated by emails.is_dry_run() (default ON): while dry-run, this
        # computes and logs who *would* be emailed but calls no provider. Going live
        # = set SENDGRID_API_KEY and EMAIL_DRY_RUN=false. Email addresses come from
        # the optional source configured in sources.supplier_email_* (none yet, so
        # email_actions is empty until that feed exists).
        emailable = pool["email"].apply(flows.is_emailable).sum() if "email" in pool else 0
        recently_sent = emails.recent_sends()
        email_actions = flows.determine_email_actions(pool, date.today(), recently_sent)
        flow_counts = Counter(a.flow for a in email_actions)

        sent_actions = []
        for a in email_actions:
            ok = emails.send(a)
            actions_taken.append(
                {
                    "profile_id": a.profile_id,
                    "action_type": f"email:{a.flow}",
                    "action_detail": a.subject,
                    "executed": ok,
                    "action_date": pd.Timestamp.now(),
                }
            )
            if ok:
                sent_actions.append(a)
        emails.log_sends(sent_actions)

        mode = "DRY-RUN (nothing sent)" if emails.is_dry_run() else f"sent {len(sent_actions)}"
        print(f"        Emailable suppliers: {emailable}/{len(pool)}")
        print(f"        Email actions: {len(email_actions)} {dict(flow_counts)} — {mode}")

    # ------------------------------------------------------------------
    # 5. Save to BigQuery
    # ------------------------------------------------------------------
    print("[5/7] Saving to BigQuery...")

    # Supplier stats — align columns to BigQuery schema
    stats_cols = [
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
        "profile_completion_pct",
        "profile_views_60d",
        "profile_views_60_90d",
        "engagement_trend",
        "leads_60d",
        "days_since_last_lead",
        "days_since_last_login",
        "estimated_value_30d",
        "contract_views_total",
        "contract_leads_total",
        "category_avg_views_60d",
        "category_avg_leads_60d",
        "renewal_status",
        "num_paid_plans_before",
        "benchmark_views_top10pct",
        "benchmark_leads_top10pct",
        "churn_probability",
        "priority_tier",
        "risk_factors",
        "recommended_action",
        "stats_date",
    ]
    stats_df = signals.copy()
    for col in stats_cols:
        if col not in stats_df.columns:
            stats_df[col] = None

    # Additive schema change (idempotent): columns added after the table was
    # created must exist before an append, or the load job rejects the frame.
    client.execute(
        f"ALTER TABLE `{client.PROJECT_ID}.{client.DATASET}.supplier_stats_daily` "
        "ADD COLUMN IF NOT EXISTS num_paid_plans_before INT64"
    )

    # Delete today's rows first to prevent duplicates on re-runs
    client.delete_today("supplier_stats_daily", date_column="stats_date")
    client.write(stats_df[stats_cols], "supplier_stats_daily", if_exists="append")
    print("        → supplier_stats_daily")

    # Signals (subset)
    signals_cols = [
        "profile_id",
        "churn_probability",
        "priority_tier",
        "risk_factors",
        "recommended_action",
        "stats_date",
    ]
    client.delete_today("signals_daily", date_column="stats_date")
    client.write(signals[signals_cols], "signals_daily", if_exists="append")
    print("        → signals_daily")

    # Actions log
    if actions_taken:
        df_actions = pd.DataFrame(actions_taken)
        client.delete_today("actions_log", date_column="DATE(action_date)")
        client.write(df_actions, "actions_log", if_exists="append")
        print("        → actions_log")

    # ------------------------------------------------------------------
    # 6. Slack summary
    # ------------------------------------------------------------------
    print("[6/7] Posting Slack summary...")
    # Aggregate reporting over ALL suppliers (counts only, never names) — kept
    # independent of the gated legacy emitters above.
    p1_mask = signals["priority_tier"] == "P1"
    p2_mask = signals["priority_tier"] == "P2"
    revenue_at_risk = signals[p1_mask]["plan_value"].sum() + signals[p2_mask]["plan_value"].sum()
    slack.send_summary(
        total_suppliers=len(signals),
        p1_count=int(p1_mask.sum()),
        p2_count=int(p2_mask.sum()),
        p3_count=(signals["priority_tier"] == "P3").sum(),
        revenue_at_risk=revenue_at_risk,
    )
    print("        → Slack sent")

    # ------------------------------------------------------------------
    # 7. Rebuild outcomes (best-effort: the snapshot above is already saved)
    # ------------------------------------------------------------------
    print("[7/7] Rebuilding outcomes...")
    try:
        df_outcomes = outcomes.build()
        print(f"        → outcomes ({len(df_outcomes)} terms)")
    except Exception as e:
        print(f"        outcomes rebuild failed (non-fatal): {e}")

    print(f"\n{'=' * 60}")
    print("Pipeline complete.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    run()
