export type Role = "analyst" | "supervisor" | "admin" | "auditor";

export type RegStatus =
  | "awaiting_processing"
  | "processing"
  | "awaiting_review"
  | "approved"
  | "pending_documents"
  | "rejected"
  | "processing_failed";

export type Severity = "info" | "low" | "medium" | "high" | "critical";

export interface User {
  id: string;
  name: string;
  email: string;
  role: Role;
  is_active?: boolean;
  last_login_at?: string | null;
}

export interface Meta {
  user: User;
  document_types: Record<string, { label: string; fields: string[] }>;
  profiles: Record<string, { label: string; tax_id_kind: "cpf" | "cnpj" }>;
  field_labels: Record<string, string>;
  permissions: { operate: boolean; approve: boolean; reject: boolean; override: boolean; audit: boolean; admin: boolean };
  limits: { max_upload_mb: number; accepted: string[] };
}

export interface PriorityReason {
  rule: string;
  label: string;
  points: number;
}

export interface RegistrationRow {
  id: string;
  code: string;
  kind: string;
  subject_name: string;
  tax_id: string | null;
  status: RegStatus;
  priority_score: number;
  priority_reasons: PriorityReason[];
  ready_for_decision: boolean;
  missing: string[];
  open_findings: number;
  blocking_findings: number;
  document_count: number | null;
  created_at: string;
  updated_at: string;
  decided_at: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Evidence {
  label: string;
  value: string | null;
  document_id: string | null;
  field: string | null;
  page: number | null;
  bbox: number[] | null;
  note: string | null;
}

export interface Finding {
  id: string;
  registration_id: string | null;
  document_id: string | null;
  code: string;
  category: string;
  severity: Severity;
  title: string;
  explanation: string;
  evidence: Evidence[];
  field_name: string | null;
  confidence: number | null;
  confidence_basis: string | null;
  recommended_action: string | null;
  source: "rule" | "forensics" | "ai" | "system" | "human";
  status: "open" | "accepted" | "escalated" | "overridden" | "superseded";
  resolved_by: { name: string } | null;
  resolved_at: string | null;
  resolution_note: string | null;
  created_at: string;
}

export interface Validity {
  state: "valid" | "expired" | "too_old" | "no_expiry" | "unknown" | "contradictory" | "invalid";
  summary: string;
  rule: string | null;
  reference_date: string;
}

export interface DocumentBrief {
  id: string;
  registration_id: string | null;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  source: string;
  source_ref: string | null;
  received_at: string;
  page_count: number | null;
  doc_type: string | null;
  doc_type_confidence: number | null;
  doc_type_source: "rules" | "ai" | "human" | null;
  issuer: string | null;
  status: "queued" | "processing" | "processed" | "failed" | "purged";
  processing_error: string | null;
  processing_attempts: number;
  processed_at: string | null;
  ai_status: "skipped" | "done" | "failed" | null;
  ai_error: string | null;
  validity: Validity | null;
  suggested_registration_id: string | null;
}

export interface ExtractedField {
  id: string;
  name: string;
  label: string;
  value: string | null;
  raw_value: string | null;
  confidence: number | null;
  source: "pdf_text" | "ocr" | "ai" | "human";
  page: number | null;
  bbox: number[] | null;
  valid: boolean | null;
  validation_note: string | null;
  status: "extracted" | "confirmed" | "corrected";
  previous_value: string | null;
}

export interface DocumentDetail extends DocumentBrief {
  fields: ExtractedField[];
  missing_fields: { name: string; label: string }[];
  findings: Finding[];
  classification: { scores: Record<string, number>; matched: string[]; rules_type: string | null; rules_confidence: number } | null;
  ocr_provider: string | null;
  registration: RegistrationRow | null;
  siblings: { id: string; original_filename: string; doc_type: string | null; status: string }[];
  job: { status: string; attempts: number; duration_ms: number | null; error: string | null; metrics: Record<string, unknown>; finished_at: string | null } | null;
}

export interface ChecklistItem {
  id: string;
  label: string;
  group?: string | null;
  stage?: string | null;
  note?: string | null;
  year?: number | null;
  required?: boolean;
  blocking?: boolean;
  per_partner?: boolean;
  received?: number;
  state_note?: string | null;
  documents?: { id: string; name: string }[];
  accepted_types: string[];
  state: "ok" | "missing" | "unclassified" | "processing" | "failed" | "expired" | "too_old" | "invalid" | "needs_review" | "optional";
  document_id: string | null;
  document_name: string | null;
}

export interface InfoItem {
  id: string;
  label: string;
  hint?: string | null;
  group?: string | null;
  stage?: string | null;
  state: "ok" | "missing";
  value: string | null;
  blocking: boolean;
}

export interface StageSummary {
  id: string;
  label: string;
  note?: string | null;
  current: boolean;
  done: number;
  total: number;
}

export interface Decision {
  id: string;
  action: "approve" | "request_documents" | "reject" | "escalate" | "reopen";
  reason: string | null;
  requested_items: string[];
  overrides: { item: string }[];
  decided_by: { name: string } | null;
  decided_at: string;
}

export interface HistoryEvent {
  id: number;
  at: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  details: Record<string, any>;
  registration_code?: string | null;
  registration_id?: string | null;
}

export interface RegistrationDetail extends RegistrationRow {
  reference_fields: Record<string, string>;
  checklist: {
    documents?: ChecklistItem[];
    info?: InfoItem[];
    stages?: StageSummary[];
    stage?: string | null;
    fields?: { field: string; label: string; state: "ok" | "missing"; value: string | null; document_id: string | null }[];
    open_findings?: number;
    blocking_findings?: number;
    processing?: boolean;
    ready_for_decision?: boolean;
  };
  decision_reason: string | null;
  decided_by: { name: string } | null;
  created_by: { name: string } | null;
  legal_hold: boolean;
  anonymized_at: string | null;
  documents: DocumentBrief[];
  findings: Finding[];
  decisions: Decision[];
  history: HistoryEvent[];
}

export interface Dashboard {
  counts: Record<
    | "awaiting_processing"
    | "documents_in_flight"
    | "awaiting_review"
    | "ready_for_decision"
    | "escalated"
    | "missing_documents"
    | "pending_documents"
    | "processing_failed"
    | "documents_failed"
    | "inbox"
    | "decided_today",
    number
  >;
  next_up: RegistrationRow[];
  recently_completed: RegistrationRow[];
  processing: { jobs_24h: number; avg_seconds_24h: number | null };
  watcher: { folder: string | null; reachable: boolean; last_scan_at: string | null; last_error: string | null; pending_files: number; enabled: boolean };
  ai: { configured: boolean; enabled: boolean; model: string | null };
  ocr: { provider: string };
}
