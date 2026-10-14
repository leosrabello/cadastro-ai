import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Followup, Modality, Page, PortfolioClient, SignatureContract, SignatureKpis, SignatureRow } from "../api/types";
import { usePerm } from "../auth";
import { ModalityTag } from "../components/ModalitySwitch";
import { Dialog, Empty, ErrorBox, LoadingRows, Mark, errorText, useToast } from "../components/ui";
import { fmtDate, plural } from "../lib/format";
import { MODALITY_LABEL } from "../lib/modality";
import { useCatalog } from "./Portfolio";
import "./portfolio.css";

const STATES: { key: string; label: string }[] = [
  { key: "", label: "Todos" },
  { key: "aguardando,parcial", label: "Aguardando assinatura" },
  { key: "sem_emissao", label: "Sem emissão" },
  { key: "assinado", label: "Assinados" },
];
const CONTRACT_STATE: Record<SignatureContract["state"], { label: string; tone: string }> = {
  sem_emissao: { label: "Não emitido", tone: "hollow" },
  aguardando: { label: "Aguardando", tone: "warn" },
  assinado: { label: "Assinado", tone: "accent" },
};
const today = () => new Date().toISOString().slice(0, 10);

interface SignaturesPage {
  items: SignatureRow[];
  kpis: SignatureKpis;
  kpis_all: SignatureKpis;
  sla_days: number;
}

export function Signatures() {
  const perm = usePerm();
  const cat = useCatalog();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [debounced, setDebounced] = useState(search);
  const state = params.get("situacao") ?? "";
  const modality = params.get("modalidade") ?? "all";
  const commercial = params.get("comercial") ?? "";
  const [followups, setFollowups] = useState<SignatureRow | null>(null);
  const [creating, setCreating] = useState(false);
  useEffect(() => { const t = setTimeout(() => setDebounced(search), 250); return () => clearTimeout(t); }, [search]);
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    v ? next.set(k, v) : next.delete(k);
    setParams(next, { replace: true });
  };

  const query = new URLSearchParams({ modality });
  if (debounced) query.set("q", debounced);
  if (state) query.set("state", state);
  if (commercial) query.set("commercial_id", commercial);
  const q = useQuery({
    queryKey: ["signatures", query.toString()],
    queryFn: () => api<SignaturesPage>(`/api/signatures?${query}`),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
  const k = q.data?.kpis;
  const filtered = !!(debounced || state || commercial || modality !== "all");

  return (
    <div className="page signatures">
      <div className="page-head">
        <div>
          <h1>Assinaturas</h1>
          <p className="muted">Conferência no portal: para cada empresa, quando os contratos SEC e FIDC foram emitidos e quando todas as partes assinaram.</p>
        </div>
        {perm.operate && <button className="btn btn-primary" onClick={() => setCreating(true)}>Novo registro</button>}
      </div>

      <section className="kpi-row" aria-label="Indicadores de assinatura">
        <Kpi lead value={days(k?.avg_signature_days)} label="Tempo médio de assinatura"
          note={k ? (k.signed_basis ? `da emissão à assinatura, média de ${plural(k.signed_basis, "contrato assinado", "contratos assinados")}` : "nenhum contrato assinado ainda") : ""} />
        <Kpi value={days(k?.avg_signature_days_sec)} label="Contrato SEC" note="tempo médio" />
        <Kpi value={days(k?.avg_signature_days_fidc)} label="Contrato FIDC" note="tempo médio" />
        <Kpi value={k ? String(k.in_process) : "–"} label="Contratos em processo" tone={k && k.oldest_open_days !== null && k.oldest_open_days >= (q.data?.sla_days ?? 7) ? "warn" : undefined}
          note={k?.in_process ? `há ${days(k.avg_open_days)} em média; o mais antigo, ${days(k.oldest_open_days)}` : "nenhum aguardando"} />
        <Kpi value={k ? String(k.signed) : "–"} label="Contratos assinados" note={k ? `${plural(k.not_issued, "contrato ainda não emitido", "contratos ainda não emitidos")}` : ""} />
        <Kpi value={k ? String(k.followups) : "–"} label="Cobranças registradas" note={k ? `em ${plural(k.companies, "empresa", "empresas")}` : ""} />
      </section>
      {filtered && q.data && <p className="meta" style={{ marginTop: -16, marginBottom: 20 }}>Indicadores das empresas filtradas. Sem filtros: tempo médio de {days(q.data.kpis_all.avg_signature_days)}, {q.data.kpis_all.in_process} em processo.</p>}

      <div className="row toolbar" style={{ flexWrap: "wrap" }}>
        <input className="input" style={{ width: 260 }} type="search" placeholder="Buscar empresa ou comercial" value={search}
          onChange={(e) => { setSearch(e.target.value); set("q", e.target.value); }} aria-label="Buscar empresa ou comercial" />
        <div className="segmented" role="group" aria-label="Situação dos contratos">
          {STATES.map((s) => <button key={s.key} aria-pressed={state === s.key} onClick={() => set("situacao", s.key)}>{s.label}</button>)}
        </div>
        <select className="select" style={{ width: 170 }} value={modality} onChange={(e) => set("modalidade", e.target.value === "all" ? "" : e.target.value)} aria-label="Modalidade">
          <option value="all">Normal e One7</option>
          <option value="normal">Só Normal</option>
          <option value="one7">Só One7</option>
        </select>
        <select className="select" style={{ width: 200 }} value={commercial} onChange={(e) => set("comercial", e.target.value)} aria-label="Comercial">
          <option value="">Todos os comerciais</option>
          <option value="none">Sem comercial</option>
          {cat.data?.commercials.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>

      {q.isError ? <ErrorBox error={q.error} retry={() => q.refetch()} /> : !q.data ? <LoadingRows /> : q.data.items.length === 0 ? (
        <Empty title={filtered ? "Nenhuma empresa com esses filtros" : "Nenhum contrato em acompanhamento"}>
          {filtered ? "Limpe a busca ou troque a situação." : "Uma empresa entra aqui sozinha quando o cliente chega a Aguardando Assinatura na Carteira, ou por Novo registro."}
        </Empty>
      ) : (
        <>
          <p className="meta" style={{ marginBottom: 8 }}>{plural(q.data.items.length, "empresa", "empresas")}. Aguardando primeiro, da emissão mais antiga para a mais recente.</p>
          <table className="table sig-table" style={{ opacity: q.isPlaceholderData ? 0.6 : 1 }}>
            <thead>
              <tr><th>Empresa</th><th>Contrato</th><th>Nº do processo</th><th>Emissão</th><th>Assinatura</th><th>Situação</th><th className="num">Dias</th><th>Cobranças</th></tr>
            </thead>
            {q.data.items.map((t) => <Company key={t.id} t={t} sla={q.data!.sla_days} readOnly={!perm.operate} onFollowups={() => setFollowups(t)} canDelete={perm.approve || perm.admin} />)}
          </table>
        </>
      )}
      <p className="meta sig-limit">
        O portal de assinatura não tem integração com o CadastroAI: nenhuma consulta ou ação é feita nele automaticamente. As datas são as que o analista confere no portal e
        registra aqui; os tempos e indicadores são calculados a partir delas.
      </p>
      {followups && <FollowupDialog t={followups} readOnly={!perm.operate} onClose={() => setFollowups(null)} />}
      {creating && <NewTracking onClose={() => setCreating(false)} />}
    </div>
  );
}

function days(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${String(v).replace(".", ",")} ${v === 1 ? "dia" : "dias"}`;
}

function Kpi({ value, label, note, tone, lead }: { value: string; label: string; note?: string; tone?: string; lead?: boolean }) {
  return (
    <div className="kpi" data-lead={lead || undefined}>
      <span className="kpi-value num" data-tone={tone}>{value}</span>
      <span className="kpi-label">{label}</span>
      {note && <span className="meta">{note}</span>}
    </div>
  );
}

function Company({ t, sla, readOnly, onFollowups, canDelete }: { t: SignatureRow; sla: number; readOnly: boolean; onFollowups: () => void; canDelete: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const patch = useMutation({
    mutationFn: (body: object) => api<SignatureRow>(`/api/signatures/${t.id}`, { method: "PATCH", json: body }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["signatures"] }); qc.invalidateQueries({ queryKey: ["portfolio-summary"] }); },
    onError: (e) => { toast(errorText(e), "danger"); qc.invalidateQueries({ queryKey: ["signatures"] }); },
  });
  const remove = useMutation({
    mutationFn: () => api(`/api/signatures/${t.id}`, { method: "DELETE" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["signatures"] }); toast(`${t.company_name} removida de Assinaturas.`); },
    onError: (e) => toast(errorText(e), "danger"),
  });
  const [confirming, setConfirming] = useState(false);
  const setDate = (kind: string, field: "issued_date" | "signed_date", value: string) =>
    patch.mutate({ contracts: { [kind]: value ? { [field]: value } : { clear: [field] } } });
  const setProcess = (kind: string, value: string) => patch.mutate({ contracts: { [kind]: { process_number: value } } });

  return (
    <tbody className="sig-company" data-state={t.state}>
      {t.contracts.map((k, i) => (
        <tr key={k.kind}>
          {i === 0 && (
            <td rowSpan={t.contracts.length} className="sig-who">
              <div className="strong">{t.company_name}</div>
              <div className="meta row" style={{ gap: 8, flexWrap: "wrap" }}>
                <ModalityTag modality={t.modality} />
                <span>{t.commercial?.name ?? "Sem comercial"}</span>
              </div>
              {t.client ? (
                <div className="meta"><Link to={`/carteira?cliente=${t.client.id}`}>Carteira: {t.client.status_label}</Link>{t.auto_created ? ", aberto automaticamente" : ""}</div>
              ) : <div className="meta">Sem cliente na carteira</div>}
              {canDelete && <button className="link-btn meta" style={{ marginTop: 6, color: "var(--muted)" }} disabled={remove.isPending} onClick={() => setConfirming(true)}>Remover</button>}
              {confirming && (
                <Dialog title={`Remover ${t.company_name}?`} onClose={() => setConfirming(false)}>
                  <p className="muted">Os dois contratos e as cobranças saem de Assinaturas. O cliente na carteira continua. A remoção fica no histórico de auditoria.</p>
                  <div className="dialog-actions">
                    <button className="btn btn-ghost" onClick={() => setConfirming(false)}>Cancelar</button>
                    <button className="btn btn-danger" onClick={() => { setConfirming(false); remove.mutate(); }}>Remover</button>
                  </div>
                </Dialog>
              )}
            </td>
          )}
          <td><span className="contract-tag" data-kind={k.kind}>{k.kind}</span></td>
          <td><input className="input input-sm" defaultValue={k.process_number} placeholder="—" disabled={readOnly} aria-label={`Número do processo ${k.kind}`}
            onBlur={(e) => e.target.value.trim() !== k.process_number && setProcess(k.kind, e.target.value.trim())} /></td>
          <td><input className="input input-sm" type="date" defaultValue={k.issued_date ?? ""} max={today()} disabled={readOnly} aria-label={`Emissão ${k.kind}`}
            key={`i-${k.issued_date}`} onChange={(e) => setDate(k.kind, "issued_date", e.target.value)} /></td>
          <td><input className="input input-sm" type="date" defaultValue={k.signed_date ?? ""} min={k.issued_date ?? undefined} max={today()} disabled={readOnly || !k.issued_date}
            title={k.issued_date ? undefined : "Informe a emissão primeiro"} aria-label={`Assinatura ${k.kind}`}
            key={`s-${k.signed_date}`} onChange={(e) => setDate(k.kind, "signed_date", e.target.value)} /></td>
          <td><Mark tone={k.state === "aguardando" && (k.days ?? 0) >= sla ? "danger" : CONTRACT_STATE[k.state].tone}>{CONTRACT_STATE[k.state].label}</Mark></td>
          <td className="num">{k.days === null ? "—" : `${k.days}${k.state === "aguardando" ? " em aberto" : ""}`}</td>
          {i === 0 && (
            <td rowSpan={t.contracts.length}>
              <button className="btn btn-sm" onClick={onFollowups}>{t.followups.length ? plural(t.followups.length, "cobrança", "cobranças") : "Registrar"}</button>
              {t.followups.length > 0 && <div className="meta" style={{ marginTop: 4 }}>última {fmtDate(t.followups[t.followups.length - 1].date)}</div>}
            </td>
          )}
        </tr>
      ))}
    </tbody>
  );
}

function FollowupDialog({ t, readOnly, onClose }: { t: SignatureRow; readOnly: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [items, setItems] = useState<Followup[]>(t.followups);
  const [date, setDate] = useState(today());
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: (next: Followup[]) => api<SignatureRow>(`/api/signatures/${t.id}`, { method: "PATCH", json: { followups: next } }),
    onSuccess: (row) => { setItems(row.followups); qc.invalidateQueries({ queryKey: ["signatures"] }); },
  });
  const update = (next: Followup[]) => { setItems(next); save.mutate(next); };
  return (
    <Dialog title={`Cobranças: ${t.company_name}`} onClose={onClose}>
      <p className="muted" style={{ marginBottom: 14 }}>Cada vez que alguém cobrou a assinatura, e o que respondeu.</p>
      <ul className="followups">
        {[...items].reverse().map((f) => {
          const i = items.indexOf(f);
          return (
            <li key={`${f.date}-${i}`}>
              <span className="num meta">{fmtDate(f.date)}</span>
              <span>{f.note || <span className="muted">Sem retorno registrado</span>}</span>
              {!readOnly && <button className="link-btn meta" onClick={() => update(items.filter((_, j) => j !== i))}>Remover</button>}
            </li>
          );
        })}
        {items.length === 0 && <li className="muted">Nenhuma cobrança registrada.</li>}
      </ul>
      {!readOnly && (
        <form className="row" style={{ marginTop: 14 }} onSubmit={(e) => { e.preventDefault(); update([...items, { date, note: note.trim(), kind: "assinatura" }]); setNote(""); }}>
          <input className="input" type="date" style={{ width: 160 }} value={date} max={today()} onChange={(e) => setDate(e.target.value)} required aria-label="Data" />
          <input className="input" placeholder="Retorno (opcional)" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Retorno" />
          <button className="btn" disabled={save.isPending}>Registrar</button>
        </form>
      )}
      {save.isError && <p className="form-error">{errorText(save.error)}</p>}
      <div className="dialog-actions"><button className="btn btn-ghost" onClick={onClose}>Fechar</button></div>
    </Dialog>
  );
}

function NewTracking({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const cat = useCatalog();
  const [modality, setModalityChoice] = useState<Modality>("normal");
  const [clientId, setClientId] = useState("");
  const [company, setCompany] = useState("");
  const [commercial, setCommercial] = useState("");
  const clients = useQuery({
    queryKey: ["portfolio-clients-names", modality],
    queryFn: () => api<Page<PortfolioClient>>(`/api/portfolio/clients?modality=${modality}&sort=name&page_size=500`),
  });
  const create = useMutation({
    mutationFn: () => api<SignatureRow>("/api/signatures", { method: "POST", json: clientId ? { client_id: clientId } : { company_name: company, commercial_id: commercial || null, modality } }),
    onSuccess: (t) => { qc.invalidateQueries({ queryKey: ["signatures"] }); toast(`${t.company_name} entrou em Assinaturas.`); onClose(); },
  });
  return (
    <Dialog title="Novo registro de assinatura" onClose={onClose}>
      <p className="muted" style={{ marginBottom: 16 }}>Escolha o cliente da carteira; a empresa e o comercial vêm dele. Use o nome livre só para empresas que não estão na carteira.</p>
      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
        <div className="segmented" role="radiogroup" aria-label="Modalidade">
          {(["normal", "one7"] as Modality[]).map((m) => (
            <button type="button" role="radio" key={m} aria-checked={modality === m} aria-pressed={modality === m} onClick={() => { setModalityChoice(m); setClientId(""); }}>{MODALITY_LABEL[m]}</button>
          ))}
        </div>
        <label className="label"><span>Cliente da carteira {MODALITY_LABEL[modality]}</span>
          <select className="select" value={clientId} onChange={(e) => setClientId(e.target.value)}>
            <option value="">Empresa fora da carteira</option>
            {clients.data?.items.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select></label>
        {!clientId && (
          <div className="grid-2">
            <label className="label"><span>Empresa</span><input className="input" value={company} minLength={2} required onChange={(e) => setCompany(e.target.value)} /></label>
            <label className="label"><span>Comercial</span>
              <select className="select" value={commercial} onChange={(e) => setCommercial(e.target.value)}>
                <option value="">Sem comercial</option>
                {cat.data?.commercials.filter((c) => c.is_active).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select></label>
          </div>
        )}
        {create.isError && <p className="form-error">{errorText(create.error)}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" disabled={create.isPending || (!clientId && company.trim().length < 2)}>Criar</button>
        </div>
      </form>
    </Dialog>
  );
}
