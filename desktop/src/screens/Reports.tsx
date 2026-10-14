import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { ClientRef, PortfolioSummary, Scope } from "../api/types";
import { ModalityTag, ScopePicker } from "../components/ModalitySwitch";
import { Empty, ErrorBox, LoadingRows, Mark } from "../components/ui";
import { fmtDate, plural } from "../lib/format";
import { useModality } from "../lib/modality";
import { SITUATION_TONE, useCatalog } from "./Portfolio";
import "./portfolio.css";

const FILTER_KEYS = ["q", "comercial", "status", "situacao", "entrada_de", "entrada_ate", "comite_de", "comite_ate"] as const;
const API_NAMES: Record<(typeof FILTER_KEYS)[number], string> = {
  q: "q", comercial: "commercial_id", status: "status", situacao: "situation",
  entrada_de: "entry_from", entrada_ate: "entry_to", comite_de: "committee_from", comite_ate: "committee_to",
};

/** The report's scope and filters live in the address, so the image page shows exactly the same numbers. */
export function useReportParams() {
  const [params, setParams] = useSearchParams();
  const [modality] = useModality();
  const scope = (params.get("modalidade") as Scope) || modality;
  const apiQuery = new URLSearchParams({ modality: scope });
  for (const k of FILTER_KEYS) {
    const v = params.get(k);
    if (v) apiQuery.set(API_NAMES[k], v);
  }
  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) v ? next.set(k, v) : next.delete(k);
    setParams(next, { replace: true });
  };
  return { params, scope, apiQuery, set, filtered: FILTER_KEYS.some((k) => params.get(k)) };
}

export function useSummary(apiQuery: URLSearchParams) {
  return useQuery({
    queryKey: ["portfolio-summary", "report", apiQuery.toString()],
    queryFn: () => api<PortfolioSummary>(`/api/portfolio/summary?${apiQuery}&rows=true`),
    placeholderData: keepPreviousData,
  });
}

export const fmtDays = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${String(v).replace(".", ",")} ${v === 1 ? "dia" : "dias"}`);
export const fmtPct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);

export function Reports() {
  const cat = useCatalog();
  const { params, scope, apiQuery, set, filtered } = useReportParams();
  const q = useSummary(apiQuery);
  const [search, setSearch] = useState(params.get("q") ?? "");
  useEffect(() => { const t = setTimeout(() => set({ q: search || null }), 250); return () => clearTimeout(t); }, [search]); // eslint-disable-line react-hooks/exhaustive-deps

  const s = q.data;
  const k = s?.kpis;
  const statuses = scope === "all" ? [] : cat.data?.statuses[scope] ?? [];
  const consolidated = scope === "all";

  return (
    <div className="page reports">
      <div className="page-head">
        <div>
          <h1>Relatórios da carteira</h1>
          <p className="muted">{s ? `${s.modality_label}. ` : ""}Números calculados dos clientes gravados no sistema, no momento em que você abre a página.</p>
        </div>
        <Link className="btn btn-primary" to={`/relatorios/imagem?${new URLSearchParams({ ...Object.fromEntries(params), modalidade: scope })}`}>Gerar imagem do relatório</Link>
      </div>

      <div className="row toolbar" style={{ flexWrap: "wrap" }}>
        <ScopePicker value={scope} onChange={(v) => set({ modalidade: v, status: null })} />
        <input className="input" style={{ width: 200 }} type="search" placeholder="Buscar cliente" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Buscar cliente" />
        <select className="select" style={{ width: 200 }} value={params.get("comercial") ?? ""} onChange={(e) => set({ comercial: e.target.value || null })} aria-label="Comercial">
          <option value="">Todos os comerciais</option>
          <option value="none">Sem comercial</option>
          {cat.data?.commercials.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        {!consolidated && (
          <select className="select" style={{ width: 190 }} value={params.get("status") ?? ""} onChange={(e) => set({ status: e.target.value || null })} aria-label="Status">
            <option value="">Todos os status</option>
            {statuses.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
          </select>
        )}
        <select className="select" style={{ width: 150 }} value={params.get("situacao") ?? ""} onChange={(e) => set({ situacao: e.target.value || null })} aria-label="Situação">
          <option value="">Toda situação</option>
          {Object.entries(cat.data?.situations ?? {}).map(([key, v]) => <option key={key} value={key}>{v}</option>)}
        </select>
        <fieldset className="date-range"><legend className="meta">Entrada</legend>
          <input className="input input-sm" type="date" value={params.get("entrada_de") ?? ""} onChange={(e) => set({ entrada_de: e.target.value || null })} aria-label="Entrada a partir de" />
          <span className="meta">até</span>
          <input className="input input-sm" type="date" value={params.get("entrada_ate") ?? ""} onChange={(e) => set({ entrada_ate: e.target.value || null })} aria-label="Entrada até" />
        </fieldset>
        <fieldset className="date-range"><legend className="meta">Comitê</legend>
          <input className="input input-sm" type="date" value={params.get("comite_de") ?? ""} onChange={(e) => set({ comite_de: e.target.value || null })} aria-label="Comitê a partir de" />
          <span className="meta">até</span>
          <input className="input input-sm" type="date" value={params.get("comite_ate") ?? ""} onChange={(e) => set({ comite_ate: e.target.value || null })} aria-label="Comitê até" />
        </fieldset>
        {filtered && <button className="btn btn-ghost" onClick={() => { setSearch(""); set(Object.fromEntries(FILTER_KEYS.map((x) => [x, null]))); }}>Limpar filtros</button>}
      </div>

      {q.isError ? <ErrorBox error={q.error} retry={() => q.refetch()} /> : !s || !k || !cat.data ? <LoadingRows rows={8} /> : s.population === 0 ? (
        <Empty title="A carteira está vazia">Importe o backup do painel antigo em <Link to="/carteira?aba=importar">Carteira, Importar dados</Link>, ou cadastre clientes.</Empty>
      ) : (
        <div style={{ opacity: q.isPlaceholderData ? 0.6 : 1 }}>
          {consolidated && <p className="consolidated-note">Consolidado: cada número soma as carteiras Normal e One7.</p>}
          {filtered && <p className="meta" style={{ marginBottom: 10 }}>{k.total_clients} de {s.population} clientes {consolidated ? "das duas modalidades" : `da carteira ${s.modality_label}`} atendem aos filtros.</p>}
          <section className="kpi-row" aria-label="Indicadores">
            <Kpi lead value={String(k.total_clients)} label={filtered ? "Clientes no filtro" : "Total de clientes"} note={plural(k.commercials, "comercial", "comerciais")} />
            <Kpi value={String(k.approved)} label="Concluídos (aptos a operar)" />
            <Kpi value={String(k.overdue)} label={`Atrasados (${s.sla_days} dias no status)`} tone={k.overdue ? "warn" : undefined} />
            <Kpi value={String(k.denied)} label="Negados" />
            <Kpi value={fmtPct(k.approval_rate)} label="Taxa de aprovação" note="aptos sobre aptos e negados" />
            <Kpi value={k.top_commercial?.name ?? "—"} label="Comercial destaque" note={k.top_commercial ? plural(k.top_commercial.total, "cliente", "clientes") : undefined} />
            {scope !== "one7" && <Kpi value={String(k.risk_exit)} label="Saída de risco" tone={k.risk_exit ? "danger" : undefined} />}
            {scope !== "one7" && <Kpi value={String(k.limit_expired)} label="Limite vencido" tone={k.limit_expired ? "warn" : undefined} />}
          </section>

          <section className="insights">
            <Insight title="Clientes por status">
              {s.by_status.filter((x) => x.count).map((x) => (
                <Row key={`${x.modality}-${x.key}`} label={<>{consolidated && <ModalityTag modality={x.modality} />} {x.label}</>} value={String(x.count)} />
              ))}
            </Insight>
            <Insight title="Tempos médios">
              <Row label="Da entrada até apto a operar" value={fmtDays(k.avg_days_to_approved)} note={k.avg_days_to_approved_basis ? plural(k.avg_days_to_approved_basis, "pasta", "pastas") : "sem pastas aptas"} />
              <Row label="Assinatura dos contratos" value={fmtDays(s.signatures.avg_signature_days)} note={s.signatures.signed_basis ? plural(s.signatures.signed_basis, "contrato", "contratos") : "nenhum assinado"} />
              <Row label="Contrato SEC" value={fmtDays(s.signatures.avg_signature_days_sec)} />
              <Row label="Contrato FIDC" value={fmtDays(s.signatures.avg_signature_days_fidc)} />
              <Row label="Contratos em aberto, há em média" value={fmtDays(s.signatures.avg_open_days)} note={plural(s.signatures.in_process, "contrato", "contratos")} />
            </Insight>
            <Insight title="Maior tempo parado"><RefList items={s.stalled} days empty="Nenhum cliente em andamento." /></Insight>
            <Insight title={`Acima do prazo (${s.sla_days} dias)`}><RefList items={s.over_sla} days warn empty={`Nenhum cliente parado há ${s.sla_days} dias ou mais.`} /></Insight>
            {scope !== "one7" && <Insight title="Saída de risco"><RefList items={s.risk_exit} empty="Nenhum cliente marcado." tone="danger" /></Insight>}
            {scope !== "one7" && <Insight title="Limite vencido"><RefList items={s.limit_expired} empty="Nenhum cliente marcado." tone="warn" /></Insight>}
            <Insight title="Entradas por mês">
              <MonthBars months={s.by_month} />
            </Insight>
          </section>

          <section style={{ marginTop: 40 }}>
            <h2 style={{ marginBottom: 10 }}>Comerciais</h2>
            <div className="table-scroll">
              <table className="table compact">
                <thead><tr><th>Comercial</th><th className="num">Clientes</th><th className="num">Participação</th><th className="num">Aptos</th><th className="num">Negados</th><th className="num">Em andamento</th><th className="num">Atrasados</th><th className="num">Aprovação</th><th className="num">Até apto</th></tr></thead>
                <tbody>
                  {s.by_commercial.map((c) => (
                    <tr key={c.id ?? "none"}>
                      <td className={c.id ? "strong" : "muted"}>{c.name}</td>
                      <td className="num">{c.total}</td>
                      <td className="num">{fmtPct(c.share)}</td>
                      <td className="num">{c.approved}</td>
                      <td className="num">{c.denied}</td>
                      <td className="num">{c.in_progress}</td>
                      <td className="num" data-tone={c.overdue ? "warn" : undefined}>{c.overdue}</td>
                      <td className="num">{fmtPct(c.approval_rate)}</td>
                      <td className="num">{fmtDays(c.avg_days_to_approved)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section style={{ marginTop: 40 }}>
            <h2 style={{ marginBottom: 10 }}>Clientes ({s.rows?.length ?? 0})</h2>
            <div className="table-scroll">
              <table className="table compact report-table">
                <thead>
                  <tr>
                    <th>Cliente</th><th>Comercial</th><th>Status</th><th>Situação</th><th>Entrada</th><th>Pré-comitê</th><th>Comitê</th>
                    <th>Emissão p/ assinatura</th><th>Conclusão assinatura</th><th>Apto a operar</th><th className="num">Tempo total</th><th className="num">Tempo assinatura</th>
                    <th className="num">Dias no status</th><th>Saída de risco</th><th>Limite vencido</th><th>Observações</th>
                  </tr>
                </thead>
                <tbody>
                  {s.rows?.map((r) => (
                    <tr key={r.id}>
                      <td className="strong" data-tone={r.risk_exit ? "danger" : r.limit_expired ? "warn" : undefined}>
                        <Link to={`/carteira?cliente=${r.id}`}>{r.name}</Link>{consolidated && <> <ModalityTag modality={r.modality} /></>}
                      </td>
                      <td className={r.commercial ? undefined : "muted"}>{r.commercial ?? "—"}</td>
                      <td>{r.status_label}</td>
                      <td><Mark tone={SITUATION_TONE[r.situation]}>{cat.data!.situations[r.situation]}</Mark></td>
                      <td className="num">{fmtDate(r.entry_date)}</td>
                      <td className="num">{r.pre_committee_date ? fmtDate(r.pre_committee_date) : "—"}</td>
                      <td className="num">{r.committee_date ? fmtDate(r.committee_date) : "—"}</td>
                      <td className="num">{r.signature_issued ? fmtDate(r.signature_issued) : "—"}</td>
                      <td className="num">{r.signature_completed ? fmtDate(r.signature_completed) : "—"}</td>
                      <td className="num">{r.approved_at ? fmtDate(r.approved_at) : "—"}</td>
                      <td className="num">{r.total_days === null ? "—" : `${r.total_days} d${r.total_days_open ? " (em andamento)" : ""}`}</td>
                      <td className="num">{r.signature_days === null ? "—" : `${r.signature_days} d${r.signature_open ? " (em aberto)" : ""}`}</td>
                      <td className="num">{r.days_in_status ?? "—"}</td>
                      <td>{r.risk_exit ? <span className="danger-text strong">Sim</span> : "Não"}</td>
                      <td>{r.limit_expired ? <span className="warn-text strong">Sim</span> : "Não"}</td>
                      <td className="report-notes">{r.notes || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function Kpi({ value, label, note, tone, lead }: { value: string; label: string; note?: string; tone?: string; lead?: boolean }) {
  return (
    <div className="kpi" data-lead={lead || undefined}>
      <span className="kpi-value num" data-tone={tone} data-long={value.length > 9}>{value}</span>
      <span className="kpi-label">{label}</span>
      {note && <span className="meta">{note}</span>}
    </div>
  );
}

function Insight({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="insight">
      <h3>{title}</h3>
      <div className="insight-body">{children}</div>
    </div>
  );
}

function Row({ label, value, note }: { label: ReactNode; value: string; note?: string }) {
  return (
    <div className="insight-row">
      <span>{label}{note && <span className="meta"> · {note}</span>}</span>
      <span className="num strong">{value}</span>
    </div>
  );
}

function RefList({ items, empty, days, warn, tone }: { items: ClientRef[]; empty: string; days?: boolean; warn?: boolean; tone?: string }) {
  if (!items.length) return <p className="meta">{empty}</p>;
  return (
    <>
      {items.map((x) => (
        <div key={x.id} className="insight-row">
          <Link to={`/carteira?cliente=${x.id}`} data-tone={tone}>{x.name}</Link>
          <span className={`num ${warn ? "warn-text" : ""}`}>{days ? `${x.days_in_status ?? 0} d` : x.status_label}</span>
        </div>
      ))}
    </>
  );
}

const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
export const monthLabel = (ym: string) => `${MONTHS[Number(ym.slice(5, 7)) - 1]}/${ym.slice(2, 4)}`;

function MonthBars({ months }: { months: { month: string; count: number }[] }) {
  if (!months.length) return <p className="meta">Sem datas de entrada.</p>;
  const max = Math.max(...months.map((m) => m.count), 1);
  return (
    <div className="month-bars" role="img" aria-label={months.map((m) => `${monthLabel(m.month)}: ${m.count}`).join(", ")}>
      {months.slice(-8).map((m) => (
        <div key={m.month} className="month-bar">
          <span className="num meta">{m.count}</span>
          <span className="month-fill" style={{ height: `${(m.count / max) * 100}%` }} />
          <span className="meta">{monthLabel(m.month)}</span>
        </div>
      ))}
    </div>
  );
}
