import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ModalityTag } from "../components/ModalitySwitch";
import { api } from "../api/client";
import type { Page, PriorityReason, RegistrationRow } from "../api/types";
import { Empty, ErrorBox, LoadingRows, Pager, StatusMark } from "../components/ui";
import { fmtTaxId, relative } from "../lib/format";
import "./queue.css";

const SCOPES = [
  { key: "all", label: "Tudo que precisa de alguém" },
  { key: "ready", label: "Prontos para decisão" },
  { key: "escalated", label: "Escalados" },
  { key: "failed", label: "Falhas" },
];

type QueuePage = Page<RegistrationRow> & { rules: { id: string; label: string; points: number }[] };

export function Queue() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const scope = params.get("escopo") ?? "all";
  const modality = params.get("modalidade") ?? "";
  const page = Number(params.get("pagina") ?? 1);
  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) v ? next.set(k, v) : next.delete(k);
    setParams(next);
  };
  const q = useQuery({
    queryKey: ["queue", scope, modality, page],
    queryFn: () => api<QueuePage>(`/api/queue?scope=${scope}&page=${page}&page_size=50${modality ? `&modality=${modality}` : ""}`),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  });

  return (
    <div className="page queue">
      <div className="page-head">
        <div>
          <h1>Fila de revisão</h1>
          <p className="muted">Ordenada por pontos de prioridade. Cada ponto vem de uma regra que você pode conferir ao lado.</p>
        </div>
      </div>
      <div className="row" style={{ marginBottom: 20, flexWrap: "wrap" }}>
        <div className="segmented" role="group" aria-label="Recorte da fila">
          {SCOPES.map((s) => (
            <button key={s.key} aria-pressed={scope === s.key} onClick={() => set({ escopo: s.key === "all" ? null : s.key, pagina: null })}>
              {s.label}
            </button>
          ))}
        </div>
        <select className="select" style={{ width: 190 }} value={modality} onChange={(e) => set({ modalidade: e.target.value || null, pagina: null })} aria-label="Modalidade">
          <option value="">Normal e One7</option>
          <option value="normal">Só Normal</option>
          <option value="one7">Só One7</option>
        </select>
      </div>
      <div className="queue-layout">
        <div>
          {q.isError ? (
            <ErrorBox error={q.error} retry={() => q.refetch()} />
          ) : !q.data ? (
            <LoadingRows rows={8} />
          ) : q.data.items.length === 0 ? (
            <Empty title="Nada nesta fila">Quando a análise automática terminar um cadastro, ele aparece aqui com os motivos da sua posição.</Empty>
          ) : (
            <>
              <ol className="queue-list enter">
                {q.data.items.map((r, i) => (
                  <li key={r.id} style={{ ["--i" as string]: Math.min(i, 10) }}>
                    <button className="queue-item" onClick={() => nav(`/cadastros/${r.id}`)}>
                      <span className="queue-score num">{r.priority_score}</span>
                      <span className="queue-who">
                        <span className="strong">{r.subject_name}</span>
                        <span className="meta num"><ModalityTag modality={r.modality} /> {r.code} · {fmtTaxId(r.tax_id)} · criado {relative(r.created_at)}</span>
                      </span>
                      <span className="queue-status"><StatusMark status={r.status} /></span>
                      <Reasons reasons={r.priority_reasons} />
                    </button>
                  </li>
                ))}
              </ol>
              <Pager page={page} pageSize={50} total={q.data.total} onPage={(p) => set({ pagina: String(p) })} />
            </>
          )}
        </div>
        <aside className="queue-rules" aria-label="Regras de prioridade">
          <h2>Como a posição é calculada</h2>
          <p className="meta" style={{ margin: "6px 0 14px" }}>Soma dos pontos das regras que se aplicam. Ajustável em Configurações. Nenhuma pontuação vem de IA.</p>
          <dl>
            {(q.data?.rules ?? []).map((r) => (
              <div key={r.id}>
                <dt>{r.label}</dt>
                <dd className="num">{r.points}</dd>
              </div>
            ))}
          </dl>
        </aside>
      </div>
    </div>
  );
}

function Reasons({ reasons }: { reasons: PriorityReason[] }) {
  if (!reasons.length) return <span className="queue-reasons meta">Sem regra de prioridade aplicada</span>;
  return (
    <span className="queue-reasons">
      {reasons.map((r) => (
        <span key={r.rule} className="queue-reason">
          <span>{r.label}</span>
          <span className="num muted">+{r.points}</span>
        </span>
      ))}
    </span>
  );
}
