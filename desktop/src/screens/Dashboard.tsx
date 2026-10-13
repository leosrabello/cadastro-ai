import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Dashboard as D, RegistrationRow } from "../api/types";
import { useAuth } from "../auth";
import { ErrorBox, Skeleton, StatusMark } from "../components/ui";
import { fmtTaxId, plural, relative } from "../lib/format";
import "./dashboard.css";

export function Dashboard() {
  const { meta } = useAuth();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api<D>("/api/dashboard"), refetchInterval: 15_000 });
  const first = meta?.user.name.split(" ")[0];
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Bom dia" : hour < 18 ? "Boa tarde" : "Boa noite";

  if (q.isError) return <div className="page"><ErrorBox error={q.error} retry={() => q.refetch()} /></div>;
  const d = q.data;
  const c = d?.counts;
  const queue = c ? c.awaiting_review + c.processing_failed : 0;

  const tiles: { n?: number; label: string; note: string; to: string; tone?: string }[] = [
    { n: c?.ready_for_decision, label: "Prontos para decisão", note: "Documentos completos e sem pontos graves", to: "/fila?escopo=ready" },
    { n: c?.escalated, label: "Escalados", note: "Aguardam um supervisor", to: "/fila?escopo=escalated", tone: c?.escalated ? "warn" : undefined },
    { n: c?.missing_documents, label: "Com documento faltando", note: "Exigência obrigatória não recebida", to: "/cadastros?status=awaiting_review,pending_documents,awaiting_processing" },
    { n: c?.documents_in_flight, label: "Documentos em análise", note: "OCR e regras rodando no servidor", to: "/cadastros?status=processing" },
    { n: c?.processing_failed, label: "Falhas no processamento", note: "Precisam de nova tentativa", to: "/fila?escopo=failed", tone: c?.processing_failed ? "danger" : undefined },
    { n: c?.inbox, label: "Na caixa de entrada", note: "Chegaram pela pasta sem cadastro", to: "/entrada" },
  ];

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>{first ? `${greeting}, ${first}.` : "Painel"}</h1>
          <p className="muted">{c ? `${plural(c.decided_today, "decisão registrada", "decisões registradas")} hoje.` : " "}</p>
        </div>
      </div>

      <section className="board enter" aria-label="Situação do trabalho">
        <Link to={d?.next_up[0] ? `/cadastros/${d.next_up[0].id}` : "/fila"} className="tile tile-lead" style={{ ["--i" as string]: 0 }}>
          <h2 className="tile-lead-title">Fila de revisão</h2>
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
            <Link to="/fila" className="meta">Ver a fila inteira</Link>
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
