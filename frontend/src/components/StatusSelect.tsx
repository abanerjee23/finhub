import { ChangeEvent, useState } from "react";
import { TicketListItem } from "../api/client";
import { OPERATOR_STATUS_LABELS, OPERATOR_STATUS_ORDER } from "../lib/format";
import { BlockedReasonDialog, ResolvedProofDialog, StatusChangeOptions } from "./dialogs";

export function StatusSelect({
  ticket,
  onStatusChange
}: {
  ticket: Pick<TicketListItem, "ticket_id" | "operator_status" | "assignee">;
  onStatusChange: (
    ticketId: string,
    status: string,
    options?: StatusChangeOptions
  ) => Promise<void>;
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

    void applyStatus(nextStatus, {
      actor: nextStatus === "in_progress" ? ticket.assignee : "Workbench User"
    });
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
