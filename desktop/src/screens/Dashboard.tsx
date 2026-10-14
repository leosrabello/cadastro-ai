import { keepPreviousData, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Dashboard as D, Modality, PortfolioSummary, RegistrationRow } from "../api/types";
import { useAuth } from "../auth";
import { ErrorBox, Skeleton, StatusMark } from "../components/ui";
import { ModalitySwitch } from "../components/ModalitySwitch";
import { fmtTaxId, plural, relative } from "../lib/format";
import { MODALITY_LABEL, useModality } from "../lib/modality";
import "./dashboard.css";

export function Dashboard() {
  const { meta } = useAuth();
  const nav = useNavigate();
  const [modality, setModality] = useModality();
  const q = useQuery({ queryKey: ["dashboard", modality], queryFn: () => api<D>(`/api/dashboard?modality=${modality}`), refetchInterval: 15_000, placeholderData: keepPreviousData });
  const port = useQuery({ queryKey: ["portfolio-summary", modality], queryFn: () => api<PortfolioSummary>(`/api/portfolio/summary?modality=${modality}`), refetchInterval: 30_000, placeholderData: keepPreviousData });
  const m = `modalidade=${modality}`;
  const first = meta?.user.name.split(" ")[0];
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Bom dia" : hour < 18 ? "Boa tarde" : "Boa noite";

  if (q.isError) return <div className="page"><ErrorBox error={q.error} retry={() => q.refetch()} /></div>;
  const d = q.data;
  const c = d?.counts;
  const queue = c ? c.awaiting_review + c.processing_failed : 0;

  const tiles: { n?: number; label: string; note: string; to: string; tone?: string }[] = [
    { n: c?.ready_for_decision, label: "Prontos para decisão", note: "Documentos completos e sem pontos graves", to: `/fila?escopo=ready&${m}` },
    { n: c?.escalated, label: "Escalados", note: "Aguardam um supervisor", to: `/fila?escopo=escalated&${m}`, tone: c?.escalated ? "warn" : undefined },
    { n: c?.missing_documents, label: "Com documento faltando", note: "Exigência obrigatória não recebida", to: `/cadastros?status=awaiting_review,pending_documents,awaiting_processing&${m}` },
    { n: c?.documents_in_flight, label: "Documentos em análise", note: "OCR e regras rodando no servidor", to: `/cadastros?status=processing&${m}` },
    { n: c?.processing_failed, label: "Falhas no processamento", note: "Precisam de nova tentativa", to: `/fila?escopo=failed&${m}`, tone: c?.processing_failed ? "danger" : undefined },
    { n: c?.inbox, label: "Na caixa de entrada", note: "Das duas modalidades: ainda sem cadastro", to: "/entrada" },
  ];

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>{first ? `${greeting}, ${first}.` : "Painel"}</h1>
          <p className="muted">{c ? `${plural(c.decided_today, "decisão registrada", "decisões registradas")} hoje em ${MODALITY_LABEL[modality]}.` : " "}</p>
        </div>
        <ModalitySwitch value={modality} onChange={setModality} />
      </div>

      <section className="board enter" aria-label={`Situação do trabalho, ${MODALITY_LABEL[modality]}`} style={{ opacity: q.isPlaceholderData ? 0.6 : 1 }}>
        <Link to={d?.next_up[0] ? `/cadastros/${d.next_up[0].id}` : `/fila?${m}`} className="tile tile-lead" style={{ ["--i" as string]: 0 }}>
          <h2 className="tile-lead-title">Fila de revisão {MODALITY_LABEL[modality]}</h2>
          <div className="tile-lead-foot">
            <span className="tile-n num">{c ? queue : "–"}</span>
            <span className="tile-lead-cta">
              {queue ? "Abrir o primeiro da fila" : "Fila vazia"}
            </span>
          </div>
        </Link>
        {tiles.map((t, i) => (
          <Link key={t.label} to={t.to} className="tile" data-tone={t.tone} style={{ ["--i" as string]: i + 1 }}>
            <span className="tile-n num">{t.n ?? "–"}</span>
            <span className="tile-label">{t.label}</span>
            <span className="meta">{t.note}</span>
          </Link>
        ))}
      </section>

      <div className="dash-cols enter">
        <section style={{ ["--i" as string]: 2 }}>
          <div className="spread" style={{ marginBottom: 8 }}>
            <h2>Próximos da fila</h2>
            <Link to={`/fila?${m}`} className="meta">Ver a fila inteira</Link>
          </div>
          {!d ? <Skeleton h={180} /> : d.next_up.length === 0 ? (
            <p className="muted" style={{ padding: "18px 0" }}>Nada aguardando revisão. Novos documentos aparecem aqui assim que a análise automática termina.</p>
          ) : (
            <ol className="next-list">
              {d.next_up.map((r) => <NextRow key={r.id} r={r} onOpen={() => nav(`/cadastros/${r.id}`)} />)}
            </ol>
          )}
        </section>
        <section style={{ ["--i" as string]: 3 }}>
          <h2 style={{ marginBottom: 8 }}>Decididos nos últimos 7 dias</h2>
          {!d ? <Skeleton h={180} /> : d.recently_completed.length === 0 ? (
            <p className="muted" style={{ padding: "18px 0" }}>Nenhuma decisão nesta semana.</p>
          ) : (
            <ul className="done-list">
              {d.recently_completed.map((r) => (
                <li key={r.id}>
                  <Link to={`/cadastros/${r.id}`}>
                    <span>{r.subject_name}</span>
                    <StatusMark status={r.status} />
                    <span className="meta num">{relative(r.decided_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <PortfolioBand modality={modality} q={port} />

      {d && (
        <p className="system-line meta">
          {d.watcher.enabled ? (
            d.watcher.reachable ? (
              <>Pasta monitorada {d.watcher.folder} lida {relative(d.watcher.last_scan_at)}{d.watcher.pending_files ? `, ${plural(d.watcher.pending_files, "arquivo aguardando cópia terminar", "arquivos aguardando cópia terminar")}` : ""}.</>
            ) : (
              <span className="danger-text">Pasta monitorada inacessível: {d.watcher.last_error ?? "sem resposta"}.</span>
            )
          ) : (
            <>Monitoramento de pasta desligado.</>
          )}{" "}
          OCR {d.ocr.provider === "tesseract" ? "no servidor próprio" : d.ocr.provider}.{" "}
          {d.ai.enabled ? `Análise complementar por IA ligada (${d.ai.model}).` : "Análise por IA desligada; regras e OCR seguem ativos."}{" "}
          {d.processing.avg_seconds_24h !== null && `Média de ${String(d.processing.avg_seconds_24h).replace(".", ",")} s por documento nas últimas 24 h.`}
        </p>
      )}
    </div>
  );
}

function PortfolioBand({ modality, q }: { modality: Modality; q: UseQueryResult<PortfolioSummary> }) {
  const s = q.data;
  if (q.isError) return <section className="carteira"><ErrorBox error={q.error} retry={() => q.refetch()} /></section>;
  const k = s?.kpis;
  const sig = s?.signatures;
  const statuses = (s?.by_status ?? []).filter((x) => x.count > 0);
  const maxStatus = Math.max(1, ...statuses.map((x) => x.count));
  const facts: { value: string; label: string; note?: string; tone?: string; to?: string }[] = k ? [
    { value: String(k.total_clients), label: "Clientes na carteira", to: "/carteira" },
    { value: k.approval_rate === null ? "—" : `${Math.round(k.approval_rate * 100)}%`, label: "Taxa de aprovação", note: `${k.approved} aptos, ${k.denied} negados` },
    { value: days(k.avg_days_to_approved), label: "Tempo médio até apto", note: basis(k.avg_days_to_approved_basis, "pasta", "pastas") },
    { value: days(sig?.avg_signature_days ?? null), label: "Tempo médio de assinatura", note: basis(sig?.signed_basis ?? 0, "contrato", "contratos"), to: "/assinaturas" },
    { value: k.top_commercial ? k.top_commercial.name : "—", label: "Comercial destaque", note: k.top_commercial ? plural(k.top_commercial.total, "cliente", "clientes") : undefined },
    { value: String(k.overdue), label: `Atrasados (${s!.sla_days} dias no status)`, tone: k.overdue ? "warn" : undefined, to: "/relatorios?situacao=atrasado" },
    ...(modality === "normal" ? [
      { value: String(k.risk_exit), label: "Saída de risco", tone: k.risk_exit ? "danger" : undefined },
      { value: String(k.limit_expired), label: "Limite vencido", tone: k.limit_expired ? "warn" : undefined },
    ] : [{ value: String(sig?.in_process ?? 0), label: "Contratos aguardando assinatura", to: "/assinaturas" },
         { value: String(k.in_progress), label: "Pastas em andamento" }]),
  ] : [];
  return (
    <section className="carteira enter" aria-labelledby="carteira-h" style={{ opacity: q.isPlaceholderData ? 0.6 : 1 }}>
      <div className="spread" style={{ marginBottom: 12 }}>
        <h2 id="carteira-h">Carteira {MODALITY_LABEL[modality]}</h2>
        <Link to="/relatorios" className="meta">Abrir relatórios</Link>
      </div>
      {!s ? <Skeleton h={200} /> : k!.total_clients === 0 ? (
        <p className="muted">Nenhum cliente {MODALITY_LABEL[modality]} na carteira. Importe o backup do painel antigo em Carteira, ou cadastre o primeiro cliente.</p>
      ) : (
        <>
          <div className="facts-strip">
            {facts.map((f) => {
              const body = (
                <>
                  <span className="fact-value num" data-tone={f.tone} data-long={f.value.length > 10}>{f.value}</span>
                  <span className="fact-label">{f.label}</span>
                  {f.note && <span className="meta">{f.note}</span>}
                </>
              );
              return f.to ? <Link key={f.label} to={f.to} className="fact">{body}</Link> : <div key={f.label} className="fact">{body}</div>;
            })}
          </div>
          <div className="dash-cols" style={{ marginTop: 32 }}>
            <section>
              <h3 style={{ marginBottom: 10 }}>Clientes por status</h3>
              <ul className="bars">
                {statuses.map((x) => (
                  <li key={x.key}>
                    <span className="bar-label">{x.label}</span>
                    <span className="bar-track"><span className="bar-fill" data-outcome={x.outcome ?? undefined} style={{ width: `${(x.count / maxStatus) * 100}%` }} /></span>
                    <span className="num strong">{x.count}</span>
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <h3 style={{ marginBottom: 10 }}>Por comercial</h3>
              <table className="table compact">
                <thead><tr><th>Comercial</th><th className="num">Clientes</th><th className="num">Aptos</th><th className="num">Aprovação</th></tr></thead>
                <tbody>
                  {s.by_commercial.slice(0, 8).map((c) => (
                    <tr key={c.id ?? "none"}>
                      <td className={c.id ? undefined : "muted"}>{c.name}</td>
                      <td className="num">{c.total}</td>
                      <td className="num">{c.approved}</td>
                      <td className="num">{c.approval_rate === null ? "—" : `${Math.round(c.approval_rate * 100)}%`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {s.by_commercial.length > 8 && <Link to="/relatorios" className="meta">Ver os {s.by_commercial.length} comerciais</Link>}
            </section>
          </div>
        </>
      )}
    </section>
  );
}

function days(v: number | null): string {
  return v === null ? "—" : `${String(v).replace(".", ",")} ${v === 1 ? "dia" : "dias"}`;
}

function basis(n: number, one: string, many: string): string {
  return n ? `média de ${plural(n, one, many)}` : "sem base ainda";
}

function NextRow({ r, onOpen }: { r: RegistrationRow; onOpen: () => void }) {
  return (
    <li>
      <button className="next-row" onClick={onOpen}>
        <span className="next-score num" title="Pontos de prioridade">{r.priority_score}</span>
        <span className="next-body">
          <span className="next-name">{r.subject_name}</span>
          <span className="meta num">{r.code} · {fmtTaxId(r.tax_id)}</span>
        </span>
        <span className="next-why">{r.priority_reasons.slice(0, 2).map((x) => x.label).join(" · ") || "Aguardando revisão"}</span>
      </button>
    </li>
  );
}
