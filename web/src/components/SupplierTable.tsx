"use client";

import Link from "next/link";
import { TierBadge } from "./TierBadge";
import { SupplierStats } from "@/lib/bigquery";

export function SupplierTable({ suppliers }: { suppliers: SupplierStats[] }) {
  if (suppliers.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        No suppliers match your filters.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white shadow-sm">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Tier
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Supplier
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
              AM
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Category
            </th>
            <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Value
            </th>
            <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Renewal
            </th>
            <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Views (60d)
            </th>
            <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Leads (60d)
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider min-w-[18rem] lg:min-w-[24rem]">
              Risk
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {suppliers.map((s) => (
            <tr
              key={s.profile_id}
              className="hover:bg-gray-50 transition-colors"
            >
              <td className="px-4 py-3 whitespace-nowrap">
                <div className="flex items-center gap-2">
                  <TierBadge tier={s.priority_tier} />
                  {s.renewal_status === "already_renewed" && (
                    <span className="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded font-medium">
                      Renewed
                    </span>
                  )}
                  {s.renewal_status === "will_churn" && (
                    <span className="text-[10px] bg-red-100 text-red-700 px-1.5 py-0.5 rounded font-medium">
                      Will churn
                    </span>
                  )}
                </div>
              </td>
              <td className="px-4 py-3">
                <Link
                  href={`/suppliers/${s.profile_id}`}
                  className="text-sm font-medium text-blue-600 hover:text-blue-800 hover:underline"
                >
                  {s.profile_name}
                </Link>
              </td>
              <td className="px-4 py-3 text-sm text-gray-600 whitespace-nowrap">
                {s.account_manager ?? "—"}
              </td>
              <td className="px-4 py-3 text-sm text-gray-600 whitespace-nowrap">
                {s.category ?? "—"}
              </td>
              <td className="px-4 py-3 text-sm text-gray-900 text-right whitespace-nowrap">
                €{s.plan_value?.toLocaleString("nl-NL") ?? 0}
              </td>
              <td className="px-4 py-3 text-sm text-right whitespace-nowrap">
                {s.days_until_renewal != null ? (
                  <span
                    className={
                      s.days_until_renewal < 30
                        ? "text-red-600 font-medium"
                        : "text-gray-600"
                    }
                  >
                    {s.days_until_renewal}d
                  </span>
                ) : (
                  "—"
                )}
              </td>
              <td className="px-4 py-3 text-sm text-gray-600 text-right whitespace-nowrap">
                {s.profile_views_60d}
              </td>
              <td className="px-4 py-3 text-sm text-gray-600 text-right whitespace-nowrap">
                {s.leads_60d}
              </td>
              <td className="px-4 py-3 text-sm text-gray-600 min-w-[18rem] lg:min-w-[24rem]">
                {s.risk_factors}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
