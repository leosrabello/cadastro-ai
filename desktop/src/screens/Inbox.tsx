import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { DocumentBrief, ExtractedField, Page, RegistrationRow } from "../api/types";
import { useAuth, usePerm } from "../auth";
import { Empty, ErrorBox, LoadingRows, Mark, errorText, useToast } from "../components/ui";
import { fmtBytes, fmtTaxId, relative } from "../lib/format";
import "./inbox.css";

interface InboxDoc extends DocumentBrief {
  ingest_note: string | null;
  suggested_registration: RegistrationRow | null;
  fields: ExtractedField[];
}
interface InboxData {
  documents: InboxDoc[];
  ingest_problems: { id: string; source_ref: string; status: string; detail: string | null; size_bytes: number; created_at: string }[];
}

const PROBLEM: Record<string, string> = { rejected: "Recusado", failed: "Falhou", duplicate: "Duplicado" };

export function Inbox() {
  const q = useQuery({ queryKey: ["inbox"], queryFn: () => api<InboxData>("/api/inbox"), refetchInterval: 10_000 });
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Caixa de entrada</h1>
          <p className="muted">Arquivos que chegaram pela pasta monitorada sem um cadastro identificável. Associe cada um ao cadastro certo.</p>
        </div>
      </div>
      {q.isError ? <ErrorBox error={q.error} retry={() => q.refetch()} /> : !q.data ? <LoadingRows /> : (
        <>
          {q.data.documents.length === 0 ? (
            <Empty title="Nada esperando associação">
              Arquivos com o código do cadastro no nome (ou numa subpasta com o código) entram direto no cadastro certo.
            </Empty>
          ) : (
            <div className="inbox-list enter">
              {q.data.documents.map((d, i) => <InboxItem key={d.id} d={d} i={i} />)}
            </div>
          )}
          {q.data.ingest_problems.length > 0 && (
            <section style={{ marginTop: 48 }}>
              <h2 style={{ marginBottom: 4 }}>Arquivos não aceitos na pasta</h2>
              <p className="meta" style={{ marginBottom: 12 }}>Recusados ficam em _falhas e duplicados em _duplicados, cada um com um arquivo .motivo.txt ao lado.</p>
              <div className="table-scroll"><table className="table">
                <thead><tr><th>Arquivo</th><th>Resultado</th><th>Motivo</th><th>Quando</th></tr></thead>
                <tbody>
                  {q.data.ingest_problems.map((p) => (
                    <tr key={p.id}>
                      <td>{p.source_ref}<div className="meta">{fmtBytes(p.size_bytes)}</div></td>
                      <td><Mark tone={p.status === "duplicate" ? "muted" : "danger"}>{PROBLEM[p.status] ?? p.status}</Mark></td>
                      <td>{p.detail}</td>
                      <td className="meta num">{relative(p.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function InboxItem({ d, i }: { d: InboxDoc; i: number }) {
  const qc = useQueryClient();
  const toast = useToast();
  const perm = usePerm();
  const { meta } = useAuth();
  const [search, setSearch] = useState("");
  const results = useQuery({
    queryKey: ["reg-search", search],
    queryFn: () => api<Page<RegistrationRow>>(`/api/registrations?q=${encodeURIComponent(search)}&page_size=5&status=awaiting_processing,processing,awaiting_review,pending_documents,processing_failed`),
    enabled: search.trim().length >= 2,
  });
  const associate = useMutation({
    mutationFn: (rid: string) => api(`/api/documents/${d.id}/associate`, { method: "POST", json: { registration_id: rid } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inbox"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast("Documento associado ao cadastro.");
    },
    onError: (e) => toast(errorText(e), "danger"),
  });
  const read = d.fields.filter((f) => f.value);
  return (
    <article className="inbox-item" style={{ ["--i" as string]: Math.min(i, 8) }}>
      <div className="inbox-doc">
        <Link to={`/documentos/${d.id}`} className="strong">{d.original_filename}</Link>
        <span className="meta">
          {d.doc_type ? meta?.document_types[d.doc_type]?.label : d.status === "processed" ? "Tipo não identificado" : "Em análise"} · chegou {relative(d.received_at)} · {d.source_ref}
        </span>
        {read.length > 0 && <span className="inbox-read">{read.map((f) => `${f.label}: ${f.value}`).join(" · ")}</span>}
        {d.ingest_note && <span className="meta">{d.ingest_note}</span>}
      </div>
      {perm.operate && (
        <div className="inbox-assoc">
          {d.suggested_registration && (
            <div className="suggestion">
              <span className="meta">O CPF/CNPJ lido confere com</span>
              <span className="strong">{d.suggested_registration.subject_name}</span>
              <span className="meta num">{d.suggested_registration.code} · {fmtTaxId(d.suggested_registration.tax_id)}</span>
              <button className="btn btn-primary btn-sm" onClick={() => associate.mutate(d.suggested_registration!.id)} disabled={associate.isPending}>Associar a este cadastro</button>
            </div>
          )}
          <input className="input" placeholder={d.suggested_registration ? "Ou busque outro cadastro" : "Buscar cadastro por nome, código ou CPF/CNPJ"} value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Buscar cadastro para associar" />
          {results.data && (
            <ul className="assoc-results">
              {results.data.items.length === 0 && <li className="meta">Nenhum cadastro aberto encontrado.</li>}
              {results.data.items.map((r) => (
                <li key={r.id}>
                  <button className="assoc-btn" onClick={() => associate.mutate(r.id)}>
                    <span>{r.subject_name}</span>
                    <span className="meta num">{r.code}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </article>
  );
}
