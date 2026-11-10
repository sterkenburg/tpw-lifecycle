import { getLatestStats } from "@/lib/bigquery";
import { SupplierTable } from "@/components/SupplierTable";
import { StatCard } from "@/components/StatCard";
import { effectiveTier, knownDays } from "@/lib/status";

export const dynamic = "force-dynamic";

export default async function ActionsPage() {
  const suppliers = await getLatestStats();

  // Queues only hold suppliers whose outcome can still change: undecided
  // (active) and scheduled cancellations. Renewed and churned are excluded.
  const open = suppliers.filter(
    (s) => s.renewal_status === "active" || s.renewal_status === "will_churn"
  );
  const p1 = suppliers.filter((s) => effectiveTier(s) === "P1");
  const cancelling = suppliers
    .filter((s) => s.renewal_status === "will_churn")
    .sort((a, b) => (a.days_until_renewal ?? 0) - (b.days_until_renewal ?? 0));
  const renewalSoon = open.filter(
    (s) =>
      s.renewal_status === "active" &&
      s.days_until_renewal != null &&
      s.days_until_renewal < 60
  );
  const noLeads = open.filter((s) => {
    const days = knownDays(s.days_since_last_lead);
    return days == null || days > 45;
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Action Queue</h1>
        <p className="text-sm text-gray-500 mt-1">
          What needs attention today.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="P1: Urgent Calls"
          value={p1.length}
          subtext="Call within 24h"
          color="red"
        />
        <StatCard
          label="Cancellation scheduled"
          value={cancelling.length}
          subtext="Save call, else exit interview"
          color="red"
        />
        <StatCard
          label="Renewal < 60d, undecided"
          value={renewalSoon.length}
          subtext="Prepare renewal outreach"
          color="orange"
        />
        <StatCard
          label="No Leads 45d+"
          value={noLeads.length}
          subtext="Re-engagement needed"
          color="blue"
        />
      </div>

      <div className="space-y-6">
        <section>
          <h2 className="text-lg font-semibold text-gray-900 mb-3">
            P1: Urgent ({p1.length})
          </h2>
          <SupplierTable suppliers={p1} />
        </section>

        <section>
          <h2 className="text-lg font-semibold text-gray-900 mb-3">
            Cancellation Scheduled ({cancelling.length})
          </h2>
          <p className="text-sm text-gray-500 -mt-2 mb-3">
            A switch to Gratis is booked. Soonest plan end first.
          </p>
          <SupplierTable suppliers={cancelling} />
        </section>

        <section>
          <h2 className="text-lg font-semibold text-gray-900 mb-3">
            Renewals Approaching ({renewalSoon.length})
          </h2>
          <SupplierTable suppliers={renewalSoon} />
        </section>

        <section>
          <h2 className="text-lg font-semibold text-gray-900 mb-3">
            No Leads in 45+ Days ({noLeads.length})
          </h2>
          <SupplierTable suppliers={noLeads} />
        </section>
      </div>
    </div>
  );
}
