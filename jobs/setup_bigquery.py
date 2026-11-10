"""One-time setup: Create BigQuery tables for the lifecycle platform.

Run this after deploying to create the dataset and tables.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from google.cloud import bigquery

from data.client import PROJECT_ID, DATASET

client = bigquery.Client(project=PROJECT_ID)

# Ensure dataset exists
dataset_ref = f"{PROJECT_ID}.{DATASET}"
try:
    client.get_dataset(dataset_ref)
    print(f"Dataset {dataset_ref} already exists")
except Exception:
    client.create_dataset(bigquery.Dataset(dataset_ref))
    print(f"Created dataset {dataset_ref}")


# Table definitions
tables = {
    "supplier_stats_daily": """
        profile_id STRING,
        profile_name STRING,
        email STRING,
        phone STRING,
        category STRING,
        plan_name STRING,
        plan_value FLOAT64,
        plan_start DATE,
        plan_end DATE,
        days_until_renewal INT64,
        business_status STRING,
        account_manager STRING,
        profile_completion_pct FLOAT64,
        profile_views_60d INT64,
        profile_views_60_90d INT64,
        engagement_trend FLOAT64,
        leads_60d INT64,
        days_since_last_lead INT64,
        days_since_last_login INT64,
        estimated_value_30d FLOAT64,
        benchmark_views_top10pct INT64,
        benchmark_leads_top10pct INT64,
        contract_views_total INT64,
        contract_leads_total INT64,
        category_avg_views_60d FLOAT64,
        category_avg_leads_60d FLOAT64,
        renewal_status STRING,
        num_paid_plans_before INT64,
        churn_probability FLOAT64,
        priority_tier STRING,
        risk_factors STRING,
        recommended_action STRING,
        stats_date DATE
    """,
    "signals_daily": """
        profile_id STRING,
        churn_probability FLOAT64,
        priority_tier STRING,
        risk_factors STRING,
        recommended_action STRING,
        stats_date DATE
    """,
    "actions_log": """
        profile_id STRING,
        action_type STRING,
        action_detail STRING,
        executed BOOLEAN,
        action_date TIMESTAMP
    """,
    "outcomes": """
        profile_id STRING,
        plan_end DATE,
        intervention_date DATE,
        intervention_type STRING,
        assigned_to STRING,
        notes STRING,
        outcome STRING,
        revenue_preserved FLOAT64,
        created_at TIMESTAMP
    """,
    "email_log": """
        profile_id STRING,
        sent_at TIMESTAMP,
        email_type STRING,
        template STRING,
        opened BOOLEAN,
        clicked BOOLEAN,
        created_at TIMESTAMP
    """,
    "intervention_log": """
        profile_id STRING,
        intervention_date DATE,
        intervention_type STRING,
        churn_probability FLOAT64,
        recommended_action STRING,
        assigned_to STRING,
        created_at TIMESTAMP
    """,
}

for table_name, schema_sql in tables.items():
    full_table = f"{dataset_ref}.{table_name}"
    try:
        client.get_table(full_table)
        print(f"  Table {full_table} already exists")
    except Exception:
        schema = [bigquery.SchemaField(
            line.strip().split()[0],
            line.strip().split()[1].rstrip(","),
        ) for line in schema_sql.strip().split("\n") if line.strip()]
        table = bigquery.Table(full_table, schema=schema)
        client.create_table(table)
        print(f"  Created table {full_table}")

print("\nSetup complete.")
