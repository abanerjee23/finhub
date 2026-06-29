// Same-origin /api in dev (Vite proxy) and production (FastAPI serves static + API).
const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export type TicketListItem = {
  ticket_id: string;
  document_id: string;
  source_document_ref: string;
  source_system: string;
  title: string;
  description: string;
  company_code: string;
  priority: string;
  operator_status: string;
  reason_code: string;
  reason_description?: string;
  error_type: string;
  workflow_status: string;
  owner_role: string;
  tagged_roles: string[];
  assignee: string;
  agent_summary: string | null;
  days_open: number;
  created_at: string;
  updated_at: string;
  sla_due_at: string;
};

export type DashboardSummary = {
  total_tickets: number;
  open_tickets: number;
  closed_tickets: number;
  average_resolution_days: number;
  slowest_stage: string | null;
  tickets_by_operator_status: Record<string, number>;
  tickets_by_owner_role: Record<string, number>;
  tickets_by_reason_code: Record<string, number>;
  workflow_status_counts: Record<string, number>;
  average_stage_days: Record<string, number>;
};

export type TicketComment = {
  comment_id: string;
  author: string;
  text: string;
  created_at: string;
};

export type TicketAttachment = {
  attachment_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_at: string;
  uploaded_by: string;
  purpose: string;
};

export type TicketDetail = TicketListItem & {
  case_id: string;
  source_document_ref: string;
  amount: number;
  currency: string;
  policy_summary: string;
  agent_summary: string | null;
  policy_owner: string;
  langfuse_trace_url?: string | null;
  current_stage_started_at: string;
  created_at: string;
  workflow_run: {
    langfuse_trace_id?: string | null;
    diagnosis: {
      root_cause: string;
      evidence: string[];
      confidence: number;
    };
    remediation_plan: {
      action: string;
      requires_approval: boolean;
      rationale: string;
      proposed_changes: Record<string, unknown>;
    };
    governance_decision: {
      allowed: boolean;
      requires_approval: boolean;
      policy_reasons: string[];
      audit_reason: string;
    };
  };
  timeline: Array<{
    timestamp: string;
    actor: string;
    action: string;
    from_status: string | null;
    to_status: string | null;
    details: Record<string, unknown>;
    summary?: string;
  }>;
  comments?: TicketComment[];
  attachments?: TicketAttachment[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(
      detail
        ? `API request failed (${response.status}): ${detail.slice(0, 180)}`
        : `API request failed (${response.status})`
    );
  }
  return response.json() as Promise<T>;
}

export function bootstrapDemo(count = 350): Promise<{ created_tickets: number }> {
  return request(`/api/demo/bootstrap?count=${count}`, { method: "POST" });
}

export function checkApiHealth(): Promise<{ status: string }> {
  return request("/api/health");
}

export function getTickets(): Promise<TicketListItem[]> {
  return request("/api/tickets");
}

export function getTicket(ticketId: string): Promise<TicketDetail> {
  return request(`/api/tickets/${ticketId}`);
}

export function postTicketComment(
  ticketId: string,
  text: string,
  author = "Workbench User"
): Promise<TicketDetail> {
  return request(`/api/tickets/${ticketId}/comments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, author })
  });
}

export function patchTicketDescription(
  ticketId: string,
  description: string
): Promise<TicketDetail> {
  return request(`/api/tickets/${ticketId}/description`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ description })
  });
}

export function transitionTicket(
  ticketId: string,
  status: string,
  options?: { actor?: string; note?: string; attachmentIds?: string[] }
): Promise<TicketDetail> {
  const body: {
    operator_status: string;
    actor: string;
    note?: string;
    attachment_ids?: string[];
  } = {
    operator_status: status,
    actor: options?.actor ?? "Workbench User"
  };
  if (options?.note?.trim()) {
    body.note = options.note.trim();
  }
  if (options?.attachmentIds?.length) {
    body.attachment_ids = options.attachmentIds;
  }
  return request(`/api/tickets/${ticketId}/transition`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

export function uploadTicketAttachment(
  ticketId: string,
  file: File,
  actor = "Workbench User"
): Promise<TicketDetail> {
  const form = new FormData();
  form.append("file", file);
  return request(
    `/api/tickets/${ticketId}/attachments?actor=${encodeURIComponent(actor)}`,
    {
      method: "POST",
      body: form
    }
  );
}

export function ticketAttachmentUrl(ticketId: string, attachmentId: string): string {
  const base = import.meta.env.VITE_API_BASE ?? "";
  return `${base}/api/tickets/${encodeURIComponent(ticketId)}/attachments/${encodeURIComponent(attachmentId)}`;
}

export function getDashboardSummary(): Promise<DashboardSummary> {
  return request("/api/dashboard/summary");
}

export type WorkbenchStatus = {
  ticket_count: number;
  staging_counts: Record<string, number>;
  summary_source: string;
};

export type WorkbenchSweepResult = {
  processed: number;
  created_tickets: number;
  errors: Array<{ document_id?: string; error: string }>;
  ticket_count: number;
  staging_counts: Record<string, number>;
  dashboard: DashboardSummary;
};

export function getWorkbenchStatus(): Promise<WorkbenchStatus> {
  return request("/api/workbench/status");
}

export function resetWorkbench(count = 50, seed = 42): Promise<WorkbenchStatus & { dashboard: DashboardSummary }> {
  return request(`/api/workbench/reset?count=${count}&seed=${seed}`, { method: "POST" });
}

export function clearWorkbench(): Promise<WorkbenchStatus & { dashboard: DashboardSummary }> {
  return request("/api/workbench/clear", { method: "POST" });
}

export function sweepWorkbench(batchSize = 5): Promise<WorkbenchSweepResult> {
  return request("/api/workbench/sweep", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ batch_size: batchSize })
  });
}
