import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { Dialog, errorText, useToast } from "./ui";

export interface DeletableDocument {
  id: string;
  original_filename: string;
  status: string;
}

/** Deletes a file sent by mistake, in the wrong version or twice, with a reason kept in the audit trail. */
export function DeleteDocument({ d, onClose, onDone }: { d: DeletableDocument; onClose: () => void; onDone?: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [reason, setReason] = useState("");
  const busy = d.status === "queued" || d.status === "processing";
  const del = useMutation({
    mutationFn: () => api(`/api/documents/${d.id}/delete`, { method: "POST", json: { reason } }),
    onSuccess: () => {
      for (const k of ["registration", "registrations", "dashboard", "inbox"]) qc.invalidateQueries({ queryKey: [k] });
      toast(`Documento excluído: ${d.original_filename}`);
      onClose();
      onDone?.();
    },
  });
  return (
    <Dialog title="Excluir este documento?" onClose={onClose}>
      {busy ? (
        <>
          <p className="muted">O documento ainda está sendo analisado. Espere terminar para excluir.</p>
          <div className="dialog-actions"><button className="btn btn-ghost" onClick={onClose}>Fechar</button></div>
        </>
      ) : (
        <form className="form-grid" onSubmit={(e) => { e.preventDefault(); del.mutate(); }}>
          <p className="muted">
            O arquivo <span className="strong">{d.original_filename}</span> e tudo o que foi lido dele (campos, pontos e observações) são apagados de vez.
            O checklist do cadastro é refeito sem ele. Use para arquivos enviados por engano, na versão errada ou repetidos.
          </p>
          <label className="label"><span>Motivo (fica na auditoria)</span>
            <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Ex.: enviado duas vezes" autoFocus /></label>
          {del.isError && <p className="form-error">{errorText(del.error)}</p>}
          <div className="dialog-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancelar</button>
            <button className="btn btn-danger" disabled={reason.trim().length < 5 || del.isPending}>{del.isPending ? "Excluindo…" : "Excluir de vez"}</button>
          </div>
        </form>
      )}
    </Dialog>
  );
}
