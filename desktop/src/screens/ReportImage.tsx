import { forwardRef, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { ClientRef, PortfolioSummary } from "../api/types";
import { Mark as LogoMark } from "../components/Logo";
import { ErrorBox, Skeleton, errorText, useToast } from "../components/ui";
import { fmtDate, fmtDateTime, plural } from "../lib/format";
import { isTauri } from "../lib/files";
import { exportSheetPng, useFitScale } from "../lib/sheet";
import { useCatalog } from "./Portfolio";
import { fmtDays, fmtPct, monthLabel, useReportParams, useSummary } from "./Reports";
import "./report.css";
import "./portfolio.css";

/** The portfolio report as a one-page image, in the same printed-annual sheet as the analysis report. */
export function ReportImage() {
  const toast = useToast();
  const cat = useCatalog();
  const { params, scope, apiQuery, filtered } = useReportParams();
  const q = useSummary(apiQuery);
  const sheet = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const scale = useFitScale(frame, q.data);
  const [busy, setBusy] = useState(false);
  const s = q.data;

  async function exportPng() {
    if (!sheet.current || !s) return;
    setBusy(true);
    try {
      const name = `relatorio-carteira-${scope}-${new Date().toISOString().slice(0, 10)}.png`;
      if (await exportSheetPng(sheet.current, name) && isTauri()) toast("Imagem salva.");
    } catch (e) {
      toast(`Não foi possível gerar a imagem: ${errorText(e)}`, "danger");
    } finally {
      setBusy(false);
    }
  }

  const filters: string[] = [];
  if (s && filtered) {
    const com = params.get("comercial");
    if (com) filters.push(com === "none" ? "sem comercial" : `comercial ${cat.data?.commercials.find((c) => c.id === com)?.name ?? ""}`);
    const st = params.get("status");
    if (st && scope !== "all") filters.push(`status ${cat.data?.statuses[scope].find((x) => x.key === st)?.label ?? st}`);
    const sit = params.get("situacao");
    if (sit) filters.push(`situação ${cat.data?.situations[sit as keyof typeof cat.data.situations] ?? sit}`);
    if (params.get("q")) filters.push(`busca "${params.get("q")}"`);
    if (params.get("entrada_de") || params.get("entrada_ate")) filters.push(`entrada ${fmtDate(params.get("entrada_de"))} a ${fmtDate(params.get("entrada_ate"))}`);
    if (params.get("comite_de") || params.get("comite_ate")) filters.push(`comitê ${fmtDate(params.get("comite_de"))} a ${fmtDate(params.get("comite_ate"))}`);
  }

  return (
    <div className="page report-page">
      <div className="page-head">
        <div>
          <Link to={`/relatorios?${params}`} className="meta">Relatórios da carteira</Link>
          <h1>Imagem do relatório</h1>
          <p className="muted">Os mesmos números da tela de relatórios, numa página para enviar ou imprimir.</p>
        </div>
        <button className="btn btn-primary" onClick={exportPng} disabled={!s || busy}>{busy ? "Gerando…" : "Baixar imagem"}</button>
      </div>
      {q.isError ? <ErrorBox error={q.error} retry={() => q.refetch()} /> : (
        <div className="report-frame" ref={frame} style={{ height: sheet.current ? sheet.current.offsetHeight * scale : undefined }}>
          {!s ? <Skeleton h={900} /> : (
            <div style={{ transform: `scale(${scale})`, transformOrigin: "top left", width: 1600 }}>
              <PortfolioSheet ref={sheet} s={s} filters={filters} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const split = (n: string) => { const [w, d] = n.split(","); return { whole: w, dec: d }; };

const PortfolioSheet = forwardRef<HTMLDivElement, { s: PortfolioSummary; filters: string[] }>(function PortfolioSheet({ s, filters }, ref) {
  const k = s.kpis;
  const one7 = s.modality === "one7";
  const title = s.modality === "all" ? "Carteira consolidada" : `Carteira ${s.modality_label}`;
  const figures: { whole: string; dec?: string; caption: string }[] = [
    { whole: String(k.total_clients), caption: s.filtered ? `clientes no filtro, de ${s.population}` : `clientes na carteira, ${plural(k.commercials, "comercial", "comerciais")}` },
    { whole: k.approval_rate === null ? "—" : String(Math.round(k.approval_rate * 100)), caption: `% de aprovação: ${k.approved} aptos, ${k.denied} negados` },
    { ...(k.avg_days_to_approved === null ? { whole: "—" } : split(String(k.avg_days_to_approved).replace(".", ","))), caption: `dias em média da entrada até apto a operar (${plural(k.avg_days_to_approved_basis, "pasta", "pastas")})` },
    { ...(s.signatures.avg_signature_days === null ? { whole: "—" } : split(String(s.signatures.avg_signature_days).replace(".", ","))), caption: `dias em média da emissão à assinatura (${plural(s.signatures.signed_basis, "contrato", "contratos")})` },
    { whole: String(k.overdue), caption: `atrasados: ${s.sla_days} dias ou mais no mesmo status` },
    one7 ? { whole: String(s.signatures.in_process), caption: "contratos aguardando assinatura" } : { whole: String(k.risk_exit), caption: `em saída de risco; ${k.limit_expired} com limite vencido` },
  ];
  const statuses = s.by_status.filter((x) => x.count > 0);

  return (
    <div className="rs ps" ref={ref}>
      <header className="ps-head">
        <div className="rs-wordmark"><LogoMark size={26} /><span>CadastroAI</span></div>
        <div className="rs-tab"><span>Relatório da carteira</span><span>{s.modality_label}</span><span>Referência {fmtDate(s.generated_at)}</span></div>
      </header>

      <section className="rs-titlebar">
        <p className="rs-standfirst">{s.modality === "all" ? "Soma das carteiras Normal e One7." : `Somente a carteira ${s.modality_label}.`}{filters.length ? ` Filtros: ${filters.join("; ")}.` : " Sem filtros."}</p>
        <h1 className="rs-title">{title}</h1>
      </section>

      <section className="rs-ledger">
        <h2 className="rs-two"><span className="rs-soft">Os números</span><span>da carteira</span></h2>
        <div className="rs-figures">
          {figures.map((f) => (
            <div key={f.caption} className="rs-figure">
              <span className="rs-whole num">{f.whole}</span>
              <span className="rs-dec num">{f.dec ? `,${f.dec}` : ""}</span>
              <span className="rs-caption">{f.caption}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="rs-split">
        <div className="rs-field"><StatusChart statuses={statuses} consolidated={s.modality === "all"} /></div>
        <div className="rs-reading">
          <h2 className="rs-h">Pontos de atenção</h2>
          <Attention title={`Acima do prazo de ${s.sla_days} dias`} items={s.over_sla.slice(0, 6)} more={s.over_sla.length - 6} days empty="Nenhum cliente parado acima do prazo." />
          {!one7 && <Attention title="Saída de risco" items={s.risk_exit.slice(0, 6)} more={s.risk_exit.length - 6} empty="Nenhum cliente marcado." />}
          {!one7 && <Attention title="Limite vencido" items={s.limit_expired.slice(0, 6)} more={s.limit_expired.length - 6} empty="Nenhum cliente marcado." />}
        </div>
      </section>

      <section className="rs-docs">
        <h2 className="rs-two"><span className="rs-soft">Comerciais</span><span>por número de clientes</span></h2>
        <div className="ps-commercials">
          <div className="ps-com-row ps-com-head"><span>Comercial</span><span>Clientes</span><span>Aptos</span><span>Negados</span><span>Em andamento</span><span>Atrasados</span><span>Aprovação</span><span>Até apto</span></div>
          {s.by_commercial.slice(0, 12).map((c) => (
            <div key={c.id ?? "none"} className="ps-com-row">
              <span className="ps-com-name" data-none={!c.id}>{c.name}</span>
              <span className="num">{c.total}</span><span className="num">{c.approved}</span><span className="num">{c.denied}</span>
              <span className="num">{c.in_progress}</span><span className="num">{c.overdue}</span>
              <span className="num">{fmtPct(c.approval_rate)}</span><span className="num">{fmtDays(c.avg_days_to_approved)}</span>
            </div>
          ))}
          {s.by_commercial.length > 12 && <p className="rs-meta">e mais {plural(s.by_commercial.length - 12, "comercial", "comerciais")} com menos clientes.</p>}
        </div>
      </section>

      <section className="rs-names">
        <h2 className="rs-h">Tempo e fluxo</h2>
        <div className="rs-cols">
          <div>
            <p className="rs-soft">Maior tempo parado</p>
            {s.stalled.length === 0 && <p className="rs-soft">Nenhum cliente em andamento</p>}
            {s.stalled.map((x) => <p key={x.id}>{x.name}<small>{x.days_in_status} dias em {x.status_label}</small></p>)}
          </div>
          <div>
            <p className="rs-soft">Tempos médios</p>
            <p>Até apto a operar<small>{fmtDays(k.avg_days_to_approved)}</small></p>
            <p>Contrato SEC<small>{fmtDays(s.signatures.avg_signature_days_sec)}</small></p>
            <p>Contrato FIDC<small>{fmtDays(s.signatures.avg_signature_days_fidc)}</small></p>
            <p>Contratos em aberto<small>{plural(s.signatures.in_process, "contrato", "contratos")}, há {fmtDays(s.signatures.avg_open_days)} em média</small></p>
          </div>
          <div>
            <p className="rs-soft">Entradas por mês</p>
            {s.by_month.length === 0 && <p className="rs-soft">Sem datas de entrada</p>}
            {s.by_month.slice(-6).map((m) => <p key={m.month}>{monthLabel(m.month)}<small>{plural(m.count, "pasta", "pastas")}</small></p>)}
          </div>
        </div>
      </section>

      <section className="rs-close">
        <div className="rs-close-grid">
          <div>
            <p className="rs-soft-ink">Situação das pastas</p>
            <p className="rs-recommendation">{k.in_progress} em andamento</p>
            <dl className="rs-terms">
              <div><dt>Concluídas</dt><dd>{k.approved}</dd></div>
              <div><dt>Negadas</dt><dd>{k.denied}</dd></div>
              <div><dt>Atrasadas</dt><dd>{k.overdue}</dd></div>
              <div><dt>Comercial destaque</dt><dd>{k.top_commercial ? `${k.top_commercial.name}, ${plural(k.top_commercial.total, "cliente", "clientes")}` : "—"}</dd></div>
            </dl>
          </div>
          <div>
            <p className="rs-soft-ink">Como os números são calculados</p>
            <p className="rs-opinion">
              Concluída é a pasta em Apto a Operar; negada, em Negada{one7 ? " ou com resultado negado no comitê ONE7" : ""}. Atrasada é a pasta parada no mesmo status há {s.sla_days} dias ou
              mais. O tempo até apto vai da data de entrada até a primeira vez em Apto a Operar. O tempo de assinatura vai da emissão do contrato no portal até a última assinatura,
              conforme as datas conferidas em Assinaturas.
            </p>
          </div>
        </div>
        <p className="rs-foot">Gerado pelo CadastroAI em {fmtDateTime(s.generated_at)} por {s.generated_by}, a partir dos clientes gravados no sistema nesse momento.</p>
      </section>
    </div>
  );
});

function Attention({ title, items, more, days, empty }: { title: string; items: ClientRef[]; more: number; days?: boolean; empty: string }) {
  return (
    <div className="rs-point">
      <p className="rs-point-title">{title}</p>
      {items.length === 0 ? <p className="rs-point-body">{empty}</p> : (
        <p className="rs-point-body">
          {items.map((x) => `${x.name} (${days ? `${x.days_in_status} dias` : x.status_label})`).join(", ")}{more > 0 ? `, e mais ${more}` : ""}.
        </p>
      )}
    </div>
  );
}

function StatusChart({ statuses, consolidated }: { statuses: PortfolioSummary["by_status"]; consolidated: boolean }) {
  const max = Math.max(1, ...statuses.map((x) => x.count));
  const rowH = 34, W = 640, labelW = 250, padT = 8;
  const H = padT + statuses.length * rowH + 8;
  const color = (o: string | null) => (o === "approved" ? "#6a9a1c" : o === "denied" ? "#5c5c5c" : "#2f78b0");
  return (
    <figure className="rs-chart">
      <figcaption>
        <span className="rs-chart-title">Clientes por status</span>
        <span className="rs-legend">
          <span><i style={{ background: "#6a9a1c" }} />Apto</span>
          <span><i style={{ background: "#5c5c5c" }} />Negado</span>
          <span><i style={{ background: "#2f78b0" }} />Em andamento</span>
        </span>
      </figcaption>
      {statuses.length === 0 ? <p className="rs-empty">Nenhum cliente.</p> : (
        <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={statuses.map((x) => `${x.label}: ${x.count}`).join(", ")}>
          {statuses.map((x, i) => {
            const y = padT + i * rowH;
            const w = Math.max(2, ((W - labelW - 50) * x.count) / max);
            return (
              <g key={`${x.modality}-${x.key}`}>
                <text x={labelW - 10} y={y + 21} textAnchor="end" className="rs-axis">{consolidated ? `${x.modality === "one7" ? "One7" : "Normal"}: ` : ""}{x.label}</text>
                <rect x={labelW} y={y + 6} width={w} height={20} rx={3} fill={color(x.outcome)} />
                <text x={labelW + w + 8} y={y + 21} className="rs-label">{x.count}</text>
              </g>
            );
          })}
        </svg>
      )}
    </figure>
  );
}
