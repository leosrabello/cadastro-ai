import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Page, RegistrationRow } from "../api/types";
import { useAuth } from "../auth";
import { ModalityTag } from "../components/ModalitySwitch";
import { Empty, ErrorBox, LoadingRows, Pager, StatusMark } from "../components/ui";
import { fmtTaxId, relative } from "../lib/format";

const FILTERS: { key: string; label: string; statuses: string }[] = [
  { key: "todos", label: "Todos", statuses: "" },
  { key: "revisao", label: "Aguardando revisão", statuses: "awaiting_review,processing_failed" },
  { key: "analise", label: "Em análise", statuses: "awaiting_processing,processing" },
  { key: "pendentes", label: "Pendentes", statuses: "pending_documents" },
  { key: "decididos", label: "Decididos", statuses: "approved,rejected" },
];

type Sort = "priority" | "created" | "updated" | "name" | "code";

export function Registrations() {
  const nav = useNavigate();
  const { meta } = useAuth();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const kind = params.get("tipo") ?? "";
  const modality = params.get("modalidade") ?? "";
  const sort = (params.get("ordem") as Sort) ?? "priority";
  const direction = params.get("dir") ?? (sort === "name" || sort === "code" ? "asc" : "desc");
  const page = Number(params.get("pagina") ?? 1);
  const [search, setSearch] = useState(params.get("q") ?? "");

  useEffect(() => {
    const t = setTimeout(() => update({ q: search || null, pagina: null }), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) v === null || v === "" ? next.delete(k) : next.set(k, v);
    setParams(next, { replace: true });
  }

  const query = new URLSearchParams({ sort, direction, page: String(page), page_size: "25" });
  if (params.get("q")) query.set("q", params.get("q")!);
  if (status) query.set("status", status);
  if (kind) query.set("kind", kind);
  if (modality) query.set("modality", modality);
  const q = useQuery({
    queryKey: ["registrations", query.toString()],
    queryFn: () => api<Page<RegistrationRow>>(`/api/registrations?${query}`),
    placeholderData: keepPreviousData,
    refetchInterval: 20_000,
  });

  const sortBy = (s: Sort) => update({ ordem: s, dir: sort === s ? (direction === "asc" ? "desc" : "asc") : null, pagina: null });
  const sortAttr = (s: Sort) => (sort === s ? (direction === "asc" ? "ascending" : "descending") : undefined);
  const activeFilter = FILTERS.find((f) => f.statuses === status)?.key ?? (status ? "custom" : "todos");

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Cadastros</h1>
          <p className="muted">{q.data ? `${q.data.total} no total com os filtros atuais.` : " "}</p>
        </div>
      </div>
      <div className="spread" style={{ marginBottom: 16, flexWrap: "wrap" }}>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <div className="segmented" role="group" aria-label="Filtrar por situação">
            {FILTERS.map((f) => (
              <button key={f.key} aria-pressed={activeFilter === f.key} onClick={() => update({ status: f.statuses || null, pagina: null })}>
                {f.label}
              </button>
            ))}
          </div>
          <select className="select" style={{ width: 170 }} value={modality} onChange={(e) => update({ modalidade: e.target.value || null, pagina: null })} aria-label="Modalidade">
            <option value="">Normal e One7</option>
            <option value="normal">Só Normal</option>
            <option value="one7">Só One7</option>
          </select>
          <select className="select" style={{ width: 170 }} value={kind} onChange={(e) => update({ tipo: e.target.value || null, pagina: null })} aria-label="Tipo de cadastro">
            <option value="">Pessoa física e jurídica</option>
            {Object.entries(meta?.profiles ?? {}).map(([k, p]) => (
              <option key={k} value={k}>{p.label}</option>
            ))}
          </select>
        </div>
        <input className="input" style={{ width: 320 }} type="search" placeholder="Buscar por nome, código ou CPF/CNPJ" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Buscar cadastros" />
      </div>

      {q.isError ? (
        <ErrorBox error={q.error} retry={() => q.refetch()} />
      ) : !q.data ? (
        <LoadingRows />
      ) : q.data.items.length === 0 ? (
        <Empty title={params.get("q") || status || modality || kind ? "Nenhum cadastro com esses filtros" : "Ainda não há cadastros"}>
          {params.get("q") || status || modality || kind ? "Limpe a busca ou escolha outra situação ou modalidade." : "Crie o primeiro em Novo cadastro, ou deixe arquivos na pasta monitorada."}
        </Empty>
      ) : (
        <>
          <table className="table" style={{ opacity: q.isPlaceholderData ? 0.6 : 1 }}>
            <thead>
              <tr>
                <th><button onClick={() => sortBy("code")} aria-sort={sortAttr("code")}>Código</button></th>
                <th><button onClick={() => sortBy("name")} aria-sort={sortAttr("name")}>Cliente</button></th>
                <th>Situação</th>
                <th>Pendências</th>
                <th><button onClick={() => sortBy("priority")} aria-sort={sortAttr("priority")}>Prioridade</button></th>
                <th><button onClick={() => sortBy("updated")} aria-sort={sortAttr("updated")}>Atualizado</button></th>
              </tr>
            </thead>
            <tbody>
              {q.data.items.map((r) => (
                <tr key={r.id} className="clickable" onClick={() => nav(`/cadastros/${r.id}`)}>
                  <td className="num">
                    <a href={`#/cadastros/${r.id}`} onClick={(e) => e.stopPropagation()}>{r.code}</a>
                  </td>
                  <td>
                    <div className="strong">{r.subject_name}</div>
                    <div className="meta num"><ModalityTag modality={r.modality} /> {meta?.profiles[r.kind]?.label ?? r.kind} · {fmtTaxId(r.tax_id)}{r.client?.commercial ? ` · ${r.client.commercial}` : ""}</div>
                  </td>
                  <td><StatusMark status={r.status} /></td>
                  <td>
                    {r.missing.length > 0 && <div className="danger-text">Falta: {r.missing.join(", ")}</div>}
                    {r.open_findings > 0 ? (
                      <div className={r.blocking_findings ? "warn-text" : "muted"}>
                        {r.open_findings} {r.open_findings === 1 ? "ponto a conferir" : "pontos a conferir"}
                      </div>
                    ) : r.missing.length === 0 && r.status !== "approved" && r.status !== "rejected" ? (
                      <span className="muted">{r.ready_for_decision ? "Pronto para decisão" : "—"}</span>
                    ) : null}
                  </td>
                  <td className="num">
                    <span className="strong">{r.priority_score}</span>
                    {r.priority_reasons[0] && <div className="meta">{r.priority_reasons[0].label}</div>}
                  </td>
                  <td className="meta num">{relative(r.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager page={page} pageSize={25} total={q.data.total} onPage={(p) => update({ pagina: String(p) })} />
        </>
      )}
    </div>
  );
}

