import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { Decision, DocumentBrief, Finding, InfoItem, RegistrationDetail as R } from "../api/types";
import { useAuth, usePerm } from "../auth";
import { FindingCard } from "../components/FindingCard";
import { UploadZone } from "../components/Upload";
import { Dialog, ErrorBox, Mark, Skeleton, StatusMark, errorText, useToast } from "../components/ui";
import { ACTIONS, CHECK_STATE, VALIDITY, fmtDate, fmtDateTime, fmtFieldValue, fmtTaxId, plural, relative } from "../lib/format";
import "./detail.css";

const SEV_ORDER = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };

export function RegistrationDetail() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const { meta } = useAuth();
  const perm = usePerm();
  const [deciding, setDeciding] = useState<Decision["action"] | null>(null);
  const [showClosed, setShowClosed] = useState(false);

  const q = useQuery({
    queryKey: ["registration", id],
    queryFn: () => api<R>(`/api/registrations/${id}`),
    refetchInterval: (query) => {
      const d = query.state.data;
      return d && (d.checklist.processing || d.documents.some((x) => x.status === "queued" || x.status === "processing")) ? 2500 : 20_000;
    },
  });

  const findings = useMemo(() => {
    const all = q.data?.findings ?? [];
    const open = all.filter((f) => f.status === "open" || f.status === "escalated").sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity]);
    const closed = all.filter((f) => !(f.status === "open" || f.status === "escalated"));
    return { open, closed };
  }, [q.data]);

  if (q.isError) {
    return (
      <div className="page">
        <ErrorBox error={q.error} retry={(q.error as ApiError)?.status === 404 ? undefined : () => q.refetch()} />
      </div>
    );
  }
  const r = q.data;
  if (!r) return <div className="page"><Skeleton h={40} w={420} /><div style={{ height: 24 }} /><Skeleton h={360} /></div>;

  const final = r.status === "approved" || r.status === "rejected";
  const closed = r.status === "rejected";
  const docTypes = meta?.document_types ?? {};
  const docName = (d: DocumentBrief) => (d.doc_type ? docTypes[d.doc_type]?.label ?? d.doc_type : "Tipo não identificado");

  return (
    <div className="page detail">
      <div className="detail-head enter">
        <div style={{ ["--i" as string]: 0 }}>
          <Link to="/cadastros" className="meta">Cadastros</Link>
          <h1>{r.subject_name}</h1>
          <p className="detail-sub">
            <StatusMark status={r.status} />
            <span className="num">{r.code}</span>
            <span>{meta?.profiles[r.kind]?.label ?? r.kind}</span>
            <span className="num">{fmtTaxId(r.tax_id)}</span>
            <span className="muted">Criado {relative(r.created_at)}{r.created_by ? ` por ${r.created_by.name}` : ""}</span>
          </p>
        </div>
        {(
          <div className="decide-bar" style={{ ["--i" as string]: 1 }}>
            <Link className="btn btn-ghost" to={`/cadastros/${r.id}/relatorio`}>Relatório da análise</Link>
            {perm.operate && !final && (
              <>
                {perm.reject && <button className="btn btn-danger" onClick={() => setDeciding("reject")}>Reprovar</button>}
                <button className="btn" onClick={() => setDeciding("escalate")}>Escalar</button>
                <button className="btn" onClick={() => setDeciding("request_documents")}>Solicitar documentos</button>
                {perm.approve && (
                  <button className="btn btn-primary" onClick={() => setDeciding("approve")} disabled={!!r.checklist.processing}>
                    Aprovar
                  </button>
                )}
              </>
            )}
            {perm.operate && (final || r.status === "pending_documents") && perm.override && <button className="btn" onClick={() => setDeciding("reopen")}>Reabrir</button>}
          </div>
        )}
      </div>

      {r.status === "approved" || r.status === "rejected" || r.status === "pending_documents" ? (
        <div className="decision-note" data-status={r.status}>
          <strong>{r.status === "approved" ? (r.checklist.stages?.length ? "Aprovado em comitê" : "Aprovado") : r.status === "rejected" ? "Reprovado" : "Documentos solicitados"}</strong>
          {r.decided_by && ` por ${r.decided_by.name}`} {r.decisions[0] && `em ${fmtDateTime(r.decisions[0].decided_at)}`}
          {r.decision_reason && <span>: “{r.decision_reason}”</span>}
          {r.status === "pending_documents" && r.decisions[0]?.requested_items.length ? <span> Solicitado: {r.decisions[0].requested_items.join("; ")}.</span> : null}
        </div>
      ) : null}

      <div className="detail-grid">
        <aside className="slip-col">
          <Slip r={r} />
        </aside>

        <div className="detail-main">
          <section aria-labelledby="docs-h">
            <div className="spread section-head">
              <h2 id="docs-h">Documentos</h2>
              <span className="meta">{plural(r.documents.length, "arquivo", "arquivos")}</span>
            </div>
            {perm.operate && <UploadZone registrationId={r.id} disabled={closed} />}
            {r.documents.length > 0 && (
              <table className="table docs-table">
                <thead>
                  <tr><th>Documento</th><th>Validade</th><th>Análise</th><th>Recebido</th></tr>
                </thead>
                <tbody>
                  {r.documents.map((d) => (
                    <tr key={d.id} className="clickable" onClick={() => nav(`/documentos/${d.id}`)}>
                      <td>
                        <a className="strong" href={`#/documentos/${d.id}`} onClick={(e) => e.stopPropagation()}>{docName(d)}</a>
                        <div className="meta">{d.original_filename}{d.issuer ? ` · ${d.issuer}` : ""}</div>
                      </td>
                      <td>{d.validity ? <Mark tone={VALIDITY[d.validity.state].tone}>{VALIDITY[d.validity.state].label}</Mark> : <span className="muted">—</span>}</td>
                      <td><DocState d={d} /></td>
                      <td className="meta num">{fmtDate(d.received_at)}<div>{d.source === "shared_folder" ? "Pasta monitorada" : "Envio manual"}</div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section aria-labelledby="findings-h">
            <div className="spread section-head">
              <h2 id="findings-h">Pontos a conferir</h2>
              <span className="meta">{findings.open.length ? plural(findings.open.length, "em aberto", "em aberto") : "Nenhum em aberto"}</span>
            </div>
            {findings.open.length === 0 ? (
              <p className="muted quiet-note">
                {r.documents.length === 0 ? "Os pontos aparecem quando os documentos forem analisados." : "Nada em aberto. Confira a ficha ao lado antes de decidir."}
              </p>
            ) : (
              <div className="stack enter">
                {findings.open.map((f, i) => (
                  <div key={f.id} style={{ ["--i" as string]: Math.min(i, 8) }}>
                    <FindingCard f={f} closed={closed} />
                  </div>
                ))}
              </div>
            )}
            {findings.closed.length > 0 && (
              <div style={{ marginTop: 14 }}>
                <button className="link-btn meta" onClick={() => setShowClosed((v) => !v)}>
                  {showClosed ? "Esconder" : "Mostrar"} {plural(findings.closed.length, "ponto resolvido", "pontos resolvidos")}
                </button>
                {showClosed && <div className="stack" style={{ marginTop: 10 }}>{findings.closed.map((f: Finding) => <FindingCard key={f.id} f={f} compact closed={closed} />)}</div>}
              </div>
            )}
          </section>

          <section aria-labelledby="trail-h">
            <div className="spread section-head">
              <h2 id="trail-h">Trilha do cadastro</h2>
              {perm.audit && <Link className="meta" to={`/historico?cadastro=${r.id}`}>Ver no histórico completo</Link>}
            </div>
            <ol className="trail">
              {r.history.slice(0, 40).map((e) => (
                <li key={e.id}>
                  <span className="meta num">{fmtDateTime(e.at)}</span>
                  <span>
                    {ACTIONS[e.action] ?? e.action}
                    {e.details?.reason ? <span className="muted">: “{String(e.details.reason)}”</span> : null}
                    {e.details?.field ? <span className="muted">, {meta?.field_labels[e.details.field] ?? e.details.field}</span> : null}
                    {e.details?.filename ? <span className="muted">, {String(e.details.filename)}</span> : null}
                  </span>
                  <span className="meta">{e.actor}</span>
                </li>
              ))}
            </ol>
          </section>
        </div>
      </div>
      {deciding && <DecisionDialog r={r} action={deciding} onClose={() => setDeciding(null)} />}
    </div>
  );
}

function DocState({ d }: { d: DocumentBrief }) {
  if (d.status === "queued" || d.status === "processing") return <Mark tone="muted">{d.status === "queued" ? "Na fila" : "Lendo o documento"}</Mark>;
  if (d.status === "failed") return <span className="danger-text">Falhou: {d.processing_error?.split(":")[0]}</span>;
  if (d.status === "purged") return <span className="muted">Expurgado</span>;
  return <Mark tone="ink">Concluída{d.ai_status === "done" ? " com IA" : ""}</Mark>;
}

function Slip({ r }: { r: R }) {
  const { meta } = useAuth();
  const docs = r.checklist.documents ?? [];
  const fields = r.checklist.fields ?? [];
  const info = r.checklist.info ?? [];
  const stages = r.checklist.stages ?? [];
  const [stage, setStage] = useState<string | null>(r.checklist.stage ?? null);
  const [editing, setEditing] = useState<InfoItem | null>(null);
  useEffect(() => setStage(r.checklist.stage ?? null), [r.checklist.stage]);
  const shown = stages.length ? docs.filter((d) => d.stage === stage) : docs;
  const shownInfo = stages.length ? info.filter((i) => i.stage === stage) : info;
  const groups = [...new Set(shown.map((d) => d.group ?? ""))];
  const pending = docs.filter((d) => d.blocking && d.required !== false && d.state !== "ok").length
    + info.filter((i) => i.blocking && i.state !== "ok").length + fields.filter((f) => f.state !== "ok").length;
  const closed = r.status === "rejected";
  return (
    <div className="paper slip enter">
      <div className="slip-head" style={{ ["--i" as string]: 0 }}>
        <h2>Ficha de conferência</h2>
        <span className="meta">{meta?.profiles[r.kind]?.label}</span>
      </div>
      {stages.length > 0 && (
        <div className="slip-stages" role="tablist" aria-label="Etapa">
          {stages.map((s) => (
            <button key={s.id} role="tab" aria-selected={stage === s.id} onClick={() => setStage(s.id)}>
              <span>{s.label}</span>
              <span className="num">{s.done} de {s.total}</span>
            </button>
          ))}
        </div>
      )}
      {stages.find((s) => s.id === stage)?.note && <p className="meta slip-stage-note">{stages.find((s) => s.id === stage)!.note}</p>}
      {groups.map((g) => (
        <section key={g} className="slip-group">
          {g && <p className="slip-group-name">{g}</p>}
          <ul className="slip-list">
            {shown.filter((d) => (d.group ?? "") === g).map((item) => (
              <li key={item.id}>
                <span className="slip-label">{item.label}</span>
                <span className="mark" data-tone={CHECK_STATE[item.state].tone}>
                  {CHECK_STATE[item.state].label}
                  {item.per_partner && item.received ? `, ${plural(item.received, "recebido", "recebidos")}` : ""}
                </span>
                {item.state_note && <span className="meta">{item.state_note[0].toUpperCase() + item.state_note.slice(1)}.</span>}
                {item.documents && item.documents.length > 0 ? (
                  <span className="slip-docs">
                    {item.documents.map((d) => <Link key={d.id} className="meta" to={`/documentos/${d.id}`}>{d.name}</Link>)}
                  </span>
                ) : (
                  item.note && <span className="meta">{item.note}</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
      {shownInfo.length > 0 && (
        <section className="slip-group">
          <p className="slip-group-name">{shownInfo[0].group ?? "Informações"}</p>
          <ul className="slip-list">
            {shownInfo.map((i) => (
              <li key={i.id}>
                <span className="slip-label">{i.label}</span>
                {i.value ? <span>{i.value}</span> : <span className="mark" data-tone={i.blocking ? "danger" : "hollow"}>Não informado</span>}
                {!closed && <button className="link-btn meta slip-edit" onClick={() => setEditing(i)}>{i.value ? "Alterar" : "Informar"}</button>}
              </li>
            ))}
          </ul>
        </section>
      )}
      {fields.length > 0 && (stage === null || stage === stages[0]?.id) && (
        <ul className="slip-list slip-fields">
          {fields.map((f) => (
            <li key={f.field}>
              <span className="slip-label">{f.label}</span>
              <span className="mark" data-tone={f.state === "ok" ? "accent" : "danger"}>{f.state === "ok" ? fmtFieldValue(f.field, f.value) : "Não lido"}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="slip-foot">
        {r.status === "rejected" ? (
          <strong>Reprovado{r.decided_at ? ` em ${fmtDate(r.decided_at)}` : ""}.</strong>
        ) : r.checklist.processing ? (
          <span>Análise automática em andamento…</span>
        ) : r.status === "approved" ? (
          <strong>{stages.length ? "Aprovado em comitê" : "Aprovado"}{r.decided_at ? ` em ${fmtDate(r.decided_at)}` : ""}.{pending ? ` ${plural(pending, "item pendente", "itens pendentes")} na formalização.` : ""}</strong>
        ) : r.ready_for_decision ? (
          <strong>Pronto para decisão.</strong>
        ) : (
          <span>
            {pending ? plural(pending, "exigência pendente", "exigências pendentes") : "Exigências atendidas"}
            {r.blocking_findings ? `, ${plural(r.blocking_findings, "ponto grave", "pontos graves")} em aberto` : ""}.
          </span>
        )}
      </div>
      {editing && <InfoDialog r={r} item={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function InfoDialog({ r, item, onClose }: { r: R; item: InfoItem; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [value, setValue] = useState(item.value ?? "");
  const m = useMutation({
    mutationFn: () => api(`/api/registrations/${r.id}`, { method: "PATCH", json: { reference_fields: { ...r.reference_fields, [item.id]: value.trim() } } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registration", r.id] });
      toast("Informação registrada.");
      onClose();
    },
  });
  return (
    <Dialog title={item.label} onClose={onClose}>
      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
        <label className="label">
          <span>{item.hint ?? "Valor"}</span>
          <textarea className="textarea" value={value} onChange={(e) => setValue(e.target.value)} />
        </label>
        {m.isError && <p className="form-error">{errorText(m.error)}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" disabled={m.isPending || !value.trim()}>Salvar</button>
        </div>
      </form>
    </Dialog>
  );
}

const DECISION_COPY: Record<Decision["action"], { title: string; button: string; reasonLabel: string; min: number }> = {
  approve: { title: "Aprovar cadastro", button: "Aprovar", reasonLabel: "Observação (opcional)", min: 0 },
  reject: { title: "Reprovar cadastro", button: "Reprovar", reasonLabel: "Motivo da reprovação", min: 10 },
  request_documents: { title: "Solicitar documentos", button: "Registrar solicitação", reasonLabel: "Mensagem interna (opcional)", min: 0 },
  escalate: { title: "Escalar para supervisão", button: "Escalar", reasonLabel: "O que o supervisor precisa avaliar", min: 10 },
  reopen: { title: "Reabrir cadastro", button: "Reabrir", reasonLabel: "Motivo da reabertura", min: 10 },
};

function DecisionDialog({ r, action, onClose }: { r: R; action: Decision["action"]; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const perm = usePerm();
  const copy = DECISION_COPY[action];
  const [reason, setReason] = useState("");
  const [blockers, setBlockers] = useState<string[] | null>(null);
  const suggested = (r.checklist.documents ?? []).filter((d) => d.state !== "ok").map((d) => d.label);
  const [items, setItems] = useState<string[]>(suggested);
  const [other, setOther] = useState("");
  const override = blockers !== null;
  const min = override ? 20 : copy.min;

  const m = useMutation({
    mutationFn: () =>
      api<Decision>(`/api/registrations/${r.id}/decisions`, {
        method: "POST",
        json: { action, reason, override, requested_items: action === "request_documents" ? [...items, ...(other.trim() ? [other.trim()] : [])] : [] },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registration", r.id] });
      qc.invalidateQueries({ queryKey: ["registrations"] });
      qc.invalidateQueries({ queryKey: ["queue"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast(`${copy.button}: ${r.code} registrado.`);
      onClose();
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "not_ready" && Array.isArray(e.details)) setBlockers(e.details as string[]);
    },
  });

  return (
    <Dialog title={override ? "Aprovar com pendências" : copy.title} onClose={onClose}>
      <p className="muted" style={{ marginBottom: 14 }}>{r.subject_name} · {r.code}</p>
      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
        {override && (
          <div className="error-box">
            <p style={{ marginBottom: 6 }}>O cadastro ainda tem pendências:</p>
            <ul style={{ margin: 0, paddingLeft: 18 }}>{blockers!.map((b) => <li key={b}>{b}</li>)}</ul>
            {!perm.override && <p style={{ marginTop: 8 }}>Somente supervisores podem aprovar assim. Resolva as pendências ou escale.</p>}
          </div>
        )}
        {action === "request_documents" && (
          <fieldset className="checks">
            <legend className="meta">O que pedir ao cliente</legend>
            {suggested.map((s) => (
              <label key={s} className="row">
                <input type="checkbox" checked={items.includes(s)} onChange={(e) => setItems((xs) => (e.target.checked ? [...xs, s] : xs.filter((x) => x !== s)))} />
                {s}
              </label>
            ))}
            <input className="input" placeholder="Outro documento ou esclarecimento" value={other} onChange={(e) => setOther(e.target.value)} />
          </fieldset>
        )}
        <label className="label">
          <span>{override ? "Justificativa para aprovar com pendências (fica na auditoria)" : copy.reasonLabel}</span>
          <textarea className="textarea" value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        {min > 0 && <span className="meta num">{reason.trim().length} de no mínimo {min} caracteres</span>}
        {m.isError && !(m.error instanceof ApiError && m.error.code === "not_ready") && <p className="form-error">{errorText(m.error)}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button
            className={action === "reject" ? "btn btn-danger" : "btn btn-primary"}
            disabled={m.isPending || reason.trim().length < min || (override && !perm.override) || (action === "request_documents" && !items.length && !other.trim())}
          >
            {override ? "Aprovar mesmo assim" : copy.button}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
