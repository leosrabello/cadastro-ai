import type { ChecklistItem, RegStatus, Severity, Validity } from "../api/types";

/** Shown in data cells that have no value. */
export const EMPTY = "—";

export const STATUS: Record<RegStatus, { label: string; tone: string }> = {
  awaiting_processing: { label: "Aguardando documentos", tone: "hollow" },
  processing: { label: "Em análise automática", tone: "muted" },
  awaiting_review: { label: "Aguardando revisão", tone: "ink" },
  approved: { label: "Aprovado", tone: "accent" },
  pending_documents: { label: "Pendente de documentos", tone: "warn" },
  rejected: { label: "Reprovado", tone: "danger" },
  processing_failed: { label: "Falha no processamento", tone: "danger" },
};

export const SEVERITY: Record<Severity, { label: string; tone: string }> = {
  critical: { label: "Crítico", tone: "danger" },
  high: { label: "Alto", tone: "danger" },
  medium: { label: "Médio", tone: "warn" },
  low: { label: "Baixo", tone: "muted" },
  info: { label: "Informativo", tone: "hollow" },
};

export const SOURCE: Record<string, string> = {
  rule: "Regra",
  forensics: "Análise do arquivo",
  ai: "IA",
  system: "Sistema",
  human: "Revisor",
  pdf_text: "Texto do PDF",
  ocr: "OCR",
};

export const FINDING_STATUS: Record<string, string> = {
  open: "Em aberto",
  accepted: "Aceito pelo revisor",
  escalated: "Escalado",
  overridden: "Regra sobreposta",
  superseded: "Não se aplica mais",
  note: "Observação, sem ação necessária",
};

export const VALIDITY: Record<Validity["state"], { label: string; tone: string }> = {
  valid: { label: "Dentro da validade", tone: "accent" },
  no_expiry: { label: "Não expira", tone: "ink" },
  expired: { label: "Vencido", tone: "danger" },
  too_old: { label: "Emitido há tempo demais", tone: "danger" },
  invalid: { label: "Situação inválida", tone: "danger" },
  unknown: { label: "Validade não determinada", tone: "warn" },
  contradictory: { label: "Datas contraditórias", tone: "warn" },
};

export const CHECK_STATE: Record<ChecklistItem["state"], { label: string; tone: string }> = {
  ok: { label: "Recebido e conferido", tone: "accent" },
  missing: { label: "Falta", tone: "danger" },
  unclassified: { label: "Recebido sem tipo identificado", tone: "warn" },
  processing: { label: "Em análise", tone: "muted" },
  failed: { label: "Falha na análise", tone: "danger" },
  expired: { label: "Vencido", tone: "danger" },
  too_old: { label: "Emitido há tempo demais", tone: "danger" },
  invalid: { label: "Situação inválida", tone: "danger" },
  needs_review: { label: "Precisa de conferência", tone: "warn" },
  optional: { label: "Se aplicável", tone: "hollow" },
};

export const ACTIONS: Record<string, string> = {
  "auth.login": "Entrou no sistema",
  "auth.logout": "Saiu do sistema",
  "auth.login_failed": "Tentativa de acesso recusada",
  "auth.password_changed": "Trocou a senha",
  "registration.created": "Criou o cadastro",
  "registration.updated": "Editou o cadastro",
  "registration.viewed": "Abriu o cadastro",
  "registration.report_generated": "Gerou o relatório de análise",
  "registration.status_changed": "Situação alterada",
  "registration.approve": "Aprovou",
  "registration.reject": "Reprovou",
  "registration.request_documents": "Solicitou documentos",
  "registration.escalate": "Escalou para supervisão",
  "registration.reopen": "Reabriu",
  "registration.reanalyzed": "Pediu nova análise",
  "registration.exported": "Exportou dados do titular",
  "registration.purged": "Expurgou dados",
  "registration.legal_hold": "Alterou retenção legal",
  "document.ingested": "Recebeu documento",
  "document.rejected": "Recusou arquivo",
  "document.processed": "Análise automática concluída",
  "document.processing_failed": "Falha na análise automática",
  "document.viewed": "Abriu documento",
  "document.downloaded": "Baixou o original",
  "document.reprocess_requested": "Pediu nova análise do documento",
  "document.classified": "Classificou o documento",
  "document.associated": "Associou documento ao cadastro",
  "field.confirmed": "Confirmou campo",
  "field.corrected": "Corrigiu campo",
  "finding.accept": "Aceitou ponto",
  "finding.escalate": "Escalou ponto",
  "finding.override": "Sobrepôs regra",
  "finding.reopen": "Reabriu ponto",
  "settings.updated": "Alterou configuração",
  "user.created": "Criou usuário",
  "user.updated": "Alterou usuário",
};

export const ROLES: Record<string, string> = {
  analyst: "Analista",
  supervisor: "Supervisor",
  admin: "Administrador",
  auditor: "Auditor",
};

const dateFmt = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });
const timeFmt = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return EMPTY;
  const d = iso.length === 10 ? new Date(iso + "T12:00:00") : new Date(iso);
  return dateFmt.format(d);
}

export function fmtTime(iso: string): string {
  return timeFmt.format(new Date(iso));
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return EMPTY;
  return `${fmtDate(iso)} às ${fmtTime(iso)}`;
}

export function relative(iso: string | null | undefined): string {
  if (!iso) return EMPTY;
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "agora";
  if (s < 3600) return `há ${Math.round(s / 60)} min`;
  if (s < 86400) return `há ${Math.round(s / 3600)} h`;
  const d = Math.round(s / 86400);
  return d === 1 ? "ontem" : `há ${d} dias`;
}

export function fmtTaxId(v: string | null): string {
  if (!v) return EMPTY;
  if (v.length === 11) return `${v.slice(0, 3)}.${v.slice(3, 6)}.${v.slice(6, 9)}-${v.slice(9)}`;
  if (v.length === 14) return `${v.slice(0, 2)}.${v.slice(2, 5)}.${v.slice(5, 8)}/${v.slice(8, 12)}-${v.slice(12)}`;
  return v;
}

function summarizeJson(name: string, value: string): string | null {
  try {
    const v = JSON.parse(value);
    if (name === "faturamento_mensal") {
      return Object.entries(v.years as Record<string, Record<string, number>>)
        .sort(([a], [b]) => b.localeCompare(a))
        .map(([y, m]) => `${y}: ${plural(Object.keys(m).length, "mês", "meses")}`)
        .join("; ");
    }
    if (name === "endividamento_itens") return (v as { instituicao: string }[]).map((i) => i.instituicao).join(", ");
    if (name === "concentracao_clientes") {
      return (v as { cliente: string; percentual: number }[]).slice(0, 3).map((r) => `${r.cliente} ${String(r.percentual).replace(".", ",")}%`).join("; ");
    }
  } catch {
    return null;
  }
  return null;
}

export function fmtFieldValue(name: string, value: string | null): string {
  if (!value) return EMPTY;
  if (value.startsWith("{") || value.startsWith("[")) return summarizeJson(name, value) ?? value;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value) && (name.startsWith("data_") || name === "validade")) return fmtDate(value);
  return value;
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1).replace(".", ",")} MB`;
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? EMPTY : `${Math.round(v * 100)}%`;
}

export function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}
