import Link from "next/link";
import {
  getSupplierById,
  getActionsForSupplier,
  getInterventionsForSupplier,
} from "@/lib/bigquery";
import { StatusBadge, TierBadge } from "@/components/TierBadge";
import { effectiveTier, knownDays } from "@/lib/status";
import { ActionHistory } from "@/components/ActionHistory";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

export default async function SupplierPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const supplier = await getSupplierById(id);

  if (!supplier) {
    notFound();
  }

  const [actions, interventions] = await Promise.all([
    getActionsForSupplier(id),
    getInterventionsForSupplier(id),
  ]);

  const riskScore = Math.round((supplier.churn_probability ?? 0) * 100);
  const tier = effectiveTier(supplier);
  const daysSinceView = knownDays(supplier.days_since_last_login);
  const daysSinceLead = knownDays(supplier.days_since_last_lead);
  const priorPlans = supplier.num_paid_plans_before;

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link href="/" className="hover:text-gray-900">
          Overview
        </Link>
        <span>/</span>
        <span className="text-gray-900 font-medium">
          {supplier.profile_name}
        </span>
      </div>

      {/* Header Card */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-gray-900">
                {supplier.profile_name}
              </h1>
              <TierBadge tier={tier} />
              <StatusBadge status={supplier.renewal_status} size="md" />
            </div>
            <p className="text-sm text-gray-500 mt-1">
              {supplier.category} · {supplier.account_manager ?? "No AM"}
            </p>
          </div>
          <a
            href={`https://admin.theperfectwedding.nl/profiles/edit/${supplier.profile_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-blue-600 hover:text-blue-800 font-medium"
          >
            Open in Admin →
          </a>
        </div>
      </div>

      {/* Health Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500">Plan Value</p>
          <p className="mt-1 text-xl font-bold text-gray-900">
            €{supplier.plan_value?.toLocaleString("nl-NL") ?? 0}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500">Renewal</p>
          <p
            className={`mt-1 text-xl font-bold ${
              supplier.days_until_renewal < 30
                ? "text-red-600"
                : "text-gray-900"
            }`}
          >
            {supplier.days_until_renewal == null
              ? "Unknown"
              : supplier.days_until_renewal < 0
              ? `Ended ${-supplier.days_until_renewal} days ago`
              : `${supplier.days_until_renewal} days`}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500">Profile Views (60d)</p>
          <p className="mt-1 text-xl font-bold text-gray-900">
            {supplier.profile_views_60d}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500">Leads (60d)</p>
          <p className="mt-1 text-xl font-bold text-gray-900">
            {supplier.leads_60d}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500">Profile Views (contract)</p>
          <p className="mt-1 text-xl font-bold text-gray-900">
            {supplier.contract_views_total}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500">Leads (contract)</p>
          <p className="mt-1 text-xl font-bold text-gray-900">
            {supplier.contract_leads_total}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500">Category Avg Views (60d)</p>
          <p className="mt-1 text-xl font-bold text-gray-900">
            {supplier.category_avg_views_60d?.toFixed(0) ?? "—"}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-xs font-medium text-gray-500">Category Avg Leads (60d)</p>
          <p className="mt-1 text-xl font-bold text-gray-900">
            {supplier.category_avg_leads_60d?.toFixed(1) ?? "—"}
          </p>
        </div>
      </div>

      {/* Risk + Signals */}
      <div className="grid md:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">
            Risk Score
          </h2>
          <div className="flex items-center gap-4">
            <div className="relative w-24 h-24">
              <svg className="w-full h-full" viewBox="0 0 36 36">
                <path
                  className="text-gray-100"
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="3"
                />
                <path
                  className={
                    tier === "P1"
                      ? "text-red-500"
                      : tier === "P2"
                      ? "text-orange-500"
                      : tier === "P3"
                      ? "text-yellow-500"
                      : tier === "P4"
                      ? "text-green-500"
                      : "text-gray-400"
                  }
                  strokeDasharray={`${riskScore}, 100`}
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="3"
                />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-lg font-bold text-gray-900">
                  {riskScore}
                </span>
              </div>
            </div>
            <div>
              <p className="text-sm font-medium text-gray-900">
                {tier ? `${tier}: ` : ""}
                {supplier.risk_factors !== "Stable"
                  ? supplier.risk_factors
                  : "No major risk factors"}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                {supplier.recommended_action}
              </p>
              <p className="text-xs text-gray-400 mt-2">
                Relative risk score out of 100, not a probability.
                {tier ? "" : " No tier: the renewal outcome is already booked."}
              </p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">
            Activity Signals
          </h2>
          <div className="space-y-3">
            <SignalRow
              label="Previous paid plans"
              value={priorPlans ?? "Unknown"}
              warning={priorPlans == null || priorPlans === 0}
            />
            <SignalRow
              label="Days since last profile view"
              value={daysSinceView ?? "No views in 90 days"}
              warning={daysSinceView == null || daysSinceView > 30}
            />
            <SignalRow
              label="Days since last lead"
              value={daysSinceLead ?? "None in 90 days"}
              warning={daysSinceLead == null || daysSinceLead > 60}
            />
            <SignalRow
              label="Views trend (30d vs prior 30d)"
              value={`${(supplier.engagement_trend * 100).toFixed(0)}%`}
              warning={supplier.engagement_trend < -0.5}
            />
          </div>
        </div>
      </div>

      {/* Action History */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-sm font-semibold text-gray-900 mb-4">
          Action History
        </h2>
        <ActionHistory actions={actions} interventions={interventions} />
      </div>
    </div>
  );
}

function SignalRow({
  label,
  value,
  warning,
}: {
  label: string;
  value: string | number;
  warning: boolean;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-gray-600">{label}</span>
      <span
        className={`text-sm font-medium ${
          warning ? "text-red-600" : "text-gray-900"
        }`}
      >
        {value}
      </span>
    </div>
  );
}
