import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { HistoryEvent, Page, RegStatus } from "../api/types";
import { useAuth } from "../auth";
import { Empty, ErrorBox, LoadingRows, Pager, errorText } from "../components/ui";
import { ACTIONS, STATUS, fmtTime } from "../lib/format";
import "./history.css";

const GROUPS = [
  { key: "", label: "Todas as ações" },
  { key: "registration.", label: "Decisões e cadastros" },
  { key: "finding.", label: "Pontos resolvidos" },
  { key: "field.", label: "Correções de campos" },
  { key: "document.", label: "Documentos" },
  { key: "auth.", label: "Acessos" },
  { key: "settings.", label: "Configurações" },
  { key: "user.", label: "Usuários" },
];

function isoDay(d: Date) {
  // taste-skill-ignore: zero-padding builds an ISO date, not an index label
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const weekday = new Intl.DateTimeFormat("pt-BR", { weekday: "long" });
const dayMonth = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short" });

export function History() {
  const { meta } = useAuth();
  const [params, setParams] = useSearchParams();
  const registration = params.get("cadastro");
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - i);
    return d;
  });
  const [day, setDay] = useState<string | null>(registration ? null : isoDay(days[0]));
  const [group, setGroup] = useState("");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 250);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => setPage(1), [day, group, debounced, registration]);

  const qs = new URLSearchParams({ page: String(page), page_size: "60" });
  if (day) {
    qs.set("date_from", day);
    qs.set("date_to", day);
  }
  if (group) qs.set("action", group);
  if (debounced) qs.set("q", debounced);
  if (registration) qs.set("registration_id", registration);
  const q = useQuery({ queryKey: ["audit", qs.toString()], queryFn: () => api<Page<HistoryEvent>>(`/api/audit?${qs}`), placeholderData: keepPreviousData });
  const verify = useMutation({ mutationFn: () => api<{ valid: boolean; checked: number; broken_at: number | null }>("/api/audit/verify") });

  if (!meta?.permissions.audit) return <div className="page"><Empty title="Sem acesso ao histórico">O histórico completo é visível para supervisores, administradores e auditores.</Empty></div>;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Histórico</h1>
          <p className="muted">Toda análise, correção, decisão e acesso, na ordem em que aconteceu. Nada aqui pode ser editado ou apagado.</p>
        </div>
        <div className="history-verify">
          <button className="btn" onClick={() => verify.mutate()} disabled={verify.isPending}>{verify.isPending ? "Conferindo…" : "Conferir integridade"}</button>
          {verify.data && (
            <span className={verify.data.valid ? "meta" : "danger-text"}>
              {verify.data.valid ? `Íntegro: ${verify.data.checked} registros encadeados conferem.` : `Quebra na cadeia no registro ${verify.data.broken_at}. Avise a segurança da informação.`}
            </span>
          )}
          {verify.isError && <span className="danger-text">{errorText(verify.error)}</span>}
        </div>
      </div>

      <div className="spread" style={{ marginBottom: 20, flexWrap: "wrap" }}>
        <div className="row">
          <select className="select" style={{ width: 230 }} value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Tipo de ação">
            {GROUPS.map((g) => <option key={g.key} value={g.key}>{g.label}</option>)}
          </select>
          {registration && (
            <span className="meta">Filtrando um cadastro · <button className="link-btn" onClick={() => { setParams({}); setDay(isoDay(days[0])); }}>limpar</button></span>
          )}
        </div>
        <input className="input" type="search" style={{ width: 320 }} placeholder="Buscar por pessoa, ação ou código" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Buscar no histórico" />
      </div>

      <div className="agenda">
        <div className="day-tabs" role="tablist" aria-label="Dia">
          {days.map((d, i) => {
            const key = isoDay(d);
            return (
              <button key={key} role="tab" aria-selected={day === key} className="day-tab" onClick={() => setDay(key)}>
                <span className="day-name">{i === 0 ? "Hoje" : i === 1 ? "Ontem" : weekday.format(d)}</span>
                <span className="day-date num">{dayMonth.format(d)}</span>
              </button>
            );
          })}
          <button role="tab" aria-selected={day === null} className="day-tab" onClick={() => setDay(null)}>
            <span className="day-name">Todos os dias</span>
            <span className="day-date">Busca completa</span>
          </button>
        </div>
        <div>
          {q.isError ? <ErrorBox error={q.error} retry={() => q.refetch()} /> : !q.data ? <LoadingRows rows={8} /> : q.data.items.length === 0 ? (
            <Empty title="Nenhum registro">Nada aconteceu com esses filtros{day ? " neste dia" : ""}.</Empty>
          ) : (
            <>
              <ol className="bands" style={{ opacity: q.isPlaceholderData ? 0.6 : 1 }}>
                {q.data.items.map((e) => (
                  <li key={e.id} className="band">
                    <span className="band-time num">{day ? fmtTime(e.at) : new Date(e.at).toLocaleDateString("pt-BR") + " " + fmtTime(e.at)}</span>
                    <span className="band-what">
                      <span className="band-title">{ACTIONS[e.action] ?? e.action}</span>
                      <span className="meta"><Detail e={e} labels={meta.field_labels} /></span>
                    </span>
                    <span className="band-who">
                      <span>{e.actor}</span>
                      {e.registration_code && e.registration_id && <Link className="meta num" to={`/cadastros/${e.registration_id}`}>{e.registration_code}</Link>}
                    </span>
                  </li>
                ))}
              </ol>
              <Pager page={page} pageSize={60} total={q.data.total} onPage={setPage} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Detail({ e, labels }: { e: HistoryEvent; labels: Record<string, string> }) {
  const d = e.details ?? {};
  const parts: string[] = [];
  if (d.field) parts.push(`${labels[d.field] ?? d.field}: ${d.before ?? "—"} → ${d.after ?? "—"}`);
  if (d.from && d.to) parts.push(`${STATUS[d.from as RegStatus]?.label ?? d.from} → ${STATUS[d.to as RegStatus]?.label ?? d.to}`);
  if (d.title) parts.push(String(d.title));
  if (d.filename) parts.push(String(d.filename));
  if (d.reason) parts.push(`“${d.reason}”`);
  if (d.note) parts.push(`“${d.note}”`);
  if (d.message) parts.push(String(d.message));
  if (e.entity_type === "setting") parts.push(`Configuração: ${e.entity_id}`);
  if (d.doc_type !== undefined) parts.push(`tipo ${d.doc_type ?? "não identificado"}, validade ${d.validity ?? "—"}, ${d.findings} ponto(s)`);
  return <>{parts.join(" · ")}</>;
}
