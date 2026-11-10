"use client";

import { useState, useMemo } from "react";
import { SupplierStats } from "@/lib/bigquery";
import { StatCard } from "@/components/StatCard";
import { SearchBar } from "@/components/SearchBar";
import { SupplierTable } from "@/components/SupplierTable";
import { effectiveTier } from "@/lib/status";

// "None" = decided suppliers (cancelling, renewed, churned): no risk tier.
const TIER_OPTIONS = ["P1", "P2", "P3", "P4", "None"];

export function OverviewClient({ suppliers }: { suppliers: SupplierStats[] }) {
  const [search, setSearch] = useState("");
  const [tierFilter, setTierFilter] = useState<string[]>(TIER_OPTIONS);
  const [amFilter, setAmFilter] = useState<string[]>([]);

  const ams = useMemo(
    () =>
      Array.from(
        new Set(suppliers.map((s) => s.account_manager).filter(Boolean))
      ) as string[],
    [suppliers]
  );

  const filtered = useMemo(() => {
    return suppliers.filter((s) => {
      const matchesSearch =
        !search ||
        s.profile_name.toLowerCase().includes(search.toLowerCase()) ||
        s.profile_id.includes(search);
      const matchesTier = tierFilter.includes(effectiveTier(s) ?? "None");
      const matchesAm =
        amFilter.length === 0 || amFilter.includes(s.account_manager ?? "");
      return matchesSearch && matchesTier && matchesAm;
    });
  }, [suppliers, search, tierFilter, amFilter]);

  const p1 = suppliers.filter((s) => effectiveTier(s) === "P1");
  const p2 = suppliers.filter((s) => effectiveTier(s) === "P2");
  const cancelling = suppliers.filter((s) => s.renewal_status === "will_churn");
  const revenueAtRisk =
    p1.reduce((sum, s) => sum + (s.plan_value ?? 0), 0) +
    p2.reduce((sum, s) => sum + (s.plan_value ?? 0), 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Supplier Overview</h1>
        <p className="text-sm text-gray-500 mt-1">
          Churn is one signal. See the full health picture.
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-4">
        <StatCard label="Suppliers" value={suppliers.length} />
        <StatCard
          label="Revenue at Risk"
          value={`€${revenueAtRisk.toLocaleString("nl-NL")}`}
          color="red"
        />
        <StatCard label="P1 (Urgent)" value={p1.length} color="red" />
        <StatCard label="P2 (High)" value={p2.length} color="orange" />
        <StatCard
          label="Cancellation scheduled"
          value={cancelling.length}
          subtext="Gratis booked: save or exit interview"
        />
      </div>

      {/* Filters */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-4">
        <SearchBar onSearch={setSearch} />

        <div className="flex flex-wrap gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">
              Priority Tier
            </label>
            <div className="flex flex-wrap gap-2">
              {TIER_OPTIONS.map((tier) => (
                <button
                  key={tier}
                  onClick={() =>
                    setTierFilter((prev) =>
                      prev.includes(tier)
                        ? prev.filter((t) => t !== tier)
                        : [...prev, tier]
                    )
                  }
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                    tierFilter.includes(tier)
                      ? tier === "P1"
                        ? "bg-red-50 text-red-700 border-red-200"
                        : tier === "P2"
                        ? "bg-orange-50 text-orange-700 border-orange-200"
                        : tier === "P3"
                        ? "bg-yellow-50 text-yellow-700 border-yellow-200"
                        : tier === "P4"
                        ? "bg-green-50 text-green-700 border-green-200"
                        : "bg-gray-100 text-gray-700 border-gray-300"
                      : "bg-white text-gray-500 border-gray-200 hover:bg-gray-50"
                  }`}
                >
                  {tier === "None" ? "No tier (decided)" : tier}
                </button>
              ))}
            </div>
          </div>

          {ams.length > 0 && (
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">
                Account Manager
              </label>
              <select
                className="block w-48 rounded-lg border border-gray-300 text-sm focus:border-blue-500 focus:ring-blue-500 px-2 py-1.5"
                value={amFilter[0] ?? ""}
                onChange={(e) =>
                  setAmFilter(e.target.value ? [e.target.value] : [])
                }
              >
                <option value="">All</option>
                {ams.map((am) => (
                  <option key={am} value={am}>
                    {am}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      </div>

      {/* Table */}
      <div>
        <h2 className="text-sm font-semibold text-gray-700 mb-3">
          {filtered.length} suppliers
        </h2>
        <SupplierTable suppliers={filtered} />
      </div>
    </div>
  );
}
