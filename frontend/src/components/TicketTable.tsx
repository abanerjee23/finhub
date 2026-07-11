import { useState } from "react";
import { TicketListItem } from "../api/client";
import { formatDaysOpen, ticketDescription } from "../lib/format";
import { StatusChangeOptions } from "./dialogs";
import { StatusSelect } from "./StatusSelect";

// Bulk moves are limited to states with no extra requirements (blocked needs a
// note, resolved needs proof attachments).
const BULK_TARGETS = [
  { value: "assigned", label: "Assigned" },
  { value: "in_progress", label: "In Progress" }
];

export function TicketTable({
  tickets,
  selectedTicketId,
  onSelect,
  onStatusChange,
  onBulkStatusChange
}: {
  tickets: TicketListItem[];
  selectedTicketId: string | null;
  onSelect: (ticketId: string) => void;
  onStatusChange: (
    ticketId: string,
    status: string,
    options?: StatusChangeOptions
  ) => Promise<void>;
  onBulkStatusChange: (ticketIds: string[], status: string) => Promise<void>;
}) {
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [bulkTarget, setBulkTarget] = useState("in_progress");
  const [bulkBusy, setBulkBusy] = useState(false);

  if (!tickets.length) return <p className="empty">No tickets match your search.</p>;

  const visibleChecked = tickets.filter((ticket) => checked.has(ticket.ticket_id));
  const allVisibleChecked = visibleChecked.length === tickets.length && tickets.length > 0;

  function toggle(ticketId: string) {
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(ticketId)) next.delete(ticketId);
      else next.add(ticketId);
      return next;
    });
  }

  function toggleAll() {
    setChecked(allVisibleChecked ? new Set() : new Set(tickets.map((t) => t.ticket_id)));
  }

  async function applyBulk() {
    if (!visibleChecked.length || bulkBusy) return;
    setBulkBusy(true);
    try {
      await onBulkStatusChange(
        visibleChecked.map((ticket) => ticket.ticket_id),
        bulkTarget
      );
      setChecked(new Set());
    } finally {
      setBulkBusy(false);
    }
  }

  return (
    <>
      {visibleChecked.length ? (
        <div className="bulk-bar">
          <span>
            {visibleChecked.length} selected
          </span>
          <label htmlFor="bulk-status" className="sr-only">
            Bulk status
          </label>
          <select
            id="bulk-status"
            value={bulkTarget}
            disabled={bulkBusy}
            onChange={(event) => setBulkTarget(event.target.value)}
          >
            {BULK_TARGETS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button disabled={bulkBusy} onClick={() => void applyBulk()} type="button">
            {bulkBusy ? "Updating…" : "Apply to selected"}
          </button>
          <button
            className="secondary"
            disabled={bulkBusy}
            onClick={() => setChecked(new Set())}
            type="button"
          >
            Clear
          </button>
        </div>
      ) : null}
      <div className="table-wrap">
        <table className="tickets-table">
          <thead>
            <tr>
              <th className="check-cell">
                <input
                  aria-label="Select all visible tickets"
                  checked={allVisibleChecked}
                  onChange={toggleAll}
                  type="checkbox"
                />
              </th>
              <th>Ticket</th>
              <th>Source Doc ID</th>
              <th>Description</th>
              <th>Value</th>
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
                <td
                  className="check-cell"
                  onClick={(event) => event.stopPropagation()}
                  onKeyDown={(event) => event.stopPropagation()}
                >
                  <input
                    aria-label={`Select ${ticket.ticket_id}`}
                    checked={checked.has(ticket.ticket_id)}
                    onChange={() => toggle(ticket.ticket_id)}
                    type="checkbox"
                  />
                </td>
                <td>
                  <strong>{ticket.ticket_id}</strong>
                </td>
                <td>{ticket.source_document_ref}</td>
                <td className="ticket-description">{ticketDescription(ticket)}</td>
                <td className="value-cell">
                  {ticket.amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}{" "}
                  {ticket.currency}
                </td>
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
    </>
  );
}
