"""FastAPI application.

Endpoints:
- POST /webhooks/lead — Instant lead notification trigger
- GET /suppliers/{id}/stats — Supplier value dashboard data
- GET /health — Health check
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from actions import notifications
from analytics import projected_value
from data import activity, client, leads, suppliers

app = FastAPI(title="TPW Lifecycle API")


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "service": "tpw-lifecycle"}


# ------------------------------------------------------------------
# Webhook: New Lead → Instant Notification
# ------------------------------------------------------------------
class LeadWebhook(BaseModel):
    profile_id: str
    couple_name: str
    event_date: str | None = None
    guest_count: int | None = None
    region: str | None = None
    message: str | None = None


@app.post("/webhooks/lead")
def webhook_lead(payload: LeadWebhook):
    """Receive a new lead event and send instant notification to supplier."""
    # Get supplier details
    supplier_df = suppliers.get_by_id(payload.profile_id)
    if supplier_df.empty:
        raise HTTPException(status_code=404, detail="Supplier not found")

    supplier = supplier_df.iloc[0]
    email = supplier.get("email")
    phone = supplier.get("phone")
    name = supplier.get("profile_name", "Leverancier")
    category = supplier.get("category", "")

    # Get recent stats for context
    lead_count = len(leads.get_by_supplier(payload.profile_id, days=30))
    # Rough view count — in production, read from supplier_stats_daily
    views = 0  # placeholder

    results = {}

    if email:
        results["email"] = notifications.send_instant_lead_email(
            to=email,
            supplier_name=name,
            couple_name=payload.couple_name,
            event_date=payload.event_date,
            guest_count=payload.guest_count,
            region=payload.region,
            message=payload.message,
            lead_number=lead_count,
            profile_views=views,
        )

    if phone:
        results["sms"] = notifications.send_instant_lead_sms(
            to=phone,
            couple_name=payload.couple_name,
            category=category,
        )

    return {
        "status": "sent",
        "profile_id": payload.profile_id,
        "notifications": results,
    }


# ------------------------------------------------------------------
# Supplier Stats (for external dashboard)
# ------------------------------------------------------------------
@app.get("/suppliers/{profile_id}/stats")
def get_supplier_stats(profile_id: str):
    """Get current stats for a supplier's value dashboard."""
    # Read latest stats from BigQuery
    sql = f"""
    SELECT *
    FROM `tpw-ga4-bigquery.retention.supplier_stats_daily`
    WHERE profile_id = '{profile_id}'
    ORDER BY stats_date DESC
    LIMIT 1
    """
    df = client.query(sql)
    if df.empty:
        raise HTTPException(status_code=404, detail="No stats found")

    row = df.iloc[0]

    # Calculate projected value
    est_value = projected_value.calculate(df)[0]

    return {
        "profile_id": profile_id,
        "profile_name": row.get("profile_name"),
        "profile_views_60d": int(row.get("profile_views_60d", 0)),
        "leads_60d": int(row.get("leads_60d", 0)),
        "estimated_value_30d": round(est_value, 2),
        "profile_completion_pct": round(row.get("profile_completion_pct", 0), 1),
        "engagement_trend": round(row.get("engagement_trend", 0), 2),
        "benchmark_views_top10pct": int(row.get("benchmark_views_top10pct", 250)),
        "benchmark_leads_top10pct": int(row.get("benchmark_leads_top10pct", 12)),
        "churn_probability": round(row.get("churn_probability", 0), 2),
        # NULL tier = decided supplier (scheduled cancellation, renewed, churned).
        "priority_tier": tier if isinstance(tier := row.get("priority_tier"), str) else None,
        "renewal_status": status if isinstance(status := row.get("renewal_status"), str) else None,
    }
