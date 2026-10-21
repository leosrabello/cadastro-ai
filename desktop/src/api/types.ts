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
  modalities: Record<Modality, string>;
  retention?: { rejected_days: number | null };
  field_labels: Record<string, string>;
  permissions: { operate: boolean; approve: boolean; reject: boolean; override: boolean; audit: boolean; admin: boolean };
  limits: { max_upload_mb: number; accepted: string[] };
}

export interface PriorityReason {
  rule: string;
  label: string;
  points: number;
}

export type Modality = "normal" | "one7";
export type Scope = Modality | "all";

export interface RegistrationRow {
  id: string;
  code: string;
  kind: string;
  modality: Modality;
  client: { id: string; name: string; commercial: string | null } | null;
  commercial: { id: string; name: string } | null;
  group: { id: string; name: string } | null;
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
  status: "open" | "accepted" | "escalated" | "overridden" | "superseded" | "note";
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
  fields_to_review: number;
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
  modality: Modality | null;
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

/* ---------- portfolio (carteira) ---------- */

export interface ClientStatusDef {
  key: string;
  label: string;
  outcome?: "approved" | "denied";
  opens_signature?: boolean;
}

export interface Catalog {
  modalities: { key: Modality; label: string }[];
  statuses: Record<Modality, ClientStatusDef[]>;
  sla_days: number;
  commercials: { id: string; name: string; is_active: boolean }[];
  one7_results: Record<string, string>;
  one7_analysis_types: Record<string, string>;
  situations: Record<Situation, string>;
}

export type Situation = "andamento" | "concluido" | "negado" | "atrasado";

export interface Followup {
  date: string;
  note: string;
  kind: "documentacao" | "assinatura";
}

export interface PortfolioClient {
  id: string;
  external_id: string | null;
  modality: Modality;
  name: string;
  commercial: { id: string; name: string } | null;
  status: string;
  status_label: string;
  entry_date: string | null;
  pre_committee_date: string | null;
  committee_date: string | null;
  contract_issued_date: string | null;
  signature_completed_date: string | null;
  notes: string;
  risk_exit: boolean;
  limit_expired: boolean;
  milestones: Record<string, Record<string, boolean>>;
  extra: { resultado_comite?: string; tipo_analise?: string | null; data_envio_comite?: string | null; em_triagem?: boolean };
  followups: Followup[];
  status_history: { status: string; at: string; label: string }[];
  legacy_history?: { at: string | null; user: string; text: string }[];
  source: "manual" | "import";
  created_at: string;
  updated_at: string;
  imported_at: string | null;
  situation?: Situation;
  days_in_status?: number | null;
  total_days?: number | null;
  total_days_open?: boolean;
  signature_days?: number | null;
  signature_open?: boolean;
  registrations?: { id: string; code: string; status: RegStatus }[];
  signature_trackings?: string[];
}

export interface CommercialRow {
  id: string;
  name: string;
  is_active: boolean;
  clients: number;
  by_modality: Partial<Record<Modality, number>>;
}

export interface ClientRef {
  id: string;
  name: string;
  modality: Modality;
  status_label: string;
  days_in_status: number | null;
  commercial: string | null;
}

export interface SignatureKpis {
  avg_signature_days: number | null;
  avg_signature_days_sec: number | null;
  avg_signature_days_fidc: number | null;
  signed_basis: number;
  in_process: number;
  avg_open_days: number | null;
  oldest_open_days: number | null;
  signed: number;
  not_issued: number;
  followups: number;
  companies: number;
}

export interface CommercialStats {
  id: string | null;
  name: string;
  total: number;
  approved: number;
  denied: number;
  in_progress: number;
  overdue: number;
  risk_exit: number;
  limit_expired: number;
  approval_rate: number | null;
  avg_days_to_approved: number | null;
  share: number;
}

export interface ReportRow {
  id: string;
  name: string;
  modality: Modality;
  commercial: string | null;
  status: string;
  status_label: string;
  situation: Situation;
  entry_date: string | null;
  pre_committee_date: string | null;
  committee_date: string | null;
  signature_issued: string | null;
  signature_completed: string | null;
  approved_at: string | null;
  total_days: number | null;
  total_days_open: boolean;
  signature_days: number | null;
  signature_open: boolean;
  days_in_status: number | null;
  risk_exit: boolean;
  limit_expired: boolean;
  notes: string;
}

export interface PortfolioSummary {
  modality: Scope;
  modality_label: string;
  filtered: boolean;
  population: number;
  generated_at: string;
  generated_by: string;
  sla_days: number;
  kpis: {
    total_clients: number;
    approved: number;
    denied: number;
    in_progress: number;
    overdue: number;
    approval_rate: number | null;
    avg_days_to_approved: number | null;
    avg_days_to_approved_basis: number;
    avg_signature_days_clients: number | null;
    avg_signature_days_clients_basis: number;
    risk_exit: number;
    limit_expired: number;
    commercials: number;
    top_commercial: { name: string; total: number } | null;
  };
  signatures: SignatureKpis;
  by_status: { modality: Modality; key: string; label: string; outcome: string | null; count: number }[];
  by_commercial: CommercialStats[];
  by_month: { month: string; count: number }[];
  by_situation: Record<Situation, number>;
  stalled: ClientRef[];
  over_sla: ClientRef[];
  risk_exit: ClientRef[];
  limit_expired: ClientRef[];
  rows?: ReportRow[];
}

export type ContractState = "sem_emissao" | "aguardando" | "assinado";

export interface SignatureContract {
  kind: "SEC" | "FIDC";
  process_number: string;
  created_date: string | null;
  issued_date: string | null;
  signed_date: string | null;
  days: number | null;
  state: ContractState;
}

export interface SignatureRow {
  id: string;
  external_id: string | null;
  company_name: string;
  modality: Modality;
  commercial: { id: string; name: string } | null;
  client: { id: string; name: string; status: string; status_label: string } | null;
  auto_created: boolean;
  contracts: SignatureContract[];
  state: ContractState | "parcial";
  waiting_days: number | null;
  oldest_pending_issue: string | null;
  last_signed: string | null;
  followups: Followup[];
  created_at: string;
  updated_at: string;
}

export interface ImportIssue {
  entity: string;
  level: "error" | "warning";
  message: string;
  ref: string | null;
  name: string | null;
}

export type ImportAction = "create" | "update" | "unchanged" | "skipped" | "rejected";

export interface ImportPlan {
  file: { name: string; sha256: string; version: number | null; exported_at: string | null; previously_imported_at: string | null };
  clients: Record<ImportAction, number>;
  signatures: Record<ImportAction, number>;
  commercials: { create: number; names: string[] };
  statuses: { added: { key: string; label: string }[]; relabeled: { key: string; from: string; to: string }[] };
  errors: number;
  warnings: number;
  issues: ImportIssue[];
  preview?: {
    clients: { action: ImportAction; external_id: string | null; reason: string | null; modality?: Modality; name?: string; commercial?: string | null; status_label?: string; entry_date?: string | null }[];
    signatures: { action: ImportAction; external_id: string | null; reason: string | null; name?: string; commercial?: string | null; linked?: boolean }[];
  };
}
