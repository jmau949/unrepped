// Listing status as a buyer reads it; `delisted` reads as "Off market".
// Shared by the Tracker cards and the Watchlist rows so the two never drift.
export const STATUS_LABEL: Record<string, string> = {
  active: "For sale",
  pending: "Pending",
  sold: "Sold",
  delisted: "Off market",
};

export const STATUS_PILL: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-700",
  pending: "bg-orange-100 text-orange-700",
  sold: "bg-slate-800 text-white",
  delisted: "bg-slate-200 text-slate-600",
};

export const statusPillClass = (status: string) => STATUS_PILL[status] ?? "bg-slate-100 text-slate-600";
export const statusLabel = (status: string) => STATUS_LABEL[status] ?? status;
