import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { forwardRef, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, apiBlob } from "../api/client";
import type { ChecklistItem, RegistrationDetail } from "../api/types";
import { usePerm } from "../auth";
import { Mark as LogoMark } from "../components/Logo";
import { Dialog, ErrorBox, Skeleton, errorText, useToast } from "../components/ui";
import { CHECK_STATE, SEVERITY, fmtDate, fmtDateTime } from "../lib/format";
import { isTauri } from "../lib/files";
import { exportSheetPng, useFitScale } from "../lib/sheet";
import "./report.css";

interface Report {
  generated_at: string;
  generated_by: string;
  reference_date: string;
  registration: { id: string; code: string; kind_label: string; modality_label: string; status: string; ready_for_decision: boolean };
  company: { razao_social: string; cnpj: string | null; tax_id_label: string | null; endereco: string | null; situacao_cadastral: string | null };
  governance: { administradores: string | null; responsaveis_assinatura: string | null; forma_assinatura: string | null; consolidado: string | null } | null;
  partners: { nome: string; cpf: string | null; fora_do_quadro?: boolean; irpf: { exercicio: string | null; bens: number | null; dividas: number | null; dividendos: number | null }[] }[];
  revenue: {
    series: Record<string, Record<string, number>>;
    summary: { year: string; previous_year: string | null; months: number[]; total: number; average: number; previous_total: number | null; growth_same_months: number | null } | null;
  };
  debt: { total: number | null; date: string | null; items: { instituicao: string; limite: number | null; tomado: number }[]; times_average_revenue: number | null } | null;
  customers: { top: { cliente: string; percentual: number }[]; top3_share: number } | null;
  statements: { exercicio: string | null; receita_liquida: number | null; lucro_liquido: number | null; patrimonio_liquido: number | null; ativo_total: number | null }[];
  checklist: RegistrationDetail["checklist"];
  findings: { by_severity: Record<string, number>; top: { title: string; severity: keyof typeof SEVERITY; explanation: string; recommended_action: string | null; source: string; count: number }[] };
  analysis: Record<string, string | null>;
  decision: { action: string; reason: string | null; by: string | null; at: string } | null;
  images: { visit_document_id: string | null; page_document_ids: string[] };
}

const MONTHS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
const DECISIONS: Record<string, string> = { approve: "Aprovado", reject: "Reprovado", request_documents: "Documentos solicitados", escalate: "Escalado", reopen: "Reaberto" };
const RECOMMENDATIONS = ["Recomendado", "Recomendado com ressalvas", "Não recomendado"];

const mi = (v: number) => (v / 1_000_000).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 2 });
const brl = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 }));

async function toDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.readAsDataURL(blob);
  });
}

function useImages(rep: Report | undefined) {
  return useQuery({
    queryKey: ["report-images", rep?.registration.id, rep?.images],
    enabled: !!rep,
    staleTime: Infinity,
    queryFn: async () => {
      const out: { photo: string | null; pages: string[] } = { photo: null, pages: [] };
      if (rep!.images.visit_document_id) {
        try {
          out.photo = await toDataUrl(await apiBlob(`/api/documents/${rep!.images.visit_document_id}/photo`));
        } catch {
          out.photo = null;
        }
      }
      for (const id of rep!.images.page_document_ids.slice(0, 3)) {
        try {
          out.pages.push(await toDataUrl(await apiBlob(`/api/documents/${id}/pages/0`)));
        } catch {
          /* skip a page that cannot be rendered */
        }
      }
      return out;
    },
  });
}

export function Report() {
  const { id = "" } = useParams();
  const perm = usePerm();
  const toast = useToast();
  const q = useQuery({ queryKey: ["report", id], queryFn: () => api<Report>(`/api/registrations/${id}/report`) });
  const imgs = useImages(q.data);
  const sheet = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const scale = useFitScale(frame, q.data);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);

  async function exportPng() {
    if (!sheet.current || !q.data) return;
    setBusy(true);
    try {
      if (await exportSheetPng(sheet.current, `analise-${q.data.registration.code}.png`) && isTauri()) toast("Imagem salva.");
    } catch (e) {
      toast(`Não foi possível gerar a imagem: ${errorText(e)}`, "danger");
    } finally {
      setBusy(false);
    }
  }

  if (q.isError) return <div className="page"><ErrorBox error={q.error} retry={() => q.refetch()} /></div>;
  const rep = q.data;
  return (
    <div className="page report-page">
      <div className="page-head">
        <div>
          <Link to={`/cadastros/${id}`} className="meta">{rep?.company.razao_social ?? "Cadastro"}</Link>
          <h1>Relatório da análise</h1>
          <p className="muted">Uma página com o que os documentos mostram e o parecer do analista. Baixe como imagem para o comitê.</p>
        </div>
        <div className="row">
          {perm.operate && <button className="btn" onClick={() => setEditing(true)} disabled={!rep}>Editar parecer</button>}
          <button className="btn btn-primary" onClick={exportPng} disabled={!rep || busy || imgs.isLoading}>{busy ? "Gerando…" : "Baixar imagem"}</button>
        </div>
      </div>
      <div className="report-frame" ref={frame} style={{ height: sheet.current ? sheet.current.offsetHeight * scale : undefined }}>
        {!rep ? <Skeleton h={900} /> : (
          <div style={{ transform: `scale(${scale})`, transformOrigin: "top left", width: 1600 }}>
            <Sheet ref={sheet} rep={rep} photo={imgs.data?.photo ?? null} pages={imgs.data?.pages ?? []} />
          </div>
        )}
      </div>
      {editing && rep && <AnalysisDialog rep={rep} onClose={() => setEditing(false)} />}
    </div>
  );
}

/* ---------------- the sheet (exported as the image) ---------------- */


const Sheet = forwardRef<HTMLDivElement, { rep: Report; photo: string | null; pages: string[] }>(function Sheet({ rep, photo, pages }, ref) {
  const s = rep.revenue.summary;
  const a = rep.analysis;
  const figures: { whole: string; dec?: string; caption: string }[] = [];
  const split = (n: string) => { const [w, d] = n.split(","); return { whole: w, dec: d }; };
  if (s) {
    figures.push({ ...split(mi(s.average)), caption: `Faturamento médio mensal de ${s.year}, R$ milhões (${s.months.length} meses)` });
    if (s.growth_same_months !== null) figures.push({ whole: `${s.growth_same_months >= 0 ? "+" : ""}${Math.round(s.growth_same_months * 100)}`, caption: `% sobre os mesmos meses de ${s.previous_year}` });
    if (s.previous_total) figures.push({ ...split(mi(s.previous_total)), caption: `Faturamento de ${s.previous_year}, R$ milhões` });
  }
  if (rep.debt?.total) figures.push({ ...split(mi(rep.debt.total)), caption: `Endividamento total, R$ milhões${rep.debt.date ? `, base ${fmtDate(rep.debt.date)}` : ""}` });
  if (rep.debt?.times_average_revenue) figures.push({ ...split(rep.debt.times_average_revenue.toLocaleString("pt-BR", { maximumFractionDigits: 1, minimumFractionDigits: 1 })), caption: "Endividamento em meses de faturamento médio" });
  if (rep.customers) figures.push({ ...split(rep.customers.top3_share.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })), caption: "% do faturamento nos três maiores clientes" });

  const stageNow = rep.checklist.stage ?? null;
  const stages = rep.checklist.stages ?? [];
  const items = (rep.checklist.documents ?? []).filter((i) => !stages.length || i.stage === stageNow);
  const title = rep.company.razao_social;
  const isCompany = rep.company.tax_id_label !== "CPF";
  // two lines at most: shrink long names until they fit the 880px measure on two lines
  const titleSize = Math.max(56, Math.min(104, Math.floor(1720 / (title.length * 0.6))));
  // the visit photograph if there is one, then the case's own document pages, never an empty cell
  const pics = [photo, ...pages].filter((x): x is string => !!x);
  const hasRevenue = !!s;
  const hasPeopleData = (rep.debt?.items ?? []).length > 0 || !!rep.customers;

  return (
    <div className="rs" ref={ref}>
      {/* masthead: gutterless mosaic, header flush on its upper edge */}
      <header className="rs-band">
        <div className="rs-mosaic">
          <div className="rs-cell rs-span2x2" data-kind={photo ? "photo" : "page"}>{pics[0] ? <img src={pics[0]} alt={photo ? "Fotografia da visita comercial" : "Primeira página de um documento do cadastro"} /> : null}</div>
          <div className="rs-cell rs-tile-accent rs-span-rows" />
          <div className="rs-cell" data-kind="page">{pics[1] ? <img src={pics[1]} alt="" /> : null}</div>
          <div className="rs-cell rs-tile-ink" />
          <div className="rs-cell" data-kind="page">{pics[2] ? <img src={pics[2]} alt="" /> : null}</div>
          <div className="rs-cell rs-span2" data-kind="page">{pics[3] ? <img src={pics[3]} alt="" /> : null}</div>
          <div className="rs-cell rs-tile-ink" />
        </div>
        <div className="rs-head">
          <div className="rs-wordmark"><LogoMark size={26} /><span>CadastroAI</span></div>
          <div className="rs-tab"><span>{rep.registration.code}</span><span>{rep.registration.kind_label}, {rep.registration.modality_label}</span><span>Referência {fmtDate(rep.reference_date)}</span></div>
        </div>
      </header>

      <section className="rs-titlebar">
        <p className="rs-standfirst">{isCompany ? "Relatório de análise de crédito" : "Relatório de análise cadastral"}{rep.company.cnpj ? `, ${rep.company.tax_id_label} ${rep.company.cnpj}` : ""}.{rep.company.endereco ? ` ${rep.company.endereco}.` : ""}</p>
        <h1 className="rs-title" style={{ fontSize: titleSize }}>{title}</h1>
      </section>

      {/* ledger aligned on the decimal */}
      {figures.length > 0 && (
        <section className="rs-ledger">
          <h2 className="rs-two"><span className="rs-soft">Os números</span><span>do cadastro</span></h2>
          <div className="rs-figures">
            {figures.slice(0, 6).map((f) => (
              <div key={f.caption} className="rs-figure">
                <span className="rs-whole num">{f.whole}</span>
                <span className="rs-dec num">{f.dec ? `,${f.dec}` : ""}</span>
                <span className="rs-caption">{f.caption}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* fixed output beside the reading column */}
      <section className="rs-split" data-single={!hasRevenue}>
        {hasRevenue && <div className="rs-field"><RevenueChart rep={rep} /></div>}
        <div className="rs-reading">
          <h2 className="rs-h">Pontos de atenção</h2>
          {rep.findings.top.length === 0 ? (
            <p>Nenhum ponto em aberto nas verificações automáticas.</p>
          ) : rep.findings.top.slice(0, 5).map((f) => (
            <div key={f.title} className="rs-point">
              <p className="rs-point-title">
                <span className="rs-sev" data-tone={SEVERITY[f.severity].tone}>{SEVERITY[f.severity].label}</span>
                {f.title}{f.count > 1 ? ` (${f.count} documentos)` : ""}{f.source === "ai" ? <span className="rs-src">IA</span> : null}
              </p>
              <p className="rs-point-body">{f.explanation}</p>
            </div>
          ))}
          {Object.keys(rep.findings.by_severity).length > 0 && (
            <p className="rs-meta">Em aberto: {Object.entries(rep.findings.by_severity).map(([k, n]) => `${n} ${SEVERITY[k as keyof typeof SEVERITY].label.toLowerCase()}`).join(", ")}.</p>
          )}
        </div>
      </section>

      {/* documents: stage tabs, banded rows */}
      <section className="rs-docs">
        <h2 className="rs-two"><span className="rs-soft">Documentação</span><span>{stages.find((x) => x.current)?.label ?? "exigida"}</span></h2>
        <div className="rs-agenda">
          <div className="rs-tabs">
            {(stages.length ? stages : [{ id: "all", label: "Exigências", done: items.filter((i) => i.state === "ok").length, total: items.length, current: true }]).map((st) => (
              <div key={st.id} className="rs-tab-block" data-active={st.current}>
                <span>{st.label}</span>
                <span className="num">{st.done} de {st.total}</span>
              </div>
            ))}
          </div>
          <div className="rs-bands">
            {items.map((i: ChecklistItem) => (
              <div key={i.id} className="rs-band-row">
                <span className="rs-state" data-tone={CHECK_STATE[i.state].tone}>{CHECK_STATE[i.state].label}</span>
                <span className="rs-band-title">{i.label}<small>{i.documents?.length ? i.documents.map((d) => d.name).join(", ") : i.state_note ?? i.note ?? ""}</small></span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* names in columns */}
      <section className="rs-names">
        <h2 className="rs-h">{isCompany ? "Pessoas e relações" : "Pessoa"}</h2>
        {isCompany && rep.governance && (rep.governance.administradores || rep.governance.forma_assinatura || rep.governance.consolidado) && (
          <dl className="rs-governance">
            <div><dt>Administradores</dt><dd>{rep.governance.administradores ?? "Não identificados no contrato"}</dd></div>
            <div><dt>Assinam pela empresa</dt><dd>{rep.governance.responsaveis_assinatura ?? rep.governance.administradores ?? "—"}</dd></div>
            <div><dt>Forma de assinatura</dt><dd>{rep.governance.forma_assinatura ?? "—"}</dd></div>
            <div><dt>Contrato consolidado</dt><dd>{rep.governance.consolidado ?? "—"}</dd></div>
          </dl>
        )}
        <div className="rs-cols">
          <div>
            <p className="rs-soft">{isCompany ? "Sócios" : "Titular"}</p>
            {rep.partners.length === 0 && <p className="rs-soft">Não identificados nos documentos</p>}
            {rep.partners.map((p) => {
              const last = p.irpf[p.irpf.length - 1];
              return (
                <p key={p.nome}>{p.nome}<small>{[p.cpf, last?.bens ? `bens ${brl(last.bens)} (IRPF ${last.exercicio})` : null, p.fora_do_quadro ? "fora do quadro" : null].filter(Boolean).join(", ")}</small></p>
              );
            })}
          </div>
          {(isCompany || hasPeopleData) && (
            <div>
              <p className="rs-soft">Credores</p>
              {(rep.debt?.items ?? []).length === 0 && <p className="rs-soft">Sem relação de endividamento</p>}
              {(rep.debt?.items ?? []).map((d) => <p key={d.instituicao}>{d.instituicao}<small>{brl(d.tomado)}</small></p>)}
            </div>
          )}
          {(isCompany || hasPeopleData) && (
            <div>
              <p className="rs-soft">Maiores clientes</p>
              {!rep.customers && <p className="rs-soft">Sem curva ABC</p>}
              {rep.customers?.top.map((c) => <p key={c.cliente}>{c.cliente}<small>{c.percentual.toLocaleString("pt-BR")}% do faturamento</small></p>)}
            </div>
          )}
        </div>
        {rep.statements.length > 0 && (
          <table className="rs-table">
            <thead><tr><th>Exercício</th><th>Receita líquida</th><th>Lucro líquido</th><th>Patrimônio líquido</th><th>Ativo total</th></tr></thead>
            <tbody>
              {rep.statements.map((st) => (
                <tr key={st.exercicio ?? "?"}>
                  <td>{st.exercicio}</td><td className="num">{brl(st.receita_liquida)}</td>
                  <td className="num" data-negative={(st.lucro_liquido ?? 0) < 0}>{brl(st.lucro_liquido)}</td>
                  <td className="num">{brl(st.patrimonio_liquido)}</td><td className="num">{brl(st.ativo_total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* close: the analyst's opinion on a full ink page */}
      <section className="rs-close">
        <div className="rs-close-grid">
          <div>
            <p className="rs-soft-ink">Recomendação do analista</p>
            <p className="rs-recommendation" data-empty={!a.recomendacao}>{a.recomendacao ?? "Sem recomendação registrada"}</p>
            <dl className="rs-terms">
              <div><dt>Limite total</dt><dd>{a.limite_total ?? "—"}</dd></div>
              <div><dt>Taxa</dt><dd>{a.taxa ?? "—"}</dd></div>
              <div><dt>Comercial</dt><dd>{a.comercial ?? "—"}</dd></div>
              <div><dt>Região</dt><dd>{a.regiao ?? "—"}</dd></div>
            </dl>
          </div>
          <div>
            <p className="rs-soft-ink">Parecer</p>
            <p className="rs-opinion">{a.parecer ?? "O analista ainda não registrou o parecer."}</p>
            {rep.decision && (
              <p className="rs-decision">
                Decisão registrada: {DECISIONS[rep.decision.action] ?? rep.decision.action}
                {rep.decision.by ? ` por ${rep.decision.by}` : ""} em {fmtDateTime(rep.decision.at)}
                {rep.decision.reason ? `: “${rep.decision.reason}”` : "."}
              </p>
            )}
          </div>
        </div>
        <p className="rs-foot">
          Gerado pelo CadastroAI em {fmtDateTime(rep.generated_at)} por {rep.generated_by}. Valores lidos dos documentos enviados; confira no original.
          Não inclui consultas a bureaus de crédito nem ao SCR.
        </p>
      </section>
    </div>
  );
});

function RevenueChart({ rep }: { rep: Report }) {
  const s = rep.revenue.summary!;
  const cur = rep.revenue.series[s.year] ?? {};
  const prev = s.previous_year ? rep.revenue.series[s.previous_year] ?? {} : {};
  const values = [...Object.values(cur), ...Object.values(prev)];
  const max = Math.max(...values, 1);
  const top = Math.ceil(max / 5_000_000) * 5_000_000;
  const W = 640, H = 360, padL = 44, padB = 34, padT = 16;
  const plotW = W - padL - 8, plotH = H - padB - padT;
  const slot = plotW / 12, bar = Math.min(18, (slot - 10) / 2);
  const y = (v: number) => padT + plotH - (v / top) * plotH;
  const lastCur = Math.max(...Object.keys(cur).map(Number), 0);
  const ticks = Array.from({ length: top / 5_000_000 + 1 }, (_, i) => i * 5_000_000);
  const barPath = (x: number, v: number) => {
    const h = Math.max(0, padT + plotH - y(v));
    const r = Math.min(4, h);
    const yt = y(v);
    return `M${x},${padT + plotH} V${yt + r} Q${x},${yt} ${x + r},${yt} H${x + bar - r} Q${x + bar},${yt} ${x + bar},${yt + r} V${padT + plotH} Z`;
  };
  return (
    <figure className="rs-chart">
      <figcaption>
        <span className="rs-chart-title">Faturamento mensal, R$ milhões</span>
        <span className="rs-legend">
          <span><i style={{ background: "#2f78b0" }} />{s.previous_year}</span>
          <span><i style={{ background: "#6a9a1c" }} />{s.year}</span>
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={`Faturamento mensal de ${s.previous_year} e ${s.year}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - 8} y1={y(t)} y2={y(t)} stroke="#e6e6e3" strokeWidth={1} />
            <text x={padL - 8} y={y(t) + 4} textAnchor="end" className="rs-axis">{t / 1_000_000}</text>
          </g>
        ))}
        {MONTHS.map((m, i) => {
          const x0 = padL + i * slot + (slot - (bar * 2 + 2)) / 2;
          const pv = prev[String(i + 1)];
          const cv = cur[String(i + 1)];
          return (
            <g key={m}>
              {pv !== undefined && <path d={barPath(x0, pv)} fill="#2f78b0"><title>{`${m}/${s.previous_year}: R$ ${mi(pv)} mi`}</title></path>}
              {cv !== undefined && <path d={barPath(x0 + bar + 2, cv)} fill="#6a9a1c"><title>{`${m}/${s.year}: R$ ${mi(cv)} mi`}</title></path>}
              <text x={padL + i * slot + slot / 2} y={H - 12} textAnchor="middle" className="rs-axis">{m}</text>
            </g>
          );
        })}
        {lastCur > 0 && (
          <text x={padL + (lastCur - 1) * slot + slot / 2 + bar / 2 + 1} y={y(cur[String(lastCur)]) - 8} textAnchor="middle" className="rs-label">{mi(cur[String(lastCur)])}</text>
        )}
      </svg>
      <p className="rs-chart-note">
        {s.year}: {s.months.length} meses, total {brl(s.total)}.{s.previous_total ? ` ${s.previous_year}: total ${brl(s.previous_total)}.` : ""}
      </p>
    </figure>
  );
}

function AnalysisDialog({ rep, onClose }: { rep: Report; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const reg = useQuery({ queryKey: ["registration", rep.registration.id], queryFn: () => api<RegistrationDetail>(`/api/registrations/${rep.registration.id}`) });
  const [form, setForm] = useState<Record<string, string>>({});
  useEffect(() => {
    const a = rep.analysis;
    setForm({ recomendacao: a.recomendacao ?? "", limite_total: a.limite_total ?? "", taxa: a.taxa ?? "", comercial: a.comercial ?? "", regiao: a.regiao ?? "", parecer: a.parecer ?? "" });
  }, [rep]);
  const m = useMutation({
    mutationFn: () => api(`/api/registrations/${rep.registration.id}`, { method: "PATCH", json: { reference_fields: { ...(reg.data?.reference_fields ?? {}), ...Object.fromEntries(Object.entries(form).filter(([, v]) => v.trim())) } } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["report", rep.registration.id] });
      qc.invalidateQueries({ queryKey: ["registration", rep.registration.id] });
      toast("Parecer registrado.");
      onClose();
    },
  });
  const set = (k: string) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <Dialog title="Parecer da análise" onClose={onClose}>
      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
        <label className="label"><span>Recomendação</span>
          <select className="select" value={form.recomendacao ?? ""} onChange={set("recomendacao")}>
            <option value="">Escolher…</option>
            {RECOMMENDATIONS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <div className="grid-2">
          <label className="label"><span>Limite total</span><input className="input num" value={form.limite_total ?? ""} onChange={set("limite_total")} placeholder="R$ 1.500.000,00" /></label>
          <label className="label"><span>Taxa</span><input className="input num" value={form.taxa ?? ""} onChange={set("taxa")} placeholder="1,85% a.m." /></label>
          <label className="label"><span>Comercial responsável</span><input className="input" value={form.comercial ?? ""} onChange={set("comercial")} /></label>
          <label className="label"><span>Região</span><input className="input" value={form.regiao ?? ""} onChange={set("regiao")} /></label>
        </div>
        <label className="label"><span>Parecer</span><textarea className="textarea" rows={7} value={form.parecer ?? ""} onChange={set("parecer")} /></label>
        {m.isError && <p className="form-error">{errorText(m.error)}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" disabled={m.isPending || !reg.data}>Salvar parecer</button>
        </div>
      </form>
    </Dialog>
  );
}
