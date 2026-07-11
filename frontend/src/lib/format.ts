import type { TicketListItem } from "../api/client";

export const OPERATOR_STATUS_LABELS: Record<string, string> = {
  assigned: "Assigned",
  in_progress: "In Progress",
  resolved: "Resolved",
  blocked: "Blocked"
};

export const OPERATOR_STATUS_ORDER = ["assigned", "in_progress", "resolved", "blocked"];

// Internal journey stages — used for timeline only, not operator-facing status.
export const STAGE_LABELS: Record<string, string> = {
  received: "Received",
  diagnosed: "Diagnosed",
  assigned: "Assigned",
  in_progress: "In Progress",
  resolved: "Resolved"
};

export const RESOLUTION_BENCHMARK_DAYS = 3;

export const WORKFLOW_STATUS_LABELS: Record<string, string> = {
  needs_approval: "Approval required",
  blocked: "Policy blocked",
  reprocessed: "Reprocessed",
  diagnosed: "Diagnosed",
  new: "New"
};

export function humanize(value: string): string {
  return value
    .replace(/_/g, " ")
    .split(" ")
    .map((word: string) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatJourneyTimestamp(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit"
  });
}

export function formatTicketDate(iso: string | Date): string {
  const date = iso instanceof Date ? iso : new Date(iso);
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric"
  });
}

export function formatDocumentValue(amount: number, currency: string): string {
  return `${amount.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })} ${currency}`;
}

const USD_COMPACT = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1
});

export function formatUsd(amount: number): string {
  return USD_COMPACT.format(amount);
}

export function formatPercent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

export function splitIntoSentences(text: string): string[] {
  return text
    .replace(/\s+/g, " ")
    .trim()
    .split(/(?<=[.!?])\s+/)
    .map((part) => part.trim())
    .filter(Boolean);
}

export function ticketDescription(
  ticket: Pick<
    TicketListItem,
    "description" | "title" | "created_at" | "source_system" | "reason_description" | "reason_code"
  >
): string {
  if (ticket.description?.trim()) return ticket.description;
  if (ticket.title?.trim()) return ticket.title;
  const date = new Date(ticket.created_at);
  const dd = String(date.getDate()).padStart(2, "0");
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const yy = String(date.getFullYear()).slice(-2);
  const brief = (ticket.reason_description ?? ticket.reason_code).replace(/\s+/g, "-");
  return `${dd}${mm}${yy}-${ticket.source_system}-${brief}`;
}

export function daysOpen(ticket: {
  days_open?: number;
  created_at?: string;
  updated_at?: string;
}): number {
  if (typeof ticket.days_open === "number") return ticket.days_open;
  if (ticket.created_at && ticket.updated_at) {
    return (Date.parse(ticket.updated_at) - Date.parse(ticket.created_at)) / 86_400_000;
  }
  return 0;
}

export function formatDaysOpen(ticket: {
  days_open?: number;
  created_at?: string;
  updated_at?: string;
}): string {
  return String(Math.round(daysOpen(ticket)));
}

export function ticketDueDate(createdAt: string): Date {
  return new Date(Date.parse(createdAt) + RESOLUTION_BENCHMARK_DAYS * 86_400_000);
}

export function urgencyRank(ticket: TicketListItem): number {
  const open = daysOpen(ticket);
  const status = ticket.operator_status;
  if (status === "blocked") return 500 + open;
  if (status === "in_progress") return 300 + open;
  if (status === "assigned") return 200 + open;
  return open;
}

export const CREATED_RANGE_OPTIONS = [
  { value: "all", label: "Any time" },
  { value: "1", label: "Last 1 day" },
  { value: "3", label: "Last 3 days" },
  { value: "7", label: "Last 7 days" },
  { value: "28", label: "Last 28 days" },
  { value: "custom", label: "Custom range" }
] as const;

export type CreatedRangePreset = (typeof CREATED_RANGE_OPTIONS)[number]["value"];

export function matchesCreatedDateRange(
  ticket: TicketListItem,
  preset: CreatedRangePreset,
  from: string,
  to: string
): boolean {
  if (preset === "all") return true;
  if (!ticket.created_at) return true;

  const created = Date.parse(ticket.created_at);
  if (Number.isNaN(created)) return true;

  const { fromMs, toMs } = resolveCreatedDateRange(preset, from, to);
  if (fromMs !== null && created < fromMs) return false;
  if (toMs !== null && created > toMs) return false;
  return true;
}

function resolveCreatedDateRange(
  preset: CreatedRangePreset,
  from: string,
  to: string
): { fromMs: number | null; toMs: number | null } {
  if (preset === "custom") {
    return {
      fromMs: from ? new Date(`${from}T00:00:00`).getTime() : null,
      toMs: to ? new Date(`${to}T23:59:59.999`).getTime() : null
    };
  }

  const days = Number(preset);
  const now = Date.now();
  return {
    fromMs: now - days * 86_400_000,
    toMs: now
  };
}
