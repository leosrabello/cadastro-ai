import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Catalog, CommercialRow, Followup, Modality, Page, PortfolioClient, Situation } from "../api/types";
import { usePerm } from "../auth";
import { ModalitySwitch, ModalityTag } from "../components/ModalitySwitch";
import { Dialog, Empty, ErrorBox, LoadingRows, Mark, Pager, errorText, useToast } from "../components/ui";
import { fmtDate, fmtDateTime, plural, relative } from "../lib/format";
import { MODALITY_LABEL, useModality } from "../lib/modality";
import { ImportArea } from "./PortfolioImport";
import "./portfolio.css";

export const SITUATION_TONE: Record<Situation, string> = { concluido: "accent", negado: "danger", atrasado: "warn", andamento: "muted" };

export function useCatalog() {
  return useQuery({ queryKey: ["portfolio-catalog"], queryFn: () => api<Catalog>("/api/portfolio/catalog"), staleTime: 60_000 });
}

const TABS = [
  { key: "clientes", label: "Clientes" },
  { key: "comerciais", label: "Comerciais" },
  { key: "importar", label: "Importar dados", supervisor: true },
];

export function Portfolio() {
  const perm = usePerm();
  const [params, setParams] = useSearchParams();
  const tab = params.get("aba") ?? "clientes";
  const setTab = (t: string) => setParams(t === "clientes" ? {} : { aba: t }, { replace: true });
  return (
    <div className="page portfolio">
      <div className="page-head">
        <div>
          <h1>Carteira</h1>
          <p className="muted">As pastas de clientes Normal e One7 no caminho até operar, com os comerciais responsáveis.</p>
        </div>
      </div>
      <div className="segmented settings-tabs" role="tablist">
        {TABS.filter((t) => !t.supervisor || perm.approve || perm.admin).map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} aria-pressed={tab === t.key} onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </div>
      {tab === "clientes" && <Clients />}
      {tab === "comerciais" && <Commercials />}
      {tab === "importar" && <ImportArea />}
    </div>
  );
}

/* ---------------- clients ---------------- */

function Clients() {
  const perm = usePerm();
  const cat = useCatalog();
  const [params, setParams] = useSearchParams();
  const [modality, setModality] = useModality();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [commercial, setCommercial] = useState("");
  const [situation, setSituation] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const open = params.get("cliente");

  useEffect(() => { setStatus(""); setPage(1); }, [modality]);
  const [debounced, setDebounced] = useState("");
  useEffect(() => { const t = setTimeout(() => { setDebounced(search); setPage(1); }, 250); return () => clearTimeout(t); }, [search]);

  const query = new URLSearchParams({ modality, page: String(page), page_size: "50", sort: "entry" });
  if (debounced) query.set("q", debounced);
  if (status) query.set("status", status);
  if (commercial) query.set("commercial_id", commercial);
  if (situation) query.set("situation", situation);
  const q = useQuery({
    queryKey: ["portfolio-clients", query.toString()],
    queryFn: () => api<Page<PortfolioClient>>(`/api/portfolio/clients?${query}`),
    placeholderData: keepPreviousData,
  });
  const statuses = cat.data?.statuses[modality] ?? [];
  const filtered = !!(debounced || status || commercial || situation);

  return (
    <>
      <div className="spread toolbar">
        <div className="row" style={{ flexWrap: "wrap" }}>
          <ModalitySwitch value={modality} onChange={setModality} />
          <input className="input" style={{ width: 240 }} type="search" placeholder="Buscar cliente" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Buscar cliente" />
          <select className="select" style={{ width: 200 }} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Status">
            <option value="">Todos os status</option>
            {statuses.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
          <select className="select" style={{ width: 180 }} value={commercial} onChange={(e) => { setCommercial(e.target.value); setPage(1); }} aria-label="Comercial">
            <option value="">Todos os comerciais</option>
            <option value="none">Sem comercial</option>
            {cat.data?.commercials.map((c) => <option key={c.id} value={c.id}>{c.name}{c.is_active ? "" : " (inativo)"}</option>)}
          </select>
          <select className="select" style={{ width: 160 }} value={situation} onChange={(e) => { setSituation(e.target.value); setPage(1); }} aria-label="Situação">
            <option value="">Toda situação</option>
            {Object.entries(cat.data?.situations ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        {perm.operate && <button className="btn btn-primary" onClick={() => setCreating(true)}>Novo cliente {MODALITY_LABEL[modality]}</button>}
      </div>
      {q.isError ? <ErrorBox error={q.error} retry={() => q.refetch()} /> : !q.data || !cat.data ? <LoadingRows /> : q.data.items.length === 0 ? (
        <Empty title={filtered ? "Nenhum cliente com esses filtros" : `Nenhum cliente ${MODALITY_LABEL[modality]} na carteira`}>
          {filtered ? "Limpe a busca ou troque os filtros." : "Importe o backup do painel antigo em Importar dados, ou crie o primeiro cliente."}
        </Empty>
      ) : (
        <>
          <p className="meta" style={{ marginBottom: 8 }}>{plural(q.data.total, "cliente", "clientes")}{filtered ? " com os filtros atuais" : ` na carteira ${MODALITY_LABEL[modality]}`}. Atrasado: parado no mesmo status há {cat.data.sla_days} dias ou mais.</p>
          <table className="table" style={{ opacity: q.isPlaceholderData ? 0.6 : 1 }}>
            <thead>
              <tr><th>Cliente</th><th>Comercial</th><th>Status</th><th>Situação</th><th>Entrada</th><th>Comitê</th><th className="num">Tempo total</th></tr>
            </thead>
            <tbody>
              {q.data.items.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => setParams({ cliente: c.id }, { replace: true })}>
                  <td>
                    <div className="strong">{c.name}</div>
                    <div className="row" style={{ gap: 8 }}>
                      {c.risk_exit && <span className="flag" data-tone="danger">Saída de risco</span>}
                      {c.limit_expired && <span className="flag" data-tone="warn">Limite vencido</span>}
                      {c.extra.em_triagem && <span className="flag">Em triagem</span>}
                      {c.extra.tipo_analise && <span className="meta">{cat.data!.one7_analysis_types[c.extra.tipo_analise]}</span>}
                    </div>
                  </td>
                  <td className={c.commercial ? undefined : "muted"}>{c.commercial?.name ?? "Sem comercial"}</td>
                  <td>{c.status_label}</td>
                  <td><Mark tone={SITUATION_TONE[c.situation!]}>{cat.data!.situations[c.situation!]}</Mark><div className="meta num">{c.days_in_status ?? 0} dias no status</div></td>
                  <td className="num">{c.entry_date ? fmtDate(c.entry_date) : <span className="warn-text">sem data</span>}</td>
                  <td className="num">{c.committee_date ? fmtDate(c.committee_date) : "—"}</td>
                  <td className="num">{c.total_days === null || c.total_days === undefined ? "—" : `${c.total_days} d${c.total_days_open ? ", em andamento" : ""}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager page={page} pageSize={50} total={q.data.total} onPage={setPage} />
        </>
      )}
      {open && <ClientDialog id={open} onClose={() => setParams({}, { replace: true })} />}
      {creating && <ClientDialog modality={modality} onClose={() => setCreating(false)} />}
    </>
  );
}

type Draft = {
  name: string;
  commercial_id: string;
  status: string;
  entry_date: string;
  pre_committee_date: string;
  committee_date: string;
  contract_issued_date: string;
  signature_completed_date: string;
  notes: string;
  risk_exit: boolean;
  limit_expired: boolean;
  milestones: Record<string, Record<string, boolean>>;
  extra: { resultado_comite: string; tipo_analise: string; data_envio_comite: string; em_triagem: boolean };
  followups: Followup[];
};

const MILESTONE_LABELS: Record<string, string> = {
  cadastro: "Cadastro", homologado: "Homologado", emissao: "Emissão do contrato", processo: "Processo de assinatura", assinado: "Contratos assinados",
  analiseComite: "Análise em comitê", aprovacaoSistema: "Aprovação no sistema", cadastroFormalizacao: "Cadastro de formalização",
};
const GROUP_LABELS: Record<string, string> = { formalizacao: "Formalização", contratos: "Contratos", cadastro: "Cadastro" };

function emptyMilestones(modality: Modality): Record<string, Record<string, boolean>> {
  return modality === "one7"
    ? { formalizacao: { analiseComite: false, aprovacaoSistema: false }, cadastro: { cadastroFormalizacao: false } }
    : { formalizacao: { cadastro: false, homologado: false }, contratos: { emissao: false, processo: false, assinado: false } };
}

function toDraft(c: PortfolioClient | null, modality: Modality, firstStatus: string): Draft {
  return {
    name: c?.name ?? "",
    commercial_id: c?.commercial?.id ?? "",
    status: c?.status ?? firstStatus,
    entry_date: c ? c.entry_date ?? "" : new Date().toISOString().slice(0, 10),
    pre_committee_date: c?.pre_committee_date ?? "",
    committee_date: c?.committee_date ?? "",
    contract_issued_date: c?.contract_issued_date ?? "",
    signature_completed_date: c?.signature_completed_date ?? "",
    notes: c?.notes ?? "",
    risk_exit: c?.risk_exit ?? false,
    limit_expired: c?.limit_expired ?? false,
    milestones: c?.milestones ?? emptyMilestones(modality),
    extra: {
      resultado_comite: c?.extra.resultado_comite ?? "em_analise",
      tipo_analise: c?.extra.tipo_analise ?? "",
      data_envio_comite: c?.extra.data_envio_comite ?? "",
      em_triagem: !!c?.extra.em_triagem,
    },
    followups: c?.followups ?? [],
  };
}

function ClientDialog({ id, modality: newModality, onClose }: { id?: string; modality?: Modality; onClose: () => void }) {
  const perm = usePerm();
  const qc = useQueryClient();
  const toast = useToast();
  const cat = useCatalog();
  const detail = useQuery({ queryKey: ["portfolio-client", id], enabled: !!id, queryFn: () => api<PortfolioClient>(`/api/portfolio/clients/${id}`) });
  const c = detail.data ?? null;
  const modality: Modality = c?.modality ?? newModality ?? "normal";
  const statuses = cat.data?.statuses[modality] ?? [];
  const [draft, setDraft] = useState<Draft | null>(null);
  const [fuDate, setFuDate] = useState(new Date().toISOString().slice(0, 10));
  const [fuNote, setFuNote] = useState("");

  useEffect(() => {
    if (draft || !cat.data || (id && !c)) return;
    setDraft(toDraft(c, modality, statuses[0]?.key ?? ""));
  }, [c, cat.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: () => {
      const d = draft!;
      const dates = ["pre_committee_date", "committee_date", "contract_issued_date", "signature_completed_date"] as const;
      if (!id) {
        return api<PortfolioClient>("/api/portfolio/clients", { method: "POST", json: {
          modality, name: d.name, commercial_id: d.commercial_id || null, status: d.status, entry_date: d.entry_date || null,
          pre_committee_date: d.pre_committee_date || null, committee_date: d.committee_date || null, notes: d.notes,
          risk_exit: d.risk_exit, limit_expired: d.limit_expired, extra: d.extra,
        } });
      }
      const body: Record<string, unknown> = {
        name: d.name, status: d.status, notes: d.notes, risk_exit: d.risk_exit, limit_expired: d.limit_expired,
        milestones: d.milestones, followups: d.followups, extra: { ...d.extra, tipo_analise: d.extra.tipo_analise || null, data_envio_comite: d.extra.data_envio_comite || null },
        clear_dates: dates.filter((k) => !d[k]),
      };
      if (d.entry_date) body.entry_date = d.entry_date;
      for (const k of dates) if (d[k]) body[k] = d[k];
      if (d.commercial_id) body.commercial_id = d.commercial_id;
      else body.clear_commercial = true;
      return api<PortfolioClient>(`/api/portfolio/clients/${id}`, { method: "PATCH", json: body });
    },
    onSuccess: (saved) => {
      for (const key of ["portfolio-clients", "portfolio-summary", "signatures", "portfolio-client", "portfolio-clients-names"]) qc.invalidateQueries({ queryKey: [key] });
      toast(id ? "Cliente salvo." : `Cliente ${saved.name} criado.`);
      onClose();
    },
  });

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => (d ? { ...d, [k]: v } : d));
  const readOnly = !perm.operate;
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const title = id ? c?.name ?? "Cliente" : `Novo cliente ${MODALITY_LABEL[modality]}`;
  const statusLabel = useMemo(() => Object.fromEntries(statuses.map((s) => [s.key, s.label])), [statuses]);

  return (
    <Dialog title={title} onClose={onClose}>
      {detail.isError ? <ErrorBox error={detail.error} /> : !draft || !cat.data ? <LoadingRows rows={5} /> : (
        <form className="form-grid client-form" onSubmit={submit}>
          <p className="meta row" style={{ flexWrap: "wrap", gap: 10 }}>
            <ModalityTag modality={modality} />
            {c && <span>{c.source === "import" ? `Importado do painel antigo ${relative(c.imported_at)}` : `Criado ${relative(c.created_at)}`}</span>}
            {c?.registrations?.map((r) => <Link key={r.id} to={`/cadastros/${r.id}`}>Cadastro {r.code}</Link>)}
            {c?.signature_trackings?.length ? <Link to={`/assinaturas?q=${encodeURIComponent(c.name)}`}>Contratos em Assinaturas</Link> : null}
          </p>
          <label className="label"><span>Nome do cliente</span>
            <input className="input" required minLength={2} value={draft.name} onChange={(e) => set("name", e.target.value)} disabled={readOnly} /></label>
          <div className="grid-2">
            <label className="label"><span>Comercial responsável</span>
              <select className="select" value={draft.commercial_id} onChange={(e) => set("commercial_id", e.target.value)} disabled={readOnly}>
                <option value="">Sem comercial</option>
                {cat.data.commercials.filter((x) => x.is_active || x.id === draft.commercial_id).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
              </select></label>
            <label className="label"><span>Status da pasta</span>
              <select className="select" value={draft.status} onChange={(e) => set("status", e.target.value)} disabled={readOnly}>
                {statuses.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                {!statusLabel[draft.status] && <option value={draft.status}>{draft.status}</option>}
              </select></label>
          </div>
          {statuses.find((s) => s.key === draft.status)?.opens_signature && c?.status !== draft.status && (
            <p className="meta">Ao salvar, os contratos SEC e FIDC deste cliente entram em Assinaturas para conferência no portal.</p>
          )}
          <div className="grid-3">
            <label className="label"><span>{modality === "one7" ? "Cadastro na ONE7" : "Entrada da pasta"}</span>
              <input className="input" type="date" value={draft.entry_date} required={modality === "normal"} onChange={(e) => set("entry_date", e.target.value)} disabled={readOnly} /></label>
            <label className="label"><span>{modality === "one7" ? "Comitê interno" : "Pré-comitê"}</span>
              <input className="input" type="date" value={draft.pre_committee_date} onChange={(e) => set("pre_committee_date", e.target.value)} disabled={readOnly} /></label>
            <label className="label"><span>{modality === "one7" ? "Comitê ONE7" : "Comitê"}</span>
              <input className="input" type="date" value={draft.committee_date} onChange={(e) => set("committee_date", e.target.value)} disabled={readOnly} /></label>
          </div>
          {modality === "one7" ? (
            <div className="grid-3">
              <label className="label"><span>Envio ao comitê</span>
                <input className="input" type="date" value={draft.extra.data_envio_comite} onChange={(e) => set("extra", { ...draft.extra, data_envio_comite: e.target.value })} disabled={readOnly} /></label>
              <label className="label"><span>Resultado do comitê ONE7</span>
                <select className="select" value={draft.extra.resultado_comite} onChange={(e) => set("extra", { ...draft.extra, resultado_comite: e.target.value })} disabled={readOnly}>
                  {Object.entries(cat.data.one7_results).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select></label>
              <label className="label"><span>Tipo de análise</span>
                <select className="select" value={draft.extra.tipo_analise} onChange={(e) => set("extra", { ...draft.extra, tipo_analise: e.target.value, em_triagem: e.target.value ? draft.extra.em_triagem : false })} disabled={readOnly}>
                  <option value="">Não definido</option>
                  {Object.entries(cat.data.one7_analysis_types).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select></label>
              {draft.extra.tipo_analise && (
                <label className="check"><input type="checkbox" checked={draft.extra.em_triagem} onChange={(e) => set("extra", { ...draft.extra, em_triagem: e.target.checked })} disabled={readOnly} /> Em triagem (fora do quadro de status)</label>
              )}
            </div>
          ) : id ? (
            <div className="grid-2">
              <label className="label"><span>Emissão / envio para assinatura</span>
                <input className="input" type="date" value={draft.contract_issued_date} onChange={(e) => set("contract_issued_date", e.target.value)} disabled={readOnly} /></label>
              <label className="label"><span>Conclusão da assinatura</span>
                <input className="input" type="date" value={draft.signature_completed_date} onChange={(e) => set("signature_completed_date", e.target.value)} disabled={readOnly} /></label>
            </div>
          ) : null}
          <label className="label"><span>Observações</span>
            <textarea className="textarea" rows={3} value={draft.notes} onChange={(e) => set("notes", e.target.value)} disabled={readOnly} /></label>
          {modality === "normal" && (
            <div className="row" style={{ gap: 20 }}>
              <label className="check"><input type="checkbox" checked={draft.risk_exit} onChange={(e) => set("risk_exit", e.target.checked)} disabled={readOnly} /> Saída de risco</label>
              <label className="check"><input type="checkbox" checked={draft.limit_expired} onChange={(e) => set("limit_expired", e.target.checked)} disabled={readOnly} /> Limite vencido</label>
            </div>
          )}
          {id && (
            <div className="milestones">
              {Object.entries(draft.milestones).map(([g, items]) => (
                <fieldset key={g} className="field-set">
                  <legend className="meta">{GROUP_LABELS[g] ?? g}</legend>
                  {Object.entries(items).map(([k, v]) => (
                    <label key={k} className="check"><input type="checkbox" checked={v} disabled={readOnly}
                      onChange={(e) => set("milestones", { ...draft.milestones, [g]: { ...items, [k]: e.target.checked } })} /> {MILESTONE_LABELS[k] ?? k}</label>
                  ))}
                </fieldset>
              ))}
            </div>
          )}
          {id && (
            <section>
              <h3 style={{ marginBottom: 6 }}>Cobranças</h3>
              {draft.followups.length === 0 && <p className="meta">Nenhuma cobrança registrada.</p>}
              <ul className="followups">
                {draft.followups.map((f, i) => (
                  <li key={`${f.date}-${i}`}>
                    <span className="num meta">{fmtDate(f.date)}</span>
                    <span>{f.note || <span className="muted">Sem retorno registrado</span>}{f.kind === "assinatura" ? <span className="meta"> (assinatura)</span> : null}</span>
                    {!readOnly && <button type="button" className="link-btn meta" onClick={() => set("followups", draft.followups.filter((_, j) => j !== i))}>Remover</button>}
                  </li>
                ))}
              </ul>
              {!readOnly && (
                <div className="row" style={{ marginTop: 8 }}>
                  <input className="input" type="date" style={{ width: 160 }} value={fuDate} onChange={(e) => setFuDate(e.target.value)} aria-label="Data da cobrança" />
                  <input className="input" placeholder="Retorno do comercial (opcional)" value={fuNote} onChange={(e) => setFuNote(e.target.value)} aria-label="Retorno" />
                  <button type="button" className="btn" disabled={!fuDate} onClick={() => { set("followups", [...draft.followups, { date: fuDate, note: fuNote.trim(), kind: "documentacao" }]); setFuNote(""); }}>Registrar</button>
                </div>
              )}
            </section>
          )}
          {c && c.status_history.length > 0 && (
            <details>
              <summary className="meta">Histórico de status ({c.status_history.length}){c.legacy_history?.length ? ` e ${c.legacy_history.length} anotações do painel antigo` : ""}</summary>
              <ul className="history-list">
                {[...c.status_history].reverse().map((h, i) => <li key={i}><span className="num meta">{fmtDateTime(h.at)}</span> {h.label}</li>)}
                {c.legacy_history?.map((h, i) => <li key={`l${i}`}><span className="num meta">{fmtDateTime(h.at)}</span> {h.text}<span className="meta"> {h.user}</span></li>)}
              </ul>
            </details>
          )}
          {save.isError && <p className="form-error">{errorText(save.error)}</p>}
          <div className="dialog-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>{readOnly ? "Fechar" : "Cancelar"}</button>
            {!readOnly && <button className="btn btn-primary" disabled={save.isPending || draft.name.trim().length < 2}>{save.isPending ? "Salvando…" : id ? "Salvar" : "Criar cliente"}</button>}
          </div>
        </form>
      )}
    </Dialog>
  );
}

/* ---------------- commercials ---------------- */

function Commercials() {
  const perm = usePerm();
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["portfolio-commercials"], queryFn: () => api<{ items: CommercialRow[]; without_commercial: number }>("/api/portfolio/commercials") });
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<CommercialRow | null>(null);
  const refresh = () => { for (const k of ["portfolio-commercials", "portfolio-catalog", "portfolio-summary", "portfolio-clients"]) qc.invalidateQueries({ queryKey: [k] }); };
  const create = useMutation({
    mutationFn: () => api("/api/portfolio/commercials", { method: "POST", json: { name } }),
    onSuccess: () => { setName(""); refresh(); toast("Comercial cadastrado."); },
  });
  const patch = useMutation({
    mutationFn: (v: { id: string; body: object }) => api(`/api/portfolio/commercials/${v.id}`, { method: "PATCH", json: v.body }),
    onSuccess: () => { setEditing(null); refresh(); toast("Comercial atualizado."); },
    onError: (e) => toast(errorText(e), "danger"),
  });
  if (q.isError) return <ErrorBox error={q.error} retry={() => q.refetch()} />;
  if (!q.data) return <LoadingRows />;
  return (
    <div className="commercials">
      {perm.operate && (
        <form className="row" style={{ marginBottom: 16 }} onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <input className="input" style={{ width: 280 }} placeholder="Nome do comercial" value={name} onChange={(e) => setName(e.target.value)} minLength={2} required aria-label="Nome do comercial" />
          <button className="btn" disabled={create.isPending || name.trim().length < 2}>Cadastrar comercial</button>
          {create.isError && <span className="form-error">{errorText(create.error)}</span>}
        </form>
      )}
      {q.data.items.length === 0 ? <Empty title="Nenhum comercial">Os comerciais entram junto com a importação da carteira, ou um a um aqui.</Empty> : (
        <table className="table">
          <thead><tr><th>Comercial</th><th className="num">Normal</th><th className="num">One7</th><th className="num">Total</th><th>Situação</th><th /></tr></thead>
          <tbody>
            {q.data.items.map((c) => (
              <tr key={c.id}>
                <td className="strong">{c.name}</td>
                <td className="num">{c.by_modality.normal ?? 0}</td>
                <td className="num">{c.by_modality.one7 ?? 0}</td>
                <td className="num">{c.clients}</td>
                <td>{c.is_active ? <Mark tone="accent">Ativo</Mark> : <Mark tone="hollow">Inativo</Mark>}</td>
                <td style={{ textAlign: "right" }}>
                  {(perm.approve || perm.admin) && (
                    <div className="row" style={{ justifyContent: "flex-end" }}>
                      <button className="btn btn-sm btn-ghost" onClick={() => setEditing(c)}>Renomear</button>
                      <button className="btn btn-sm btn-ghost" onClick={() => patch.mutate({ id: c.id, body: { is_active: !c.is_active } })}>{c.is_active ? "Desativar" : "Reativar"}</button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {q.data.without_commercial > 0 && <tr><td className="muted">Sem comercial</td><td colSpan={2} /><td className="num">{q.data.without_commercial}</td><td colSpan={2} /></tr>}
          </tbody>
        </table>
      )}
      <p className="meta" style={{ marginTop: 12, maxWidth: "80ch" }}>Desativar tira o comercial das escolhas de novos clientes; os clientes e os números dele continuam. Nomes iguais com acentos ou maiúsculas diferentes são o mesmo comercial.</p>
      {editing && <RenameDialog c={editing} pending={patch.isPending} error={patch.error} onSave={(n) => patch.mutate({ id: editing.id, body: { name: n } })} onClose={() => setEditing(null)} />}
    </div>
  );
}

function RenameDialog({ c, onSave, onClose, pending, error }: { c: CommercialRow; onSave: (n: string) => void; onClose: () => void; pending: boolean; error: unknown }) {
  const [n, setN] = useState(c.name);
  return (
    <Dialog title={`Renomear ${c.name}`} onClose={onClose}>
      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); onSave(n); }}>
        <label className="label"><span>Nome</span><input className="input" value={n} minLength={2} required onChange={(e) => setN(e.target.value)} /></label>
        {error ? <p className="form-error">{errorText(error)}</p> : null}
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" disabled={pending || n.trim().length < 2}>Salvar</button>
        </div>
      </form>
    </Dialog>
  );
}
