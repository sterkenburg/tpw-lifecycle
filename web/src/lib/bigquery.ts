import { BigQuery } from "@google-cloud/bigquery";

const PROJECT_ID = "tpw-ga4-bigquery";
const DATASET = "retention";

function getCredentials() {
  const json = process.env.GOOGLE_APPLICATION_CREDENTIALS_JSON;
  if (json) {
    try {
      return JSON.parse(Buffer.from(json, "base64").toString("utf-8"));
    } catch {
      return JSON.parse(json);
    }
  }
  return undefined;
}

const bq = new BigQuery({
  projectId: PROJECT_ID,
  credentials: getCredentials(),
});

function serializeValue(v: any): any {
  if (v == null) return null;
  // BigQuery DATE/DATETIME/TIMESTAMP objects
  if (typeof v === "object" && v.value !== undefined) {
    return v.value;
  }
  if (v instanceof Date) {
    return v.toISOString();
  }
  if (Array.isArray(v)) {
    return v.map(serializeValue);
  }
  if (typeof v === "object") {
    const out: any = {};
    for (const key of Object.keys(v)) {
      out[key] = serializeValue(v[key]);
    }
    return out;
  }
  return v;
}

async function query<T = any>(
  sql: string,
  params?: Record<string, string | number>
): Promise<T[]> {
  const [rows] = await bq.query({ query: sql, useLegacySql: false, params });
  return (rows as any[]).map((row) => serializeValue(row)) as T[];
}

// Optional history tables (e.g. intervention_log) may not exist in the dataset;
// a missing table must not take down the whole supplier page.
async function queryOptionalTable<T>(
  sql: string,
  params?: Record<string, string | number>
): Promise<T[]> {
  try {
    return await query<T>(sql, params);
  } catch (err: unknown) {
    const e = err as { code?: number; message?: string } | null;
    const notFound =
      e?.code === 404 || /Not found: Table/i.test(String(e?.message));
    if (notFound) return [];
    throw err;
  }
}

export type SupplierStats = {
  profile_id: string;
  profile_name: string;
  email: string | null;
  phone: string | null;
  category: string | null;
  plan_name: string | null;
  plan_value: number;
  plan_start: string | null;
  plan_end: string | null;
  days_until_renewal: number;
  business_status: string | null;
  account_manager: string | null;
  profile_completion_pct: number | null;
  profile_views_60d: number;
  profile_views_60_90d: number;
  engagement_trend: number;
  leads_60d: number;
  days_since_last_lead: number;
  days_since_last_login: number;
  estimated_value_30d: number | null;
  benchmark_views_top10pct: number | null;
  benchmark_leads_top10pct: number | null;
  contract_views_total: number;
  contract_leads_total: number;
  category_avg_views_60d: number | null;
  category_avg_leads_60d: number | null;
  renewal_status: string | null;
  churn_probability: number;
  priority_tier: string;
  risk_factors: string;
  recommended_action: string;
  stats_date: string;
};

export type ActionLog = {
  profile_id: string;
  action_type: string;
  action_detail: string;
  executed: boolean;
  action_date: string;
};

export type InterventionLog = {
  profile_id: string;
  intervention_date: string;
  intervention_type: string;
  churn_probability: number;
  recommended_action: string;
  assigned_to: string;
  created_at: string;
};

export async function getLatestStats(): Promise<SupplierStats[]> {
  const sql = `
    SELECT *
    FROM \`${PROJECT_ID}.${DATASET}.supplier_stats_daily\`
    WHERE stats_date = (
      SELECT MAX(stats_date) FROM \`${PROJECT_ID}.${DATASET}.supplier_stats_daily\`
    )
    ORDER BY churn_probability DESC
  `;
  return query<SupplierStats>(sql);
}

export async function getSupplierById(
  profileId: string
): Promise<SupplierStats | null> {
  const sql = `
    SELECT *
    FROM \`${PROJECT_ID}.${DATASET}.supplier_stats_daily\`
    WHERE profile_id = @profileId
    ORDER BY stats_date DESC
    LIMIT 1
  `;
  const rows = await query<SupplierStats>(sql, { profileId });
  return rows[0] ?? null;
}

export async function getSupplierHistory(
  profileId: string,
  limit: number = 30
): Promise<SupplierStats[]> {
  const sql = `
    SELECT *
    FROM \`${PROJECT_ID}.${DATASET}.supplier_stats_daily\`
    WHERE profile_id = @profileId
    ORDER BY stats_date DESC
    LIMIT @limit
  `;
  return query<SupplierStats>(sql, { profileId, limit });
}

export async function getActionsForSupplier(
  profileId: string
): Promise<ActionLog[]> {
  const sql = `
    SELECT *
    FROM \`${PROJECT_ID}.${DATASET}.actions_log\`
    WHERE profile_id = @profileId
    ORDER BY action_date DESC
  `;
  return queryOptionalTable<ActionLog>(sql, { profileId });
}

export async function getInterventionsForSupplier(
  profileId: string
): Promise<InterventionLog[]> {
  const sql = `
    SELECT *
    FROM \`${PROJECT_ID}.${DATASET}.intervention_log\`
    WHERE profile_id = @profileId
    ORDER BY created_at DESC
  `;
  return queryOptionalTable<InterventionLog>(sql, { profileId });
}

export async function getTodayActionCount(): Promise<number> {
  const sql = `
    SELECT COUNT(*) as cnt
    FROM \`${PROJECT_ID}.${DATASET}.actions_log\`
    WHERE DATE(action_date) = CURRENT_DATE()
  `;
  const rows = await query<{ cnt: number }>(sql);
  return rows[0]?.cnt ?? 0;
}
