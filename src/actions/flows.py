"""Email flow targeting — decides WHO gets WHICH email today.

This module is intentionally pure and side-effect free: given the daily
`signals` DataFrame and today's date, it returns the list of emails that
*should* go out. Actually sending them (and the dry-run guard) lives in
`emails.py`; logging/dedup lives in the daily pipeline. Keeping the decision
logic pure makes it unit-testable without touching BigQuery or SendGrid.

Three flows are supported in v1 (templates already exist for all three):
  - renewal_prep    : contract ends within `renewal_days` (value recap + offer)
  - re_engagement   : no lead for `no_lead_days`, and not a P1 (P1 = human call)
  - monthly_results : the 1st of the month, to every active supplier

Precedence (one email per supplier per run):
  renewal_prep > re_engagement > monthly_results
"""

import os
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
import yaml

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "settings.yaml")
with open(_CONFIG_PATH) as _f:
    _CONFIG = yaml.safe_load(_f)

_THRESHOLDS = _CONFIG.get("thresholds", {})
_EMAIL_CFG = _CONFIG.get("email", {})

NO_LEAD_DAYS = _THRESHOLDS.get("no_lead_days", 45)

# Booked-outcome statuses that must not get nurture emails: a scheduled Gratis
# downgrade is a save/exit conversation, and churned suppliers go to winback.
# (These used to be excluded implicitly because they were always P1; decided
# suppliers no longer carry a tier.)
_NO_NURTURE_STATUSES = {"will_churn", "lapsed"}
RENEWAL_DAYS = _THRESHOLDS.get("renewal_days", 60)
MONTHLY_SEND_DAY = _EMAIL_CFG.get("monthly_send_day", 1)
DEDUP_DAYS = _EMAIL_CFG.get(
    "dedup_days",
    {"monthly_results": 25, "re_engagement": 14, "renewal_prep": 21},
)

# Dutch month names for the monthly results subject line.
_MONTHS_NL = [
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
]


@dataclass
class EmailAction:
    """A single email that should be sent to one supplier."""

    profile_id: str
    flow: str  # "renewal_prep" | "re_engagement" | "monthly_results"
    email: str
    name: str
    subject: str
    payload: dict = field(default_factory=dict)


def is_emailable(value) -> bool:
    """True if the value looks like a usable email address."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    text = str(value).strip()
    return "@" in text and "." in text


def _int(value, default: int = 0) -> int:
    """Coerce a possibly-null/NaN cell to an int."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default: float = 0.0) -> float:
    """Coerce a possibly-null/NaN cell to a float."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _renewal_action(row) -> EmailAction | None:
    """Renewal prep: active contract ending within RENEWAL_DAYS."""
    if row.get("renewal_status") != "active":
        return None
    days = row.get("days_until_renewal")
    if days is None or pd.isna(days):
        return None
    days = int(days)
    if not (0 < days <= RENEWAL_DAYS):
        return None

    # Prefer full-contract totals for the yearly recap; fall back to 60d window.
    total_views = _int(row.get("contract_views_total")) or _int(row.get("profile_views_60d"))
    total_leads = _int(row.get("contract_leads_total")) or _int(row.get("leads_60d"))
    return EmailAction(
        profile_id=str(row["profile_id"]),
        flow="renewal_prep",
        email=str(row["email"]).strip(),
        name=row.get("profile_name") or "",
        subject=f"Je abonnement loopt af over {days} dagen",
        payload={
            "days_until_renewal": days,
            "plan_value": _float(row.get("plan_value")),
            "total_views": total_views,
            "total_leads": total_leads,
            "estimated_value": _float(row.get("estimated_value_30d")),
        },
    )


def _reengagement_action(row) -> EmailAction | None:
    """Re-engagement: no lead for NO_LEAD_DAYS, and not a P1 (P1 = human call).

    days_since_last_lead is NULL when there was no lead in the whole 90-day
    window; that qualifies (shown as "90+").
    """
    if row.get("priority_tier") == "P1" or row.get("renewal_status") in _NO_NURTURE_STATUSES:
        return None
    raw = row.get("days_since_last_lead")
    if raw is None or pd.isna(raw) or int(raw) >= 999:
        days: int | str = "90+"
    else:
        days = int(raw)
        if days < NO_LEAD_DAYS:
            return None
    return EmailAction(
        profile_id=str(row["profile_id"]),
        flow="re_engagement",
        email=str(row["email"]).strip(),
        name=row.get("profile_name") or "",
        subject="Je profiel is bekeken — hier is waarom er (nog) geen aanvraag is",
        payload={
            "category": row.get("category") or "",
            "days_since_lead": days,
        },
    )


def _monthly_action(row, month_name: str) -> EmailAction | None:
    """Monthly results: value recap for every active supplier (except P1).

    P1 suppliers are being actively worked by a human (CRM task), so they are
    not also sent the upbeat automated recap.
    """
    if row.get("priority_tier") == "P1" or row.get("renewal_status") in _NO_NURTURE_STATUSES:
        return None
    return EmailAction(
        profile_id=str(row["profile_id"]),
        flow="monthly_results",
        email=str(row["email"]).strip(),
        name=row.get("profile_name") or "",
        subject=f"Je ThePerfectWedding resultaten voor {month_name}",
        payload={
            "month": month_name,
            "profile_views": _int(row.get("profile_views_60d")),
            "leads": _int(row.get("leads_60d")),
            "estimated_value": _float(row.get("estimated_value_30d")),
            "benchmark_views": _int(row.get("benchmark_views_top10pct"), 250),
            "trend_pct": int(round(_float(row.get("engagement_trend")) * 100)),
        },
    )


def determine_email_actions(
    signals: pd.DataFrame,
    today: date,
    recently_sent: set[tuple[str, str]] | None = None,
) -> list[EmailAction]:
    """Decide which emails to send today.

    Args:
        signals: daily supplier stats + churn signals (one row per supplier).
        today: the date the pipeline is running for.
        recently_sent: set of (profile_id, flow) pairs already emailed inside
            that flow's dedup window — these are skipped.

    Returns:
        One EmailAction per eligible supplier (highest-precedence flow only).
    """
    recently_sent = recently_sent or set()
    is_monthly_day = today.day == MONTHLY_SEND_DAY

    # Dutch name of the month the recap covers (the previous month).
    prev_month_idx = (today.month - 2) % 12  # today.month-1 is current; -2 → previous, 0-indexed
    month_name = _MONTHS_NL[prev_month_idx]

    actions: list[EmailAction] = []
    for _, row in signals.iterrows():
        if not is_emailable(row.get("email")):
            continue

        # Highest-precedence eligible flow wins; one email per supplier per run.
        action = _renewal_action(row)
        if action is None:
            action = _reengagement_action(row)
        if action is None and is_monthly_day:
            action = _monthly_action(row, month_name)
        if action is None:
            continue

        if (action.profile_id, action.flow) in recently_sent:
            continue

        actions.append(action)

    return actions
