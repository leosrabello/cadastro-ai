import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { Dialog, errorText, useToast } from "./ui";

export interface DeletableRegistration {
  id: string;
  code: string;
  status: string;
  legal_hold?: boolean;
  documents: number | null;
}

/** Deletes a registration sent by mistake, with a reason kept in the audit trail. Approved
 * registrations and those under legal hold stay; the server enforces the same rules. */
export function DeleteRegistration({ r, onClose, onDone }: { r: DeletableRegistration; onClose: () => void; onDone?: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [reason, setReason] = useState("");
  const blocked = r.status === "approved"
    ? "Cadastros aprovados ficam guardados pelo prazo legal (5 anos após o fim do relacionamento). Se foi aprovado por engano, um supervisor precisa reabri-lo antes."
    : r.legal_hold ? "Este cadastro está sob retenção legal. Remova a retenção antes de excluir." : null;
  const del = useMutation({
    mutationFn: () => api(`/api/registrations/${r.id}/delete`, { method: "POST", json: { reason } }),
    onSuccess: () => {
      for (const k of ["registrations", "dashboard", "queue", "registration"]) qc.invalidateQueries({ queryKey: [k] });
      toast(`Cadastro ${r.code} excluído.`);
      onClose();
      onDone?.();
    },
  });
  const docs = r.documents ?? 0;
  return (
    <Dialog title={`Excluir ${r.code}?`} onClose={onClose}>
      {blocked ? (
        <>
          <p className="muted">{blocked}</p>
          <div className="dialog-actions"><button className="btn btn-ghost" onClick={onClose}>Fechar</button></div>
        </>
      ) : (
        <form className="form-grid" onSubmit={(e) => { e.preventDefault(); del.mutate(); }}>
          <p className="muted">
            Apaga de vez o cadastro, {docs === 0 ? "sem documentos" : docs === 1 ? "o documento enviado" : `os ${docs} documentos enviados`}, os pontos e as decisões. Não dá para desfazer.
            O histórico de auditoria guarda só o código e o motivo.
          </p>
          <label className="label"><span>Motivo (fica na auditoria)</span>
            <textarea className="textarea" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Ex.: cadastro duplicado, criado por engano, teste" autoFocus /></label>
          <span className="meta num">{reason.trim().length} de no mínimo 10 caracteres</span>
          {del.isError && <p className="form-error">{errorText(del.error)}</p>}
          <div className="dialog-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancelar</button>
            <button className="btn btn-danger" disabled={reason.trim().length < 10 || del.isPending}>{del.isPending ? "Excluindo…" : "Excluir de vez"}</button>
          </div>
        </form>
      )}
    </Dialog>
  );
}

export function TrashIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="M19 6l-1 14H6L5 6" /><path d="M10 11v6" /><path d="M14 11v6" />
    </svg>
  );
}
