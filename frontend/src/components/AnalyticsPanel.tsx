import { DashboardSummary } from "../api/client";
import {
  humanize,
  OPERATOR_STATUS_LABELS,
  OPERATOR_STATUS_ORDER,
  RESOLUTION_BENCHMARK_DAYS,
  STAGE_LABELS
} from "../lib/format";

export function Metric({
  label,
  value,
  hint,
  valueTone
}: {
  label: string;
  value: string | number;
  hint?: string;
  valueTone?: "good" | "bad";
}) {
  return (
    <article className="metric-card">
      <span>{label}</span>
      <strong className={valueTone ? `metric-${valueTone}` : undefined}>{value}</strong>
      {hint ? <small className="metric-hint">{hint}</small> : null}
    </article>
  );
}

function StatusGrid({ data }: { data: Record<string, number> }) {
  const entries = OPERATOR_STATUS_ORDER.map((status) => [status, data[status] ?? 0] as const);
  if (!entries.some(([, value]) => value > 0)) return null;
  return (
    <div className="breakdown">
      <h3>By Status</h3>
      <div className="status-grid">
        {entries.map(([label, value]) => (
          <article className={`status-card status-${label}`} key={label}>
            <span>{OPERATOR_STATUS_LABELS[label] ?? humanize(label)}</span>
            <strong>{value}</strong>
          </article>
        ))}
      </div>
    </div>
  );
}

export function Breakdown({
  title,
  data,
  humanize: humanizeLabel = false,
  formatValue,
  activeKey,
  onSelect
}: {
  title: string;
  data: Record<string, number>;
  humanize?: boolean;
  formatValue?: (value: number) => string;
  activeKey?: string | null;
  onSelect?: (key: string) => void;
}) {
  const entries = Object.entries(data);
  if (!entries.length) return <p className="empty">No data yet.</p>;
  const sorted = [...entries].sort((a, b) => b[1] - a[1]).slice(0, 8);
  const max = Math.max(...sorted.map(([, value]) => value));
  return (
    <div className="breakdown">
      <h3>{title}</h3>
      {sorted.map(([label, value], index) => {
        const row = (
          <>
            <span>{humanizeLabel ? humanize(label) : label}</span>
            <div>
              <i className={`rank-${index + 1}`} style={{ width: `${(value / max) * 100}%` }} />
            </div>
            <strong>{formatValue ? formatValue(value) : value}</strong>
          </>
        );
        if (!onSelect) {
          return (
            <div className="bar-row" key={label}>
              {row}
            </div>
          );
        }
        return (
          <button
            className={`bar-row bar-row-button ${activeKey === label ? "bar-row-active" : ""}`}
            key={label}
            onClick={() => onSelect(label)}
            title={`Filter tickets by ${label}`}
            type="button"
          >
            {row}
          </button>
        );
      })}
    </div>
  );
}

function StagePerformance({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data);
  if (!entries.length) return null;
  const sorted = [...entries].sort((a, b) => b[1] - a[1]).slice(0, 5);
  return (
    <div className="breakdown">
      <h3>Average Stage Time (Days)</h3>
      {sorted.map(([stage, value], index) => (
        <div className="bar-row" key={stage}>
          <span>{STAGE_LABELS[stage] ?? humanize(stage)}</span>
          <div>
            <i
              className={`rank-${index + 1}`}
              style={{ width: `${(value / sorted[0][1]) * 100}%` }}
            />
          </div>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}

export function AnalyticsPanel({
  summary,
  ticketCount,
  operatorStatusCounts
}: {
  summary: DashboardSummary | null;
  ticketCount: number;
  operatorStatusCounts: Record<string, number>;
}) {
  const avgResolutionDays = summary?.average_resolution_days ?? 0;
  const hasTickets = (summary?.total_tickets ?? ticketCount) > 0;

  return (
    <div className="panel analytics-panel">
      <div className="panel-header">
        <h2>Analytics</h2>
      </div>
      <div className="analytics-overview">
        <Metric label="Total Tickets" value={summary?.total_tickets ?? ticketCount} />
        <Metric label="Active Tickets" value={summary?.open_tickets ?? 0} />
        <Metric
          label="Avg Resolution Time (Days)"
          value={avgResolutionDays}
          valueTone={
            hasTickets
              ? avgResolutionDays < RESOLUTION_BENCHMARK_DAYS
                ? "good"
                : "bad"
              : undefined
          }
        />
      </div>
      <StatusGrid data={operatorStatusCounts} />
      <Breakdown title="Tickets by Owner" data={summary?.tickets_by_owner_role ?? {}} humanize />
      <StagePerformance data={summary?.average_stage_days ?? {}} />
    </div>
  );
}
