import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Evidence, Finding } from "../api/types";
import { usePerm } from "../auth";
import { FINDING_STATUS, SOURCE, fmtDateTime, pct } from "../lib/format";
import { Dialog, SeverityMark, errorText, useToast } from "./ui";

type Action = "accept" | "escalate" | "override" | "reopen";

const ACTION_COPY: Record<Action, { title: string; button: string; hint: string; min: number }> = {
  accept: { title: "Marcar como não problemático", button: "Confirmar", hint: "Explique por que este ponto não impede o cadastro.", min: 10 },
  escalate: { title: "Escalar para supervisão", button: "Escalar", hint: "Diga o que o supervisor precisa olhar.", min: 10 },
  override: { title: "Sobrepor o resultado da regra", button: "Sobrepor", hint: "A justificativa fica registrada na trilha de auditoria.", min: 20 },
  reopen: { title: "Reabrir ponto", button: "Reabrir", hint: "Opcional.", min: 0 },
};

export function FindingCard({ f, onEvidence, compact, closed }: { f: Finding; onEvidence?: (e: Evidence) => void; compact?: boolean; closed?: boolean }) {
  const perm = usePerm();
  const [action, setAction] = useState<Action | null>(null);
  const isOpen = f.status === "open" || f.status === "escalated";
  const canAccept = perm.operate && (perm.override || !["high", "critical"].includes(f.severity));
  return (
    <article className="finding" data-severity={f.severity} data-status={f.status}>
      <header className="finding-head">
        <SeverityMark severity={f.severity} />
        <h3>{f.title}</h3>
        <span className="meta">{SOURCE[f.source] ?? f.source}</span>
      </header>
      <p className="finding-why">{f.explanation}</p>
      {f.evidence.length > 0 && (
        <ul className="evidence">
          {f.evidence.map((e, i) => (
            <li key={i}>
              <span className="meta">{e.label}</span>
              <EvidenceValue e={e} onEvidence={onEvidence} />
              {e.note && <span className="meta">{e.note}</span>}
            </li>
          ))}
        </ul>
      )}
      {!compact && (f.confidence_basis || f.confidence !== null) && (
        <p className="meta finding-basis">
          {f.confidence !== null && <>Indicador {pct(f.confidence)}. </>}
          {f.confidence_basis}
        </p>
      )}
      {isOpen && f.recommended_action && <p className="finding-next">{f.recommended_action}</p>}
      {!isOpen && (
        <p className="meta">
          {FINDING_STATUS[f.status]}
          {f.resolved_by && ` por ${f.resolved_by.name}`}
          {f.resolved_at && `, ${fmtDateTime(f.resolved_at)}`}
          {f.resolution_note && `: “${f.resolution_note}”`}
        </p>
      )}
      {f.status === "escalated" && f.resolution_note && <p className="meta">Escalado: “{f.resolution_note}”</p>}
      {!closed && perm.operate && (
        <div className="finding-actions">
          {isOpen && canAccept && <button className="btn btn-sm" onClick={() => setAction("accept")}>Não é problema</button>}
          {f.status === "open" && <button className="btn btn-sm" onClick={() => setAction("escalate")}>Escalar</button>}
          {isOpen && perm.override && f.source !== "human" && <button className="btn btn-sm btn-ghost" onClick={() => setAction("override")}>Sobrepor regra</button>}
          {!isOpen && perm.override && <button className="btn btn-sm btn-ghost" onClick={() => setAction("reopen")}>Reabrir</button>}
        </div>
      )}
      {action && <ResolveDialog f={f} action={action} onClose={() => setAction(null)} />}
    </article>
  );
}

function EvidenceValue({ e, onEvidence }: { e: Evidence; onEvidence?: (e: Evidence) => void }) {
  const text = e.value ?? (e.bbox ? "Ver região no documento" : "—");
  if (e.document_id && onEvidence) {
    return (
      <button className="link-btn evidence-value" onClick={() => onEvidence(e)}>
        {text}
        {e.page !== null && <span className="meta"> · pág. {e.page + 1}</span>}
      </button>
    );
  }
  if (e.document_id) {
    const q = new URLSearchParams();
    if (e.page !== null) q.set("pagina", String(e.page));
    if (e.bbox) q.set("regiao", e.bbox.join(","));
    return (
      <Link className="evidence-value" to={`/documentos/${e.document_id}?${q}`}>
        {text}
      </Link>
    );
  }
  return <span className="evidence-value">{text}</span>;
}

function ResolveDialog({ f, action, onClose }: { f: Finding; action: Action; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [note, setNote] = useState("");
  const copy = ACTION_COPY[action];
  const m = useMutation({
    mutationFn: () => api<Finding>(`/api/findings/${f.id}/resolve`, { method: "POST", json: { action, note } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registration"] });
      qc.invalidateQueries({ queryKey: ["document"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast(action === "escalate" ? "Ponto escalado para supervisão." : "Registrado.");
      onClose();
    },
  });
  return (
    <Dialog title={copy.title} onClose={onClose}>
      <p className="muted" style={{ marginBottom: 14 }}>{f.title}</p>
      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
        <label className="label">
          <span>{copy.hint}</span>
          <textarea className="textarea" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        {copy.min > 0 && <span className="meta num">{note.trim().length} de no mínimo {copy.min} caracteres</span>}
        {m.isError && <p className="form-error">{errorText(m.error)}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" disabled={m.isPending || note.trim().length < copy.min}>{copy.button}</button>
        </div>
      </form>
    </Dialog>
  );
}
