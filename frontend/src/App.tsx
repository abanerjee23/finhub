import { ChangeEvent, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  checkApiHealth,
  DashboardSummary,
  getDashboardSummary,
  getTicket,
  getTickets,
  getWorkbenchStatus,
  postTicketComment,
  patchTicketDescription,
  resetWorkbench,
  sweepWorkbench,
  transitionTicket,
  uploadTicketAttachment,
  ticketAttachmentUrl,
  TicketDetail,
  TicketListItem
} from "./api/client";

const OPERATOR_STATUS_LABELS: Record<string, string> = {
  assigned: "Assigned",
  in_progress: "In Progress",
  resolved: "Resolved",
  blocked: "Blocked"
};

const OPERATOR_STATUS_ORDER = ["assigned", "in_progress", "resolved", "blocked"];

const STATUS_FILTER_OPTIONS = [
  { value: "all", label: "All" },
  ...OPERATOR_STATUS_ORDER.map((status) => ({
    value: status,
    label: OPERATOR_STATUS_LABELS[status]
  }))
];

// Internal journey stages — used for timeline only, not operator-facing status.
const STAGE_LABELS: Record<string, string> = {
  received: "Received",
  diagnosed: "Diagnosed",
  assigned: "Assigned",
  in_progress: "In Progress",
  resolved: "Resolved"
};
const RESOLUTION_BENCHMARK_DAYS = 3;
const RESOLUTION_PROOF_ACCEPT =
  "image/jpeg,image/png,image/gif,image/webp,application/pdf,text/plain,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel";
const MAX_RESOLUTION_PROOF_FILES = 5;
const PAGE_SIZE = 50;
const CREATED_RANGE_OPTIONS = [
  { value: "all", label: "Any time" },
  { value: "1", label: "Last 1 day" },
  { value: "3", label: "Last 3 days" },
  { value: "7", label: "Last 7 days" },
  { value: "28", label: "Last 28 days" },
  { value: "custom", label: "Custom range" }
] as const;

type CreatedRangePreset = (typeof CREATED_RANGE_OPTIONS)[number]["value"];

type StatusChangeOptions = {
  note?: string;
  attachmentIds?: string[];
};

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

export default function App() {
  const [tickets, setTickets] = useState<TicketListItem[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [selectedTicket, setSelectedTicket] = useState<TicketDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [message, setMessage] = useState("Loading tickets...");
  const [statusFilter, setStatusFilter] = useState("all");
  const [assigneeFilter, setAssigneeFilter] = useState("all");
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
      const [ticketRows, dashboard] = await Promise.all([
        getTickets(),
        getDashboardSummary()
      ]);
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
      setMessage(
        error instanceof Error ? error.message : "Failed to load tickets."
      );
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
              updated_at: updated.updated_at,
              agent_summary: updated.agent_summary ?? null
            }
          : row
      )
    );
  }

  async function handleStatusChange(ticketId: string, status: string, options?: StatusChangeOptions) {
    try {
      const updated = await transitionTicket(ticketId, status, options);
      handleTicketUpdate(updated);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Failed to update ticket status."
      );
      throw error;
    }
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
      const result = await sweepWorkbench(sweepBatchSize);
      setSummary(result.dashboard);
      setQueuePending(result.staging_counts.new ?? 0);
      await refresh(null);
      if (result.errors.length) {
        setMessage(
          `Created ${result.created_tickets} ticket${result.created_tickets === 1 ? "" : "s"}. ${result.errors.length} document${result.errors.length === 1 ? "" : "s"} failed.`
        );
      } else {
        setMessage(
          `Created ${result.created_tickets} ticket${result.created_tickets === 1 ? "" : "s"} from the staging queue.`
        );
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Agent processing failed.");
    } finally {
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
  }, [tickets, statusFilter, assigneeFilter, searchQuery, createdRangePreset, createdFrom, createdTo]);

  const visibleTickets = filteredTickets.slice(0, visibleCount);
  const hasMore = filteredTickets.length > visibleCount;

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [statusFilter, assigneeFilter, searchQuery, createdRangePreset, createdFrom, createdTo]);

  const avgResolutionDays = summary?.average_resolution_days ?? 0;
  const hasTickets = (summary?.total_tickets ?? tickets.length) > 0;

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

      <section className="panel workbench-panel">
        <div className="panel-header">
          <h2>Workbench Controls</h2>
          <span>{queuePending} document{queuePending === 1 ? "" : "s"} waiting in queue</span>
        </div>
        <div className="workbench-controls">
          <label htmlFor="seed-count">
            Seed count
            <input
              id="seed-count"
              min={1}
              max={500}
              type="number"
              value={seedCount}
              onChange={(event) => setSeedCount(Number(event.target.value) || 50)}
              disabled={workbenchBusy}
            />
          </label>
          <button
            className="secondary"
            disabled={workbenchBusy || apiOnline === false}
            onClick={() => void handleResetWorkbench()}
            type="button"
          >
            Reset &amp; seed queue
          </button>
          <label htmlFor="sweep-batch">
            Batch size
            <input
              id="sweep-batch"
              min={1}
              max={25}
              type="number"
              value={sweepBatchSize}
              onChange={(event) => setSweepBatchSize(Number(event.target.value) || 5)}
              disabled={workbenchBusy}
            />
          </label>
          <button
            disabled={workbenchBusy || apiOnline === false || queuePending === 0}
            onClick={() => void handleSweepWorkbench()}
            type="button"
          >
            {workbenchBusy ? "Processing…" : "Run agent processing"}
          </button>
          <button
            className="secondary"
            disabled={workbenchBusy || apiOnline === false}
            onClick={() => void refresh(selectedTicket?.ticket_id ?? null)}
            type="button"
          >
            Refresh
          </button>
        </div>
      </section>

      <section className="layout">
        <div className="panel analytics-panel">
          <div className="panel-header">
            <h2>Analytics</h2>
          </div>
          <div className="analytics-overview">
            <Metric label="Total Tickets" value={summary?.total_tickets ?? tickets.length} />
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
        <div className="panel wide detail-panel">
          <TicketDetailPanel
            ticket={selectedTicket}
            loading={detailLoading}
            onTicketUpdate={handleTicketUpdate}
            onStatusChange={handleStatusChange}
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
            <label htmlFor="ticket-search" className="sr-only">Search tickets</label>
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
                onChange={(event) => setCreatedRangePreset(event.target.value as CreatedRangePreset)}
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
          <TicketTable
            tickets={visibleTickets}
            selectedTicketId={selectedTicket?.ticket_id ?? null}
            onSelect={selectTicket}
            onStatusChange={handleStatusChange}
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

function Metric({
  label,
  value,
  valueTone
}: {
  label: string;
  value: string | number;
  valueTone?: "good" | "bad";
}) {
  return (
    <article className="metric-card">
      <span>{label}</span>
      <strong className={valueTone ? `metric-${valueTone}` : undefined}>{value}</strong>
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

function Breakdown({
  title,
  data,
  humanize: humanizeLabel = false
}: {
  title: string;
  data: Record<string, number>;
  humanize?: boolean;
}) {
  const entries = Object.entries(data).slice(0, 8);
  if (!entries.length) return <p className="empty">No data yet.</p>;
  const sorted = [...entries].sort((a, b) => b[1] - a[1]).slice(0, 8);
  const max = Math.max(...sorted.map(([, value]) => value));
  return (
    <div className="breakdown">
      <h3>{title}</h3>
      {sorted.map(([label, value], index) => (
        <div className="bar-row" key={label}>
          <span>{humanizeLabel ? humanize(label) : label}</span>
          <div>
            <i className={`rank-${index + 1}`} style={{ width: `${(value / max) * 100}%` }} />
          </div>
          <strong>{value}</strong>
        </div>
      ))}
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
            <i className={`rank-${index + 1}`} style={{ width: `${(value / sorted[0][1]) * 100}%` }} />
          </div>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}

function TicketTable({
  tickets,
  selectedTicketId,
  onSelect,
  onStatusChange
}: {
  tickets: TicketListItem[];
  selectedTicketId: string | null;
  onSelect: (ticketId: string) => void;
  onStatusChange: (ticketId: string, status: string, options?: StatusChangeOptions) => Promise<void>;
}) {
  if (!tickets.length) return <p className="empty">No tickets match your search.</p>;
  return (
    <div className="table-wrap">
      <table className="tickets-table">
        <thead>
          <tr>
            <th>Ticket</th>
            <th>Source Doc ID</th>
            <th>Description</th>
            <th>Assignee</th>
            <th>Status</th>
            <th>Days Open</th>
          </tr>
        </thead>
        <tbody>
          {tickets.map((ticket) => (
            <tr
              key={ticket.ticket_id}
              className={selectedTicketId === ticket.ticket_id ? "selected-row" : ""}
              onClick={() => onSelect(ticket.ticket_id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(ticket.ticket_id);
                }
              }}
              tabIndex={0}
              role="button"
              aria-label={`View ticket ${ticket.ticket_id}`}
            >
              <td>
                <strong>{ticket.ticket_id}</strong>
              </td>
              <td>{ticket.source_document_ref}</td>
              <td className="ticket-description">{ticketDescription(ticket)}</td>
              <td>{ticket.assignee}</td>
              <td className="status-cell">
                <StatusSelect ticket={ticket} onStatusChange={onStatusChange} />
              </td>
              <td>{formatDaysOpen(ticket)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


function TicketDetailPanel({
  ticket,
  loading,
  onTicketUpdate,
  onStatusChange
}: {
  ticket: TicketDetail | null;
  loading: boolean;
  onTicketUpdate: (ticket: TicketDetail) => void;
  onStatusChange: (ticketId: string, status: string, options?: StatusChangeOptions) => Promise<void>;
}) {
  if (loading) {
    return <p className="empty">Loading ticket details...</p>;
  }
  if (!ticket) return <p className="empty">Select a ticket to inspect the agent diagnosis summary and ownership.</p>;
  const openDays = daysOpen(ticket);

  return (
    <div className="detail">
      <div className="detail-header">
        <p className="detail-kicker">{ticket.ticket_id}</p>
        <EditableDescription ticket={ticket} onTicketUpdate={onTicketUpdate} />
      </div>

      <AgentSummaryHero ticket={ticket} />

      <div className="detail-grid">
        <Info label="Source System" value={ticket.source_system} />
        <Info label="Source System Document ID" value={ticket.source_document_ref} />
        <Info label="Document Value" value={formatDocumentValue(ticket.amount, ticket.currency)} />
        <Info label="Assignee" value={ticket.assignee} />
        <Info label="Ticket Created Date" value={formatTicketDate(ticket.created_at)} />
        <Info label="Ticket Due Date" value={formatTicketDate(ticketDueDate(ticket.created_at))} />
        <Info
          label="Days Open"
          value={formatDaysOpen(ticket)}
          valueTone={openDays < RESOLUTION_BENCHMARK_DAYS ? "good" : "bad"}
        />
        <div className="info">
          <span>Current Status</span>
          <StatusSelect ticket={ticket} onStatusChange={onStatusChange} />
        </div>
      </div>

      <CommentsSection ticket={ticket} onTicketUpdate={onTicketUpdate} />

      <AttachmentsSection ticket={ticket} />

      <h3>Activity Log</h3>
      <JourneyTimeline events={ticket.timeline} />
    </div>
  );
}

function AgentSummaryHero({ ticket }: { ticket: TicketDetail }) {
  const summary = ticket.agent_summary;
  const sentences = summary ? splitIntoSentences(summary) : [];
  const policyNote = policyNoteFromTicket(ticket);

  return (
    <section className="summary-hero">
      <div className="summary-hero-header">
        <p className="summary-hero-eyebrow">Agent diagnosis</p>
        <div className="summary-hero-badges">
          {policyNote ? <span className="summary-hero-badge">{policyNote}</span> : null}
          {ticket.langfuse_trace_url ? (
            <a
              className="summary-hero-trace-link"
              href={ticket.langfuse_trace_url}
              rel="noreferrer"
              target="_blank"
            >
              View trace in Langfuse
            </a>
          ) : null}
        </div>
      </div>
      {sentences.length ? (
        <>
          <p className="summary-hero-lead">{sentences[0]}</p>
          {sentences.length > 1 ? (
            <ul className="summary-hero-points">
              {sentences.slice(1).map((sentence) => (
                <li key={sentence}>{sentence}</li>
              ))}
            </ul>
          ) : null}
        </>
      ) : (
        <p className="summary-hero-empty">Summary is being generated.</p>
      )}
    </section>
  );
}

function policyNoteFromTicket(ticket: TicketDetail): string | null {
  if (ticket.workflow_status === "needs_approval") return "Approval required";
  if (ticket.workflow_status === "blocked") return "Policy blocked";
  if (ticket.workflow_status === "reprocessed") return "Reprocessed";
  return null;
}

function splitIntoSentences(text: string): string[] {
  return text
    .replace(/\s+/g, " ")
    .trim()
    .split(/(?<=[.!?])\s+/)
    .map((part) => part.trim())
    .filter(Boolean);
}

function EditableDescription({
  ticket,
  onTicketUpdate
}: {
  ticket: TicketDetail;
  onTicketUpdate: (ticket: TicketDetail) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const description = ticketDescription(ticket);

  function startEditing() {
    setDraft(description);
    setError(null);
    setEditing(true);
  }

  function cancelEditing() {
    setDraft("");
    setError(null);
    setEditing(false);
  }

  async function saveDescription() {
    const next = draft.trim();
    if (!next || saving) return;
    if (next === description) {
      cancelEditing();
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const updated = await patchTicketDescription(ticket.ticket_id, next);
      onTicketUpdate(updated);
      setEditing(false);
      setDraft("");
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save description.");
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    return (
      <div className="detail-title-edit">
        <input
          autoFocus
          className="detail-title-input"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void saveDescription();
            }
            if (event.key === "Escape") cancelEditing();
          }}
        />
        <div className="detail-title-actions">
          {error ? <span className="comment-error">{error}</span> : null}
          <button disabled={saving || !draft.trim()} onClick={() => void saveDescription()} type="button">
            {saving ? "Saving..." : "Save"}
          </button>
          <button className="secondary" disabled={saving} onClick={cancelEditing} type="button">
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="detail-title-row">
      <h2>{description}</h2>
      <button
        aria-label="Edit description"
        className="icon-button"
        onClick={startEditing}
        title="Edit description"
        type="button"
      >
        <EditIcon />
      </button>
    </div>
  );
}

function EditIcon() {
  return (
    <svg aria-hidden="true" fill="none" height="16" viewBox="0 0 24 24" width="16">
      <path
        d="M4 20h4l10.5-10.5a1.77 1.77 0 0 0-2.5-2.5L5.5 17.5 4 20Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
      <path
        d="M13.5 6.5l4 4"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function CommentsSection({
  ticket,
  onTicketUpdate
}: {
  ticket: TicketDetail;
  onTicketUpdate: (ticket: TicketDetail) => void;
}) {
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const comments = ticket.comments ?? [];

  async function submitComment() {
    const text = draft.trim();
    if (!text || posting) return;

    setPosting(true);
    setError(null);
    try {
      const updated = await postTicketComment(ticket.ticket_id, text);
      onTicketUpdate(updated);
      setDraft("");
    } catch (commentError) {
      setError(
        commentError instanceof Error ? commentError.message : "Could not post comment."
      );
    } finally {
      setPosting(false);
    }
  }

  return (
    <section className="comments-section">
      <h3>Comments</h3>
      <div className="comment-compose">
        <label htmlFor={`comment-${ticket.ticket_id}`} className="sr-only">
          Add a comment
        </label>
        <textarea
          id={`comment-${ticket.ticket_id}`}
          rows={3}
          placeholder="Add a comment..."
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <div className="comment-compose-actions">
          {error ? <span className="comment-error">{error}</span> : null}
          <button disabled={posting || !draft.trim()} onClick={submitComment} type="button">
            {posting ? "Posting..." : "Post Comment"}
          </button>
        </div>
      </div>
      {comments.length ? (
        <ul className="comment-list">
          {[...comments]
            .sort((left, right) => Date.parse(left.created_at) - Date.parse(right.created_at))
            .map((comment) => (
              <li className="comment-item" key={comment.comment_id}>
                <div className="comment-meta">
                  <strong>{comment.author}</strong>
                  <time dateTime={comment.created_at}>
                    {formatJourneyTimestamp(comment.created_at)}
                  </time>
                </div>
                <p>{comment.text}</p>
              </li>
            ))}
        </ul>
      ) : (
        <p className="empty">No comments yet.</p>
      )}
    </section>
  );
}

function JourneyTimeline({ events }: { events: TicketDetail["timeline"] }) {
  if (!events.length) return <p className="empty">No activity logged yet.</p>;

  return (
    <div className="journey-track">
      {events.map((event, index) => {
        const stage = journeyStageLabel(event);
        const stageKey = journeyStageKey(event);
        const isLast = index === events.length - 1;
        const isResolved = stageKey === "resolved";

        return (
          <div
            className={`journey-step complete ${isLast ? "current" : ""} ${isResolved ? "resolved" : ""}`}
            key={`${event.timestamp}-${event.action}`}
          >
            <div className="journey-rail">
              <span className="journey-node" />
              {index < events.length - 1 ? <span className="journey-line" /> : null}
            </div>
            <div className="journey-content">
              <div className="journey-meta">
                <span className="journey-stage">{stage}</span>
                <time className="journey-time" dateTime={event.timestamp}>
                  {formatJourneyTimestamp(event.timestamp)}
                </time>
              </div>
              <p className="journey-text">{event.summary ?? humanize(event.action)}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

const JOURNEY_ACTION_LABELS: Record<string, string> = {
  failed_document_loaded: "Received",
  diagnosis_completed: "Diagnosed",
  ticket_assigned: "Assigned",
  work_started: "In Progress",
  reprocess_completed: "Resolved"
};

function journeyStageLabel(event: TicketDetail["timeline"][number]): string {
  if (event.to_status) {
    return STAGE_LABELS[event.to_status] ?? humanize(event.to_status);
  }
  return JOURNEY_ACTION_LABELS[event.action] ?? humanize(event.action);
}

function journeyStageKey(event: TicketDetail["timeline"][number]): string {
  if (event.to_status) return event.to_status;
  const byAction: Record<string, string> = {
    failed_document_loaded: "received",
    diagnosis_completed: "diagnosed",
    ticket_assigned: "assigned",
    work_started: "in_progress",
    reprocess_completed: "resolved"
  };
  return byAction[event.action] ?? "";
}

function formatJourneyTimestamp(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit"
  });
}

function StatusSelect({
  ticket,
  onStatusChange
}: {
  ticket: Pick<TicketListItem, "ticket_id" | "operator_status">;
  onStatusChange: (ticketId: string, status: string, options?: StatusChangeOptions) => Promise<void>;
}) {
  const [saving, setSaving] = useState(false);
  const [blockedPromptOpen, setBlockedPromptOpen] = useState(false);
  const [resolvedPromptOpen, setResolvedPromptOpen] = useState(false);
  const currentStatus = ticket.operator_status;

  async function applyStatus(nextStatus: string, options?: StatusChangeOptions) {
    setSaving(true);
    try {
      await onStatusChange(ticket.ticket_id, nextStatus, options);
    } finally {
      setSaving(false);
    }
  }

  function handleChange(event: ChangeEvent<HTMLSelectElement>) {
    event.stopPropagation();
    const nextStatus = event.target.value;
    if (nextStatus === currentStatus) return;

    if (nextStatus === "blocked") {
      setBlockedPromptOpen(true);
      return;
    }

    if (nextStatus === "resolved") {
      setResolvedPromptOpen(true);
      return;
    }

    void applyStatus(nextStatus);
  }

  return (
    <>
      <select
        className={`status-select status-${currentStatus}`}
        value={currentStatus}
        disabled={saving || blockedPromptOpen || resolvedPromptOpen}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => event.stopPropagation()}
        onChange={handleChange}
        aria-label={`Status for ${ticket.ticket_id}`}
      >
        {OPERATOR_STATUS_ORDER.map((status) => (
          <option key={status} value={status}>
            {OPERATOR_STATUS_LABELS[status]}
          </option>
        ))}
      </select>
      {blockedPromptOpen ? (
        <BlockedReasonDialog
          ticketId={ticket.ticket_id}
          saving={saving}
          onCancel={() => setBlockedPromptOpen(false)}
          onConfirm={async (note) => {
            try {
              await applyStatus("blocked", { note });
              setBlockedPromptOpen(false);
            } catch {
              // Parent surfaces the API error message.
            }
          }}
        />
      ) : null}
      {resolvedPromptOpen ? (
        <ResolvedProofDialog
          ticketId={ticket.ticket_id}
          saving={saving}
          onCancel={() => setResolvedPromptOpen(false)}
          onConfirm={async (options) => {
            try {
              await applyStatus("resolved", options);
              setResolvedPromptOpen(false);
            } catch {
              // Parent surfaces the API error message.
            }
          }}
        />
      ) : null}
    </>
  );
}

function ModalPortal({ children }: { children: ReactNode }) {
  return createPortal(children, document.body);
}

function BlockedReasonDialog({
  ticketId,
  saving,
  onCancel,
  onConfirm
}: {
  ticketId: string;
  saving: boolean;
  onCancel: () => void;
  onConfirm: (note: string) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    const note = reason.trim();
    if (!note) {
      setError("Explain why this ticket is blocked before saving.");
      return;
    }
    setError(null);
    await onConfirm(note);
  }

  return (
    <ModalPortal>
      <div
        className="modal-backdrop"
        onClick={(event) => {
          event.stopPropagation();
          if (!saving) onCancel();
        }}
        role="presentation"
      >
        <div
          aria-labelledby={`blocked-reason-title-${ticketId}`}
          aria-modal="true"
          className="modal-card"
          onClick={(event) => event.stopPropagation()}
          role="dialog"
        >
          <h3 id={`blocked-reason-title-${ticketId}`}>Why is this ticket blocked?</h3>
          <p className="modal-copy">
            Blocked status requires a comment so other operators understand what is holding this
            ticket up.
          </p>
          <label htmlFor={`blocked-reason-${ticketId}`} className="sr-only">
            Blocked reason
          </label>
          <textarea
            autoFocus
            id={`blocked-reason-${ticketId}`}
            rows={4}
            placeholder="e.g. Waiting on MDG to create vendor master data in target system."
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape" && !saving) onCancel();
            }}
          />
          {error ? <span className="comment-error">{error}</span> : null}
          <div className="modal-actions">
            <button className="secondary" disabled={saving} onClick={onCancel} type="button">
              Cancel
            </button>
            <button disabled={saving || !reason.trim()} onClick={() => void submit()} type="button">
              {saving ? "Saving..." : "Set Blocked"}
            </button>
          </div>
        </div>
      </div>
    </ModalPortal>
  );
}

function ResolvedProofDialog({
  ticketId,
  saving,
  onCancel,
  onConfirm
}: {
  ticketId: string;
  saving: boolean;
  onCancel: () => void;
  onConfirm: (options: StatusChangeOptions) => Promise<void>;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [note, setNote] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busy = saving || uploading;

  function addFiles(selected: FileList | null) {
    if (!selected?.length) return;
    setFiles((current) => {
      const merged = [...current];
      for (const file of Array.from(selected)) {
        if (merged.length >= MAX_RESOLUTION_PROOF_FILES) break;
        if (!merged.some((existing) => existing.name === file.name && existing.size === file.size)) {
          merged.push(file);
        }
      }
      return merged;
    });
  }

  function removeFile(index: number) {
    setFiles((current) => current.filter((_, fileIndex) => fileIndex !== index));
  }

  async function submit() {
    if (!files.length) {
      setError("Upload at least one proof file showing successful reprocessing.");
      return;
    }

    setError(null);
    setUploading(true);
    try {
      const attachmentIds: string[] = [];
      for (const file of files) {
        const updated = await uploadTicketAttachment(ticketId, file);
        const uploaded = updated.attachments?.[updated.attachments.length - 1];
        if (!uploaded) {
          throw new Error(`Could not attach ${file.name}.`);
        }
        attachmentIds.push(uploaded.attachment_id);
      }
      await onConfirm({
        note: note.trim() || undefined,
        attachmentIds
      });
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Could not upload proof and resolve the ticket."
      );
    } finally {
      setUploading(false);
    }
  }

  return (
    <ModalPortal>
      <div
        className="modal-backdrop"
        onClick={(event) => {
          event.stopPropagation();
          if (!busy) onCancel();
        }}
        role="presentation"
      >
        <div
          aria-labelledby={`resolved-proof-title-${ticketId}`}
          aria-modal="true"
          className="modal-card modal-card-wide"
          onClick={(event) => event.stopPropagation()}
          role="dialog"
        >
          <h3 id={`resolved-proof-title-${ticketId}`}>Upload reprocessing proof</h3>
          <p className="modal-copy">
            Resolved status requires proof that the document was reprocessed successfully.
          </p>
          <p className="modal-copy">
            Attach screenshots, SAP confirmation exports, PDFs, or other evidence (up to{" "}
            {MAX_RESOLUTION_PROOF_FILES} files, 10 MB each).
          </p>
        <label className="file-upload-field" htmlFor={`resolved-proof-files-${ticketId}`}>
          <span>Select files or images</span>
          <input
            accept={RESOLUTION_PROOF_ACCEPT}
            id={`resolved-proof-files-${ticketId}`}
            multiple
            onChange={(event) => {
              addFiles(event.target.files);
              event.target.value = "";
            }}
            type="file"
          />
        </label>
        {files.length ? (
          <ul className="upload-preview-list">
            {files.map((file, index) => (
              <li className="upload-preview-item" key={`${file.name}-${file.size}-${index}`}>
                <span>{file.name}</span>
                <span>{formatFileSize(file.size)}</span>
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => removeFile(index)}
                  type="button"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="empty">No proof files selected yet.</p>
        )}
        <label htmlFor={`resolved-note-${ticketId}`} className="modal-label">
          Optional note
        </label>
        <textarea
          id={`resolved-note-${ticketId}`}
          rows={3}
          placeholder="e.g. Document reposted in CFIN and confirmed in Fiori monitor."
          value={note}
          onChange={(event) => setNote(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape" && !busy) onCancel();
          }}
        />
        {error ? <span className="comment-error">{error}</span> : null}
        <div className="modal-actions">
          <button className="secondary" disabled={busy} onClick={onCancel} type="button">
            Cancel
          </button>
          <button disabled={busy || !files.length} onClick={() => void submit()} type="button">
            {busy ? "Saving..." : "Resolve Ticket"}
          </button>
        </div>
        </div>
      </div>
    </ModalPortal>
  );
}

function AttachmentsSection({ ticket }: { ticket: TicketDetail }) {
  const attachments = [...(ticket.attachments ?? [])].sort(
    (left, right) => Date.parse(left.uploaded_at) - Date.parse(right.uploaded_at)
  );

  return (
    <section className="attachments-section">
      <h3>Attachments</h3>
      {attachments.length ? (
        <ul className="attachment-list">
          {attachments.map((attachment) => {
            const href = ticketAttachmentUrl(ticket.ticket_id, attachment.attachment_id);
            const isImage = attachment.content_type.startsWith("image/");
            return (
              <li className="attachment-item" key={attachment.attachment_id}>
                {isImage ? (
                  <a href={href} rel="noreferrer" target="_blank">
                    <img alt={attachment.filename} className="attachment-thumb" src={href} />
                  </a>
                ) : null}
                <div className="attachment-meta">
                  <a href={href} rel="noreferrer" target="_blank">
                    {attachment.filename}
                  </a>
                  <span>
                    {formatFileSize(attachment.size_bytes)} · {attachment.uploaded_by} ·{" "}
                    {formatJourneyTimestamp(attachment.uploaded_at)}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="empty">No attachments yet.</p>
      )}
    </section>
  );
}

function Info({
  label,
  value,
  valueTone
}: {
  label: string;
  value: string;
  valueTone?: "good" | "bad";
}) {
  return (
    <div className="info">
      <span>{label}</span>
      <strong className={valueTone ? `metric-${valueTone}` : undefined}>{value}</strong>
    </div>
  );
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function humanize(value: string): string {
  return value
    .replace(/_/g, " ")
    .split(" ")
    .map((word: string) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function ticketDescription(
  ticket: Pick<TicketListItem, "description" | "title" | "created_at" | "source_system" | "reason_description" | "reason_code">
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

function formatDaysOpen(ticket: { days_open?: number; created_at?: string; updated_at?: string }): string {
  return String(Math.round(daysOpen(ticket)));
}

function daysOpen(ticket: { days_open?: number; created_at?: string; updated_at?: string }): number {
  if (typeof ticket.days_open === "number") return ticket.days_open;
  if (ticket.created_at && ticket.updated_at) {
    return (Date.parse(ticket.updated_at) - Date.parse(ticket.created_at)) / 86_400_000;
  }
  return 0;
}

function ticketDueDate(createdAt: string): Date {
  return new Date(Date.parse(createdAt) + RESOLUTION_BENCHMARK_DAYS * 86_400_000);
}

function formatTicketDate(iso: string | Date): string {
  const date = iso instanceof Date ? iso : new Date(iso);
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric"
  });
}

function formatDocumentValue(amount: number, currency: string): string {
  return `${amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

function matchesCreatedDateRange(
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

function urgencyRank(ticket: TicketListItem): number {
  const open = daysOpen(ticket);
  const status = ticket.operator_status;
  if (status === "blocked") return 500 + open;
  if (status === "in_progress") return 300 + open;
  if (status === "assigned") return 200 + open;
  return open;
}
