"""Refit the churn model on past renewal decisions and write config/churn_model.json.

    python jobs/fit_churn_model.py                    # query BigQuery
    python jobs/fit_churn_model.py --csv-dir DIR      # offline, from exported CSVs
    python jobs/fit_churn_model.py --dry-run          # report only, keep the model file

Training rows: annual paid terms (301-400 days) whose renewal is decided (plan_end
at least 45 days ago) and whose 90-day input window is covered by the exposure
rollup (history from 2025-01). Inputs are measured at T = plan_end - 60 days.
Short terms are excluded: their plan_end is rewritten when a term is cut short,
so their labels and timing are unreliable.

Validation: fit on terms ending before the last VALIDATION_MONTHS months, score
those held-out months, compare with a prior-plans-only baseline. The shipped
model is then refitted on all rows. Review the printed report and the JSON diff
in a PR before merging; nothing changes in production until then.

CSV inputs (--csv-dir): terms.csv (profile_id, plan_start, plan_end, plan_value,
category, derived_prior, renewed), views.csv (profile_id, date, profile_views),
leads.csv (profile_id, event_date, n), site.csv (date, site_views).
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import pandas as pd

from signals import churn_model

HORIZON_DAYS = 60
RENEWAL_GRACE_DAYS = 45
EXPOSURE_START = pd.Timestamp("2025-01-01")
VALIDATION_MONTHS = 6
L2 = 1.0


# --- Data ----------------------------------------------------------------------

def _load_bigquery() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    from data import client, suppliers

    first_end = (EXPOSURE_START + pd.Timedelta(days=90 + HORIZON_DAYS)).date()
    terms = client.query(f"""
    WITH paid AS (
        SELECT CAST(profile_id AS STRING) AS profile_id, category, plan_name, plan_value,
               DATE(plan_start) AS plan_start, DATE(plan_end) AS plan_end
        FROM `{suppliers._BUSINESS_TABLE}`
        WHERE profile_id IS NOT NULL AND plan_name != 'Gratis'
    ),
    n AS (
        SELECT *,
            LEAD(plan_start) OVER (PARTITION BY profile_id ORDER BY plan_start, plan_end)
                AS next_paid_start,
            ROW_NUMBER() OVER (PARTITION BY profile_id ORDER BY plan_start, plan_end) - 1
                AS derived_prior
        FROM paid
    )
    SELECT *, COALESCE(DATE_DIFF(next_paid_start, plan_end, DAY) <= {RENEWAL_GRACE_DAYS}, FALSE)
              AS renewed
    FROM n
    WHERE plan_end BETWEEN '{first_end}'
                       AND DATE_SUB(CURRENT_DATE(), INTERVAL {RENEWAL_GRACE_DAYS} DAY)
    """)
    ids = ",".join(f"'{p}'" for p in terms["profile_id"].astype(str).unique())
    exposure = f"{client.PROJECT_ID}.{client.DATASET}.supplier_exposure_daily"
    views = client.query(f"""
    SELECT profile_id, date, profile_views FROM `{exposure}`
    WHERE date >= '{EXPOSURE_START.date()}' AND profile_views > 0 AND profile_id IN ({ids})
    """)
    site = client.query(f"""
    SELECT date, SUM(profile_views) AS site_views FROM `{exposure}`
    WHERE date >= '{EXPOSURE_START.date()}' GROUP BY date
    """)
    leads = client.query(f"""
    SELECT CAST(company_id AS STRING) AS profile_id, event_date, COUNT(*) AS n
    FROM `tpw-ga4-bigquery.ga4_dataform_output.generate_lead`
    WHERE event_date >= '{EXPOSURE_START.date()}' AND CAST(company_id AS STRING) IN ({ids})
    GROUP BY 1, 2
    UNION ALL
    SELECT CAST(profile_id AS STRING), event_date, COUNT(*)
    FROM `tpw-ga4-bigquery.ga4_dataform_output.show_phone`
    WHERE event_date >= '{EXPOSURE_START.date()}' AND CAST(profile_id AS STRING) IN ({ids})
    GROUP BY 1, 2
    """)
    return terms, views, leads, site


def _load_csv(directory: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    d = Path(directory)
    return (
        pd.read_csv(d / "terms.csv", dtype={"profile_id": str}),
        pd.read_csv(d / "views.csv", dtype={"profile_id": str}),
        pd.read_csv(d / "leads.csv", dtype={"profile_id": str}),
        pd.read_csv(d / "site.csv"),
    )


def training_frame(terms, views, leads, site) -> pd.DataFrame:
    """One row per eligible term with the raw model inputs at T = plan_end - 60d."""
    t = terms.copy()
    t["profile_id"] = t["profile_id"].astype(str)
    for col in ["plan_start", "plan_end"]:
        t[col] = pd.to_datetime(t[col])
    t["renewed"] = t["renewed"].astype(str).str.lower().isin(["true", "1"])
    t["term_days"] = (t["plan_end"] - t["plan_start"]).dt.days
    t["T"] = t["plan_end"] - pd.Timedelta(days=HORIZON_DAYS)
    t = t[t["term_days"].between(301, 400) & (t["T"] - pd.Timedelta(days=90) >= EXPOSURE_START)]

    views = views.assign(
        date=pd.to_datetime(views["date"]), profile_id=views["profile_id"].astype(str)
    )
    leads = leads.assign(
        date=pd.to_datetime(leads["event_date"]), profile_id=leads["profile_id"].astype(str)
    )
    site = (
        site.assign(date=pd.to_datetime(site["date"]))
        .set_index("date")["site_views"].sort_index()
    )
    by_views = {k: g.set_index("date")["profile_views"] for k, g in views.groupby("profile_id")}
    by_leads = {k: g.groupby("date")["n"].sum() for k, g in leads.groupby("profile_id")}

    def window_sum(series, as_of, days):
        if series is None:
            return 0.0
        start = as_of - pd.Timedelta(days=days)
        return float(series[(series.index > start) & (series.index <= as_of)].sum())

    def days_since(series, as_of):
        if series is None:
            return np.nan
        start = as_of - pd.Timedelta(days=90)
        hit = series[(series.index > start) & (series.index <= as_of) & (series > 0)]
        return float((as_of - hit.index.max()).days) if len(hit) else np.nan

    rows = []
    for r in t.itertuples():
        rows.append({
            "prior_paid_plans": r.derived_prior,
            "profile_views_60d": window_sum(by_views.get(r.profile_id), r.T, 60),
            "site_views_60d": window_sum(site, r.T, 60),
            "days_since_last_lead": days_since(by_leads.get(r.profile_id), r.T),
        })
    out = pd.concat([t.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    out["churn"] = (~out["renewed"]).astype(int)
    return out


# --- Metrics -------------------------------------------------------------------

def auc(y: np.ndarray, p: np.ndarray) -> float:
    """ROC AUC via the rank-sum formula (ties get average ranks)."""
    ranks = pd.Series(p).rank().to_numpy()
    pos = y == 1
    n_pos, n_neg = pos.sum(), (~pos).sum()
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-dir")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    raw = _load_csv(args.csv_dir) if args.csv_dir else _load_bigquery()
    df = training_frame(*raw)
    x, y = churn_model.features(df), df["churn"]
    cutoff = df["plan_end"].max() - pd.DateOffset(months=VALIDATION_MONTHS)
    train, test = df["plan_end"] <= cutoff, df["plan_end"] > cutoff

    print(f"Training rows: {len(df)} annual terms, plan_end {df['plan_end'].min().date()} .. "
          f"{df['plan_end'].max().date()}, non-renewal {y.mean():.1%}")
    print(f"Validation: fit on plan_end <= {cutoff.date()} (n={train.sum()}), "
          f"test on later terms (n={test.sum()}, non-renewal {y[test].mean():.1%})")

    b0, coef = churn_model.fit(x[train], y[train], l2=L2)
    model = {"intercept": b0, "coefficients": coef}
    p = churn_model.predict(df[test], model).to_numpy()
    prior_only = -df.loc[test, "prior_paid_plans"].to_numpy(dtype=float)
    test_auc, base_auc = auc(y[test].to_numpy(), p), auc(y[test].to_numpy(), prior_only)
    print(f"  held-out AUC {test_auc:.3f} (prior-plans-only baseline {base_auc:.3f}); "
          f"mean predicted {p.mean():.1%} vs actual {y[test].mean():.1%}")
    quint = pd.qcut(pd.Series(p), 5, labels=False, duplicates="drop")
    calib = pd.DataFrame({"pred": p, "actual": y[test].to_numpy()}).groupby(quint.to_numpy()).mean()
    print("  calibration by quintile:\n" + calib.round(3).T.to_string())

    b0_all, coef_all = churn_model.fit(x, y, l2=L2)
    print(f"Final model (all {len(df)} rows): intercept {b0_all:.3f}, "
          + ", ".join(f"{k} {v:+.3f}" for k, v in coef_all.items()))
    if args.dry_run:
        print("Dry run: model file not written.")
        return
    churn_model.save(b0_all, coef_all, {
        "version": date.today().isoformat(),
        "rows": int(len(df)),
        "plan_end_range": [str(df["plan_end"].min().date()), str(df["plan_end"].max().date())],
        "non_renewal_rate": round(float(y.mean()), 4),
        "l2": L2,
        "validation": {
            "train_plan_end_until": str(cutoff.date()),
            "test_rows": int(test.sum()),
            "test_auc": round(test_auc, 4),
            "prior_only_auc": round(base_auc, 4),
            "test_mean_predicted": round(float(p.mean()), 4),
            "test_actual_rate": round(float(y[test].mean()), 4),
        },
    })
    print(f"Wrote {churn_model.MODEL_PATH}")


if __name__ == "__main__":
    main()
