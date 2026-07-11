import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AssigneeOption,
  checkApiHealth,
  DashboardSummary,
  getAssignees,
  getDashboardSummary,
  getSweepJob,
  getTicket,
  getTickets,
  getWorkbenchStatus,
  resetWorkbench,
  startSweepJob,
  TicketDetail,
  TicketListItem,
  transitionTicket
} from "./api/client";
import { AnalyticsPanel } from "./components/AnalyticsPanel";
import { BusinessImpactPanel } from "./components/BusinessImpact";
import { StatusChangeOptions } from "./components/dialogs";
import { TicketDetailPanel } from "./components/TicketDetailPanel";
import { TicketTable } from "./components/TicketTable";
import { SweepProgress, WorkbenchControls } from "./components/WorkbenchControls";
import {
  CREATED_RANGE_OPTIONS,
  CreatedRangePreset,
  matchesCreatedDateRange,
  OPERATOR_STATUS_LABELS,
  OPERATOR_STATUS_ORDER,
  ticketDescription,
  urgencyRank
} from "./lib/format";

const PAGE_SIZE = 50;
const SWEEP_POLL_INTERVAL_MS = 1200;

const STATUS_FILTER_OPTIONS = [
  { value: "all", label: "All" },
  ...OPERATOR_STATUS_ORDER.map((status) => ({
    value: status,
    label: OPERATOR_STATUS_LABELS[status]
  }))
];

function readTicketIdFromHash(): string | null {
  const hash = window.location.hash;
  const match = hash.match(/^#\/tickets\/(.+)$/);
  return match ? decodeURIComponent(match[1]) : null;
}

function pushTicketHash(ticketId: string | null) {
  const newHash = ticketId ? `#/tickets/${encodeURIComponent(ticketId)}` : "";
  if (window.location.hash !== newHash) {
    window.history.pushState(null, "", newHash || window.location.pathname);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export default function App() {
  const [tickets, setTickets] = useState<TicketListItem[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [selectedTicket, setSelectedTicket] = useState<TicketDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [message, setMessage] = useState("Loading tickets...");
  const [statusFilter, setStatusFilter] = useState("all");
  const [assigneeFilter, setAssigneeFilter] = useState("all");
  const [companyFilter, setCompanyFilter] = useState<string | null>(null);
  const [sourceSystemFilter, setSourceSystemFilter] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [createdRangePreset, setCreatedRangePreset] = useState<CreatedRangePreset>("all");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [workbenchBusy, setWorkbenchBusy] = useState(false);
  const [seedCount, setSeedCount] = useState(50);
  const [sweepBatchSize, setSweepBatchSize] = useState(5);
  const [queuePending, setQueuePending] = useState(0);
  const [sweepProgress, setSweepProgress] = useState<SweepProgress>(null);
  const [assignees, setAssignees] = useState<AssigneeOption[]>([]);

  async function loadWorkbenchStatus() {
    try {
      const status = await getWorkbenchStatus();
      setQueuePending(status.staging_counts.new ?? 0);
    } catch {
      setQueuePending(0);
    }
  }

  async function refresh(preferredTicketId?: string | null) {
    try {
      const [ticketRows, dashboard] = await Promise.all([getTickets(), getDashboardSummary()]);
      setTickets(ticketRows);
      setSummary(dashboard);
      setApiOnline(true);

      const ticketId =
        preferredTicketId && ticketRows.some((ticket) => ticket.ticket_id === preferredTicketId)
          ? preferredTicketId
          : ticketRows[0]?.ticket_id;

      if (ticketId) {
        try {
          setSelectedTicket(await getTicket(ticketId));
          pushTicketHash(ticketId);
        } catch {
          setSelectedTicket(null);
          pushTicketHash(null);
        }
      } else {
        setSelectedTicket(null);
        pushTicketHash(null);
      }

      setMessage(
        ticketRows.length
          ? `${ticketRows.length} ticket${ticketRows.length === 1 ? "" : "s"} loaded.`
          : "No tickets in the queue. Failed documents will appear here after agent processing."
      );
      await loadWorkbenchStatus();
    } catch (error) {
      setApiOnline(false);
      setMessage(error instanceof Error ? error.message : "Failed to load tickets.");
    }
  }

  const selectTicket = useCallback(async (ticketId: string) => {
    setDetailLoading(true);
    try {
      const detail = await getTicket(ticketId);
      setSelectedTicket(detail);
      pushTicketHash(ticketId);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? `Failed to load ticket: ${error.message}`
          : "Failed to load ticket details."
      );
    } finally {
      setDetailLoading(false);
    }
  }, []);

  function handleTicketUpdate(updated: TicketDetail) {
    const description = ticketDescription(updated);
    setSelectedTicket(updated);
    setTickets((current) =>
      current.map((row) =>
        row.ticket_id === updated.ticket_id
          ? {
              ...row,
              title: updated.title,
              description,
              operator_status: updated.operator_status,
              assignee: updated.assignee,
              workflow_status: updated.workflow_run.status ?? row.workflow_status,
              updated_at: updated.updated_at,
              agent_summary: updated.agent_summary ?? null
            }
          : row
      )
    );
    // Value/SLA metrics change with status transitions — refresh the dashboard.
    getDashboardSummary().then(setSummary).catch(() => undefined);
  }

  async function handleStatusChange(
    ticketId: string,
    status: string,
    options?: StatusChangeOptions
  ) {
    try {
      const updated = await transitionTicket(ticketId, status, options);
      handleTicketUpdate(updated);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to update ticket status.");
      throw error;
    }
  }

  async function handleBulkStatusChange(ticketIds: string[], status: string) {
    let failures = 0;
    for (const ticketId of ticketIds) {
      try {
        const updated = await transitionTicket(ticketId, status);
        handleTicketUpdate(updated);
      } catch {
        failures += 1;
      }
    }
    const moved = ticketIds.length - failures;
    setMessage(
      failures
        ? `Moved ${moved} ticket${moved === 1 ? "" : "s"}; ${failures} failed.`
        : `Moved ${moved} ticket${moved === 1 ? "" : "s"} to ${OPERATOR_STATUS_LABELS[status] ?? status}.`
    );
  }

  async function handleResetWorkbench() {
    setWorkbenchBusy(true);
    try {
      const result = await resetWorkbench(seedCount);
      setSummary(result.dashboard);
      setQueuePending(result.staging_counts.new ?? 0);
      await refresh(null);
      setMessage(`Workbench reset. ${seedCount} documents seeded for agent processing.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to reset workbench.");
    } finally {
      setWorkbenchBusy(false);
    }
  }

  async function handleSweepWorkbench() {
    setWorkbenchBusy(true);
    setMessage(`Processing up to ${sweepBatchSize} documents with agents…`);
    try {
      let job = await startSweepJob(sweepBatchSize);
      setSweepProgress({ processed: job.processed ?? 0, total: job.total ?? sweepBatchSize });
      while (job.status === "running") {
        await sleep(SWEEP_POLL_INTERVAL_MS);
        job = await getSweepJob(job.job_id);
        setSweepProgress({ processed: job.processed ?? 0, total: job.total ?? sweepBatchSize });
      }

      if (job.status === "failed") {
        setMessage(job.error ? `Agent processing failed: ${job.error}` : "Agent processing failed.");
        return;
      }

      if (job.dashboard) setSummary(job.dashboard);
      setQueuePending(job.staging_counts?.new ?? 0);
      await refresh(null);
      const created = job.created_tickets ?? 0;
      const failed = job.errors?.length ?? 0;
      setMessage(
        failed
          ? `Created ${created} ticket${created === 1 ? "" : "s"}. ${failed} document${failed === 1 ? "" : "s"} failed.`
          : `Created ${created} ticket${created === 1 ? "" : "s"} from the staging queue.`
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Agent processing failed.");
    } finally {
      setSweepProgress(null);
      setWorkbenchBusy(false);
    }
  }

  useEffect(() => {
    function onHashChange() {
      const ticketId = readTicketIdFromHash();
      if (ticketId && ticketId !== selectedTicket?.ticket_id) {
        void selectTicket(ticketId);
      }
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [selectedTicket?.ticket_id, selectTicket]);

  useEffect(() => {
    async function boot() {
      try {
        await checkApiHealth();
        setApiOnline(true);
        const hashTicketId = readTicketIdFromHash();
        await refresh(hashTicketId);
        try {
          const options = await getAssignees();
          setAssignees(options.assignees);
        } catch {
          setAssignees([]);
        }
      } catch {
        setApiOnline(false);
        setMessage("Unable to connect to the workbench service. Please try again shortly.");
      }
    }
    boot().catch(() => undefined);
  }, []);

  const operatorStatusCounts = useMemo(() => {
    const counts = Object.fromEntries(OPERATOR_STATUS_ORDER.map((status) => [status, 0]));
    for (const ticket of tickets) {
      const key = ticket.operator_status;
      counts[key] = (counts[key] ?? 0) + 1;
    }
    return counts;
  }, [tickets]);
  const assigneeOptions = useMemo(
    () => ["all", ...Array.from(new Set(tickets.map((ticket) => ticket.assignee))).sort()],
    [tickets]
  );
  const filteredTickets = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return [...tickets]
      .filter((ticket) => statusFilter === "all" || ticket.operator_status === statusFilter)
      .filter((ticket) => assigneeFilter === "all" || ticket.assignee === assigneeFilter)
      .filter((ticket) => companyFilter === null || ticket.company_code === companyFilter)
      .filter(
        (ticket) => sourceSystemFilter === null || ticket.source_system === sourceSystemFilter
      )
      .filter((ticket) =>
        matchesCreatedDateRange(ticket, createdRangePreset, createdFrom, createdTo)
      )
      .filter((ticket) => {
        if (!query) return true;
        return (
          ticket.ticket_id.toLowerCase().includes(query) ||
          ticket.source_document_ref.toLowerCase().includes(query) ||
          ticketDescription(ticket).toLowerCase().includes(query) ||
          ticket.assignee.toLowerCase().includes(query) ||
          (ticket.agent_summary ?? "").toLowerCase().includes(query) ||
          (ticket.reason_code ?? "").toLowerCase().includes(query)
        );
      })
      .sort((left, right) => urgencyRank(right) - urgencyRank(left));
  }, [
    tickets,
    statusFilter,
    assigneeFilter,
    companyFilter,
    sourceSystemFilter,
    searchQuery,
    createdRangePreset,
    createdFrom,
    createdTo
  ]);

  const visibleTickets = filteredTickets.slice(0, visibleCount);
  const hasMore = filteredTickets.length > visibleCount;

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [
    statusFilter,
    assigneeFilter,
    companyFilter,
    sourceSystemFilter,
    searchQuery,
    createdRangePreset,
    createdFrom,
    createdTo
  ]);

  return (
    <main className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Autonomous Finance Operations</p>
          <h1>Agentic Document Error Resolution Workbench</h1>
          <p>Scaling document failure resolution through autonomous agents</p>
        </div>
      </header>

      <p className={`status-message ${apiOnline === false ? "status-error" : ""}`}>{message}</p>

      <WorkbenchControls
        queuePending={queuePending}
        seedCount={seedCount}
        sweepBatchSize={sweepBatchSize}
        busy={workbenchBusy}
        apiOnline={apiOnline}
        sweepProgress={sweepProgress}
        onSeedCountChange={setSeedCount}
        onSweepBatchSizeChange={setSweepBatchSize}
        onReset={() => void handleResetWorkbench()}
        onSweep={() => void handleSweepWorkbench()}
        onRefresh={() => void refresh(selectedTicket?.ticket_id ?? null)}
      />

      <BusinessImpactPanel
        summary={summary}
        companyFilter={companyFilter}
        sourceSystemFilter={sourceSystemFilter}
        onCompanySelect={(code) =>
          setCompanyFilter((current) => (current === code ? null : code))
        }
        onSourceSystemSelect={(system) =>
          setSourceSystemFilter((current) => (current === system ? null : system))
        }
      />

      <section className="layout">
        <AnalyticsPanel
          summary={summary}
          ticketCount={tickets.length}
          operatorStatusCounts={operatorStatusCounts}
        />
        <div className="panel wide detail-panel">
          <TicketDetailPanel
            ticket={selectedTicket}
            loading={detailLoading}
            assignees={assignees}
            onTicketUpdate={handleTicketUpdate}
            onStatusChange={handleStatusChange}
            onWorkflowAction={setMessage}
          />
        </div>
      </section>

      <section className="layout search-tickets-layout">
        <div className="panel wide search-tickets-panel">
          <div className="panel-header">
            <h2>Search Tickets</h2>
            <span>
              {visibleTickets.length}
              {filteredTickets.length > visibleTickets.length
                ? ` of ${filteredTickets.length}`
                : ""}{" "}
              shown
            </span>
          </div>
          <div className="search-bar">
            <label htmlFor="ticket-search" className="sr-only">
              Search tickets
            </label>
            <input
              id="ticket-search"
              type="search"
              placeholder="Search by ticket ID, document ID, description, assignee..."
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />
          </div>
          <div className="filters-row">
            <label htmlFor="filter-status">
              Status
              <select
                id="filter-status"
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value)}
              >
                {STATUS_FILTER_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label htmlFor="filter-assignee">
              Assignee
              <select
                id="filter-assignee"
                value={assigneeFilter}
                onChange={(event) => setAssigneeFilter(event.target.value)}
              >
                {assigneeOptions.map((option) => (
                  <option key={option} value={option}>
                    {option === "all" ? "All assignees" : option}
                  </option>
                ))}
              </select>
            </label>
            <label htmlFor="filter-created">
              Created
              <select
                id="filter-created"
                value={createdRangePreset}
                onChange={(event) =>
                  setCreatedRangePreset(event.target.value as CreatedRangePreset)
                }
              >
                {CREATED_RANGE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {createdRangePreset === "custom" ? (
            <div className="filters-row filters-row-custom">
              <label htmlFor="filter-from">
                From
                <input
                  id="filter-from"
                  type="date"
                  value={createdFrom}
                  onChange={(event) => setCreatedFrom(event.target.value)}
                />
              </label>
              <label htmlFor="filter-to">
                To
                <input
                  id="filter-to"
                  type="date"
                  value={createdTo}
                  min={createdFrom || undefined}
                  onChange={(event) => setCreatedTo(event.target.value)}
                />
              </label>
            </div>
          ) : null}
          {companyFilter || sourceSystemFilter ? (
            <div className="active-filters">
              {companyFilter ? (
                <button
                  className="filter-chip"
                  onClick={() => setCompanyFilter(null)}
                  type="button"
                >
                  Company {companyFilter} ✕
                </button>
              ) : null}
              {sourceSystemFilter ? (
                <button
                  className="filter-chip"
                  onClick={() => setSourceSystemFilter(null)}
                  type="button"
                >
                  {sourceSystemFilter} ✕
                </button>
              ) : null}
            </div>
          ) : null}
          <TicketTable
            tickets={visibleTickets}
            selectedTicketId={selectedTicket?.ticket_id ?? null}
            onSelect={selectTicket}
            onStatusChange={handleStatusChange}
            onBulkStatusChange={handleBulkStatusChange}
          />
          {hasMore ? (
            <div className="load-more">
              <button
                className="secondary"
                onClick={() => setVisibleCount((n) => n + PAGE_SIZE)}
                type="button"
              >
                Show more ({filteredTickets.length - visibleCount} remaining)
              </button>
            </div>
          ) : null}
        </div>
      </section>
    </main>
  );
}
