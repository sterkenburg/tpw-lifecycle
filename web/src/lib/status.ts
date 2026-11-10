import type { SupplierStats } from "@/lib/bigquery";

// renewal_status values that mean the outcome is already booked. Only undecided
// ("active") suppliers carry a P1-P4 risk tier.
export const DECIDED_STATUS: Record<
  string,
  { label: string; className: string }
> = {
  will_churn: {
    label: "Cancelling",
    className: "bg-red-100 text-red-700",
  },
  already_renewed: {
    label: "Renewed",
    className: "bg-green-100 text-green-700",
  },
  lapsed: {
    label: "Churned",
    className: "bg-gray-200 text-gray-700",
  },
};

export function isUndecided(s: Pick<SupplierStats, "renewal_status">): boolean {
  return (s.renewal_status ?? "active") === "active";
}

// Tier shown in the UI. Older snapshots also tiered decided suppliers; hide that
// so queues only ever contain suppliers whose outcome can still change.
export function effectiveTier(
  s: Pick<SupplierStats, "renewal_status" | "priority_tier">
): string | null {
  return isUndecided(s) ? s.priority_tier ?? null : null;
}

// Day counts are NULL when there was no event in the 90-day window. Older
// snapshots used 999 for the same thing.
export function knownDays(v: number | null | undefined): number | null {
  return v == null || v >= 999 ? null : v;
}
