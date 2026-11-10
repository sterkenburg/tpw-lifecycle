"use client";

import { DECIDED_STATUS } from "@/lib/status";

const tierStyles: Record<string, string> = {
  P1: "bg-red-100 text-red-800 border-red-200",
  P2: "bg-orange-100 text-orange-800 border-orange-200",
  P3: "bg-yellow-100 text-yellow-800 border-yellow-200",
  P4: "bg-green-100 text-green-800 border-green-200",
};

export function TierBadge({ tier }: { tier: string | null }) {
  if (!tier) return null;
  const style = tierStyles[tier] ?? "bg-gray-100 text-gray-800 border-gray-200";
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${style}`}
    >
      {tier}
    </span>
  );
}

export function StatusBadge({
  status,
  size = "sm",
}: {
  status: string | null;
  size?: "sm" | "md";
}) {
  const spec = status ? DECIDED_STATUS[status] : undefined;
  if (!spec) return null;
  const sizing =
    size === "md"
      ? "text-xs px-2 py-1 rounded-full"
      : "text-[10px] px-1.5 py-0.5 rounded";
  return (
    <span className={`${sizing} font-medium whitespace-nowrap ${spec.className}`}>
      {spec.label}
    </span>
  );
}
