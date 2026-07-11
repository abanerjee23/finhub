import { DashboardSummary } from "../api/client";
import { formatPercent, formatUsd } from "../lib/format";
import { Breakdown, Metric } from "./AnalyticsPanel";

const AGING_ORDER = ["0-1d", "1-3d", "3-7d", "7d+"];

export function BusinessImpactPanel({
  summary,
  companyFilter,
  sourceSystemFilter,
  onCompanySelect,
  onSourceSystemSelect
}: {
  summary: DashboardSummary | null;
  companyFilter: string | null;
  sourceSystemFilter: string | null;
  onCompanySelect: (companyCode: string) => void;
  onSourceSystemSelect: (sourceSystem: string) => void;
}) {
  if (!summary || summary.total_tickets === 0) return null;

  const slaBreached = summary.sla_breached_count;

  return (
    <section className="panel business-impact-panel">
      <div className="panel-header">
        <h2>Business Impact</h2>
        <span>USD-equivalent at fixed demo FX rates</span>
      </div>
      <div className="impact-cards">
        <Metric
          label="Open Value at Risk"
          value={formatUsd(summary.open_value_usd)}
          hint={`${summary.open_tickets} open ticket${summary.open_tickets === 1 ? "" : "s"}`}
          valueTone={summary.open_value_usd > 0 ? "bad" : "good"}
        />
        <Metric
          label="Total Value Failed"
          value={formatUsd(summary.total_value_usd)}
          hint={`${summary.total_tickets} document${summary.total_tickets === 1 ? "" : "s"}`}
        />
        <Metric
          label="SLA Breached"
          value={slaBreached}
          hint={slaBreached ? `${formatUsd(summary.sla_breached_value_usd)} at risk` : "All within SLA"}
          valueTone={slaBreached ? "bad" : "good"}
        />
        <Metric
          label="Automation Rate"
          value={formatPercent(summary.automation_rate)}
          hint="Documents reprocessed without human action"
          valueTone={summary.automation_rate >= 0.4 ? "good" : undefined}
        />
      </div>
      <div className="impact-breakdowns">
        <Breakdown
          title="Open Value by Company Code"
          data={summary.open_value_by_company_code}
          formatValue={formatUsd}
          activeKey={companyFilter}
          onSelect={onCompanySelect}
        />
        <Breakdown
          title="Open Value by Source System"
          data={summary.open_value_by_source_system}
          formatValue={formatUsd}
          activeKey={sourceSystemFilter}
          onSelect={onSourceSystemSelect}
        />
        <div className="breakdown">
          <h3>Open Ticket Aging</h3>
          <div className="aging-grid">
            {AGING_ORDER.map((label) => {
              const bucket = summary.aging_buckets[label] ?? { count: 0, value_usd: 0 };
              return (
                <article className="aging-card" key={label}>
                  <span>{label}</span>
                  <strong>{bucket.count}</strong>
                  <small>{formatUsd(bucket.value_usd)}</small>
                </article>
              );
            })}
          </div>
          <h3>Value by Currency</h3>
          <div className="currency-chips">
            {Object.entries(summary.value_by_currency).map(([currency, value]) => (
              <span className="currency-chip" key={currency}>
                {currency}{" "}
                {value.toLocaleString(undefined, {
                  maximumFractionDigits: 0
                })}
              </span>
            ))}
          </div>
        </div>
      </div>
      <p className="impact-footnote">
        Click a company code or source system to filter the ticket list. FX rates:{" "}
        {Object.entries(summary.fx_rates_to_usd)
          .map(([currency, rate]) => `${currency} ${rate}`)
          .join(" · ")}
      </p>
    </section>
  );
}
