import { useEffect, useState } from "react";
import {
  approveTicket,
  AssigneeOption,
  getTicket,
  maintainTicketMapping,
  patchTicketDescription,
  postSummaryFeedback,
  postTicketComment,
  ticketAttachmentUrl,
  TicketDetail,
  updateTicketAssignee
} from "../api/client";
import {
  daysOpen,
  formatDaysOpen,
  formatDocumentValue,
  formatFileSize,
  formatJourneyTimestamp,
  formatTicketDate,
  humanize,
  MAPPING_PIPELINE_STEPS,
  MASTER_DATA_PIPELINE_STEPS,
  RESOLUTION_BENCHMARK_DAYS,
  splitIntoSentences,
  STAGE_LABELS,
  ticketDescription,
  ticketDueDate,
  TRANSITIONAL_WORKFLOW_STATUSES,
  WORKFLOW_STATUS_LABELS
} from "../lib/format";
import { ApproveDialog, MaintainMappingDialog, StatusChangeOptions } from "./dialogs";
import { StatusSelect } from "./StatusSelect";

const MAPPING_LABELS: Record<string, string> = {
  MP_GL_ACCOUNT: "GL account",
  MP_COST_CENTER: "cost center",
  MP_PROFIT_CENTER: "profit center"
};

function mappingLabelForReason(reasonCode: string): string | null {
  const prefix = Object.keys(MAPPING_LABELS).find((key) => reasonCode.startsWith(key));
  return prefix ? MAPPING_LABELS[prefix] : null;
}

export function TicketDetailPanel({
  ticket,
  loading,
  assignees,
  onTicketUpdate,
  onStatusChange,
  onWorkflowAction
}: {
  ticket: TicketDetail | null;
  loading: boolean;
  assignees: AssigneeOption[];
  onTicketUpdate: (ticket: TicketDetail) => void;
  onStatusChange: (
    ticketId: string,
    status: string,
    options?: StatusChangeOptions
  ) => Promise<void>;
  onWorkflowAction: (message: string) => void;
}) {
  useReprocessingPoll(ticket, onTicketUpdate);

  if (loading) {
    return <p className="empty">Loading ticket details...</p>;
  }
  if (!ticket) {
    return (
      <p className="empty">Select a ticket to inspect the agent diagnosis summary and ownership.</p>
    );
  }
  const openDays = daysOpen(ticket);

  return (
    <div className="detail">
      <div className="detail-header">
        <p className="detail-kicker">{ticket.ticket_id}</p>
        <EditableDescription ticket={ticket} onTicketUpdate={onTicketUpdate} />
      </div>

      <AgentSummaryHero ticket={ticket} onTicketUpdate={onTicketUpdate} />

      <WorkflowActions
        ticket={ticket}
        onTicketUpdate={onTicketUpdate}
        onWorkflowAction={onWorkflowAction}
      />

      <ReprocessingPipeline ticket={ticket} />

      <div className="detail-grid">
        <Info label="Source System" value={ticket.source_system} />
        <Info label="Source System Document ID" value={ticket.source_document_ref} />
        <Info label="Document Value" value={formatDocumentValue(ticket.amount, ticket.currency)} />
        <AssigneeSelect ticket={ticket} assignees={assignees} onTicketUpdate={onTicketUpdate} />
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

const POLL_INTERVAL_MS = 1500;

function useReprocessingPoll(
  ticket: TicketDetail | null,
  onTicketUpdate: (ticket: TicketDetail) => void
) {
  const ticketId = ticket?.ticket_id ?? null;
  const status = ticket?.workflow_run.status ?? null;
  const isTransitional = status !== null && TRANSITIONAL_WORKFLOW_STATUSES.has(status);

  useEffect(() => {
    if (!ticketId || !isTransitional) return;
    let cancelled = false;
    const interval = window.setInterval(async () => {
      try {
        const updated = await getTicket(ticketId);
        if (!cancelled) onTicketUpdate(updated);
      } catch {
        // Transient poll failure; next tick retries.
      }
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [ticketId, isTransitional, onTicketUpdate]);
}

function ReprocessingPipeline({ ticket }: { ticket: TicketDetail }) {
  const action = ticket.workflow_run.remediation_plan.action;
  const status = ticket.workflow_run.status;
  const steps =
    action === "create_target_master_data"
      ? MASTER_DATA_PIPELINE_STEPS
      : action === "maintain_source_mapping"
        ? MAPPING_PIPELINE_STEPS
        : null;

  if (!steps) return null;
  // Only show once the operator has kicked off the pipeline — the CTA button
  // is enough for the initial needs_approval/needs_mapping state.
  if (status === steps[0].key) return null;

  const currentIndex = steps.findIndex((step) => step.key === status);

  return (
    <div className="reprocessing-pipeline">
      {steps.map((step, index) => (
        <div
          className={`pipeline-step ${index <= currentIndex ? "pipeline-step-done" : ""} ${
            index === currentIndex ? "pipeline-step-current" : ""
          }`}
          key={step.key}
        >
          <span className="pipeline-node" />
          <span className="pipeline-label">{step.label}</span>
          {index < steps.length - 1 ? <span className="pipeline-connector" /> : null}
        </div>
      ))}
      {currentIndex >= 0 && currentIndex < steps.length - 1 ? (
        <span className="pipeline-hint">Advancing automatically…</span>
      ) : null}
    </div>
  );
}

function WorkflowActions({
  ticket,
  onTicketUpdate,
  onWorkflowAction
}: {
  ticket: TicketDetail;
  onTicketUpdate: (ticket: TicketDetail) => void;
  onWorkflowAction: (message: string) => void;
}) {
  const [approveOpen, setApproveOpen] = useState(false);
  const [mappingOpen, setMappingOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const workflowStatus = ticket.workflow_run.status;
  const mappingLabel = mappingLabelForReason(ticket.reason_code);
  const canApprove = workflowStatus === "needs_approval";
  const canMaintainMapping = mappingLabel !== null && workflowStatus === "needs_mapping";

  if (!canApprove && !canMaintainMapping) return null;

  return (
    <div className="workflow-actions">
      {canApprove ? (
        <button disabled={busy} onClick={() => setApproveOpen(true)} type="button">
          Approve &amp; Reprocess
        </button>
      ) : null}
      {canMaintainMapping ? (
        <button
          className={canApprove ? "secondary" : undefined}
          disabled={busy}
          onClick={() => setMappingOpen(true)}
          type="button"
        >
          Maintain Mapping…
        </button>
      ) : null}
      {approveOpen ? (
        <ApproveDialog
          ticketId={ticket.ticket_id}
          saving={busy}
          onCancel={() => setApproveOpen(false)}
          onConfirm={async (note) => {
            setBusy(true);
            try {
              const updated = await approveTicket(ticket.ticket_id, { note });
              onTicketUpdate(updated);
              setApproveOpen(false);
              onWorkflowAction(
                "Approval recorded. Master data creation and reprocessing are now queued — " +
                  "this ticket will advance automatically over the next moment."
              );
            } finally {
              setBusy(false);
            }
          }}
        />
      ) : null}
      {mappingOpen && mappingLabel ? (
        <MaintainMappingDialog
          ticketId={ticket.ticket_id}
          mappingLabel={mappingLabel}
          saving={busy}
          onCancel={() => setMappingOpen(false)}
          onConfirm={async (targetValue, sourceValue, note) => {
            setBusy(true);
            try {
              const updated = await maintainTicketMapping(ticket.ticket_id, targetValue, {
                sourceValue: sourceValue || undefined,
                note: note || undefined
              });
              onTicketUpdate(updated);
              setMappingOpen(false);
              onWorkflowAction(
                "Mapping maintained. Reprocessing is now queued — this ticket will advance " +
                  "automatically over the next moment."
              );
            } finally {
              setBusy(false);
            }
          }}
        />
      ) : null}
    </div>
  );
}

function AssigneeSelect({
  ticket,
  assignees,
  onTicketUpdate
}: {
  ticket: TicketDetail;
  assignees: AssigneeOption[];
  onTicketUpdate: (ticket: TicketDetail) => void;
}) {
  const [saving, setSaving] = useState(false);
  const options = assignees.length
    ? assignees
    : [{ name: ticket.assignee, role: ticket.owner_role }];
  const known = options.some((option) => option.name === ticket.assignee);

  async function handleChange(nextAssignee: string) {
    if (nextAssignee === ticket.assignee || saving) return;
    setSaving(true);
    try {
      onTicketUpdate(await updateTicketAssignee(ticket.ticket_id, nextAssignee));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="info">
      <span>Assignee</span>
      <select
        aria-label={`Assignee for ${ticket.ticket_id}`}
        className="assignee-select"
        disabled={saving}
        value={ticket.assignee}
        onChange={(event) => void handleChange(event.target.value)}
      >
        {!known ? <option value={ticket.assignee}>{ticket.assignee}</option> : null}
        {options.map((option) => (
          <option key={option.name} value={option.name}>
            {option.name} — {option.role}
          </option>
        ))}
      </select>
    </div>
  );
}

function AgentSummaryHero({
  ticket,
  onTicketUpdate
}: {
  ticket: TicketDetail;
  onTicketUpdate: (ticket: TicketDetail) => void;
}) {
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const [shadowOpen, setShadowOpen] = useState(false);
  const summary = ticket.agent_summary;
  const sentences = summary ? splitIntoSentences(summary) : [];
  const policyNote = policyNoteFromTicket(ticket);
  const executionMode = ticket.workflow_run.execution_mode;
  const agentDriven = executionMode?.startsWith("openai_agents");
  const feedback = ticket.summary_feedback;

  async function sendFeedback(rating: "up" | "down") {
    if (feedbackBusy) return;
    setFeedbackBusy(true);
    try {
      onTicketUpdate(await postSummaryFeedback(ticket.ticket_id, rating));
    } finally {
      setFeedbackBusy(false);
    }
  }

  return (
    <section className="summary-hero">
      <div className="summary-hero-header">
        <p className="summary-hero-eyebrow">Agent diagnosis</p>
        <div className="summary-hero-badges">
          {executionMode ? (
            <span
              className="summary-hero-badge execution-badge"
              title={`Workflow execution mode: ${executionMode}`}
            >
              {agentDriven ? "Multi-agent run" : "Deterministic run"}
            </span>
          ) : null}
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
          <div className="summary-feedback">
            <span>Was this summary helpful?</span>
            <button
              aria-label="Summary was helpful"
              className={`feedback-button ${feedback?.rating === "up" ? "feedback-active" : ""}`}
              disabled={feedbackBusy}
              onClick={() => void sendFeedback("up")}
              type="button"
            >
              👍
            </button>
            <button
              aria-label="Summary was not helpful"
              className={`feedback-button ${feedback?.rating === "down" ? "feedback-active" : ""}`}
              disabled={feedbackBusy}
              onClick={() => void sendFeedback("down")}
              type="button"
            >
              👎
            </button>
            {feedback ? <small>Feedback recorded — thank you.</small> : null}
          </div>
        </>
      ) : (
        <p className="summary-hero-empty">Summary is being generated.</p>
      )}
      {ticket.workflow_run.agent_final_output ? (
        <div className="shadow-output">
          <button
            className="shadow-toggle"
            onClick={() => setShadowOpen((open) => !open)}
            type="button"
          >
            {shadowOpen ? "Hide" : "Show"} agent audit note (shadow mode)
            {ticket.workflow_run.shadow_agreement === false ? " ⚠ disagreement" : ""}
          </button>
          {shadowOpen ? (
            <p className="shadow-text">{ticket.workflow_run.agent_final_output}</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function policyNoteFromTicket(ticket: TicketDetail): string | null {
  const status = ticket.workflow_run.status ?? ticket.workflow_status;
  if (status === "blocked") return "Policy blocked";
  return WORKFLOW_STATUS_LABELS[status] ?? null;
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
          <button
            disabled={saving || !draft.trim()}
            onClick={() => void saveDescription()}
            type="button"
          >
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
      setError(commentError instanceof Error ? commentError.message : "Could not post comment.");
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

const JOURNEY_ACTION_LABELS: Record<string, string> = {
  failed_document_loaded: "Received",
  diagnosis_completed: "Diagnosed",
  ticket_assigned: "Assigned",
  work_started: "In Progress",
  reprocess_completed: "Resolved",
  approval_recorded: "Approved",
  mapping_maintained: "Mapping Maintained",
  reassigned: "Reassigned"
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
