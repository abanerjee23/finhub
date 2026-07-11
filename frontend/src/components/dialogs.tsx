import { ReactNode, useState } from "react";
import { createPortal } from "react-dom";
import { uploadTicketAttachment } from "../api/client";
import { formatFileSize } from "../lib/format";

const RESOLUTION_PROOF_ACCEPT =
  "image/jpeg,image/png,image/gif,image/webp,application/pdf,text/plain,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel";
const MAX_RESOLUTION_PROOF_FILES = 5;

export type StatusChangeOptions = {
  note?: string;
  attachmentIds?: string[];
};

export function ModalPortal({ children }: { children: ReactNode }) {
  return createPortal(children, document.body);
}

export function BlockedReasonDialog({
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

export function ResolvedProofDialog({
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

export function ApproveDialog({
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
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setError(null);
    try {
      await onConfirm(note.trim());
    } catch (submitError) {
      setError(
        submitError instanceof Error ? submitError.message : "Could not record the approval."
      );
    }
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
          aria-labelledby={`approve-title-${ticketId}`}
          aria-modal="true"
          className="modal-card"
          onClick={(event) => event.stopPropagation()}
          role="dialog"
        >
          <h3 id={`approve-title-${ticketId}`}>Approve master data creation?</h3>
          <p className="modal-copy">
            Your approval is recorded in the audit trail, the missing master data is created in
            the target system, and the document is reprocessed under policy control.
          </p>
          <label htmlFor={`approve-note-${ticketId}`} className="modal-label">
            Optional note
          </label>
          <textarea
            id={`approve-note-${ticketId}`}
            rows={3}
            placeholder="e.g. Verified with MDG that the vendor record request is legitimate."
            value={note}
            onChange={(event) => setNote(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape" && !saving) onCancel();
            }}
          />
          {error ? <span className="comment-error">{error}</span> : null}
          <div className="modal-actions">
            <button className="secondary" disabled={saving} onClick={onCancel} type="button">
              Cancel
            </button>
            <button disabled={saving} onClick={() => void submit()} type="button">
              {saving ? "Approving..." : "Approve & Reprocess"}
            </button>
          </div>
        </div>
      </div>
    </ModalPortal>
  );
}

export function MaintainMappingDialog({
  ticketId,
  mappingLabel,
  defaultSourceValue,
  saving,
  onCancel,
  onConfirm
}: {
  ticketId: string;
  mappingLabel: string;
  defaultSourceValue?: string;
  saving: boolean;
  onCancel: () => void;
  onConfirm: (targetValue: string, sourceValue: string, note: string) => Promise<void>;
}) {
  const [sourceValue, setSourceValue] = useState(defaultSourceValue ?? "");
  const [targetValue, setTargetValue] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    const target = targetValue.trim();
    if (!target) {
      setError("Enter the target value for the mapping.");
      return;
    }
    setError(null);
    try {
      await onConfirm(target, sourceValue.trim(), note.trim());
    } catch (submitError) {
      setError(
        submitError instanceof Error ? submitError.message : "Could not maintain the mapping."
      );
    }
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
          aria-labelledby={`mapping-title-${ticketId}`}
          aria-modal="true"
          className="modal-card"
          onClick={(event) => event.stopPropagation()}
          role="dialog"
        >
          <h3 id={`mapping-title-${ticketId}`}>Maintain {mappingLabel} mapping</h3>
          <p className="modal-copy">
            Record the source-to-target mapping entry, then the document is reprocessed. No
            approval is required for mapping maintenance.
          </p>
          <label htmlFor={`mapping-source-${ticketId}`} className="modal-label">
            Source value
          </label>
          <input
            className="modal-input"
            id={`mapping-source-${ticketId}`}
            placeholder="Source system value"
            value={sourceValue}
            onChange={(event) => setSourceValue(event.target.value)}
          />
          <label htmlFor={`mapping-target-${ticketId}`} className="modal-label">
            Target value
          </label>
          <input
            autoFocus
            className="modal-input"
            id={`mapping-target-${ticketId}`}
            placeholder="Central Finance target value"
            value={targetValue}
            onChange={(event) => setTargetValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void submit();
              if (event.key === "Escape" && !saving) onCancel();
            }}
          />
          <label htmlFor={`mapping-note-${ticketId}`} className="modal-label">
            Optional note
          </label>
          <textarea
            id={`mapping-note-${ticketId}`}
            rows={2}
            placeholder="e.g. Confirmed target cost center with controlling."
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
          {error ? <span className="comment-error">{error}</span> : null}
          <div className="modal-actions">
            <button className="secondary" disabled={saving} onClick={onCancel} type="button">
              Cancel
            </button>
            <button disabled={saving || !targetValue.trim()} onClick={() => void submit()} type="button">
              {saving ? "Saving..." : "Maintain & Reprocess"}
            </button>
          </div>
        </div>
      </div>
    </ModalPortal>
  );
}
