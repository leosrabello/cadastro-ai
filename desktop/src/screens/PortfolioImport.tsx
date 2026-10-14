import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api, apiForm } from "../api/client";
import type { ImportAction, ImportPlan } from "../api/types";
import { ModalityTag } from "../components/ModalitySwitch";
import { ErrorBox, Mark, useToast } from "../components/ui";
import { fmtDate, fmtDateTime, plural } from "../lib/format";

const ACTION: Record<ImportAction, { label: string; tone: string }> = {
  create: { label: "Novo", tone: "accent" },
  update: { label: "Atualiza", tone: "ink" },
  unchanged: { label: "Sem mudança", tone: "muted" },
  skipped: { label: "Mantido no sistema", tone: "warn" },
  rejected: { label: "Rejeitado", tone: "danger" },
};

function postFile(path: string, file: File, extra?: Record<string, string>): Promise<ImportPlan> {
  const form = new FormData();
  form.append("file", file, file.name);
  for (const [k, v] of Object.entries(extra ?? {})) form.append(k, v);
  return apiForm<ImportPlan>(path, form);
}

interface ImportRecord {
  id: string;
  filename: string;
  imported_at: string;
  imported_by: string | null;
  summary: ImportPlan;
}

export function ImportArea() {
  const qc = useQueryClient();
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [plan, setPlan] = useState<ImportPlan | null>(null);
  const [result, setResult] = useState<ImportPlan | null>(null);
  const [onlyProblems, setOnlyProblems] = useState(true);
  const history = useQuery({ queryKey: ["portfolio-imports"], queryFn: () => api<{ items: ImportRecord[] }>("/api/portfolio/imports") });

  const preview = useMutation({
    mutationFn: (f: File) => postFile("/api/portfolio/import/preview", f),
    onSuccess: (p) => { setPlan(p); setResult(null); },
  });
  const apply = useMutation({
    mutationFn: () => postFile("/api/portfolio/import", file!, { sha256: plan!.file.sha256 }),
    onSuccess: (r) => {
      setResult(r);
      setPlan(null);
      for (const k of ["portfolio-imports", "portfolio-clients", "portfolio-summary", "portfolio-catalog", "portfolio-commercials", "signatures", "portfolio-clients-names"]) qc.invalidateQueries({ queryKey: [k] });
      toast("Importação concluída.");
    },
  });

  const choose = (f: File | null) => {
    setFile(f);
    setPlan(null);
    setResult(null);
    if (f) preview.mutate(f);
  };
  const work = plan ? plan.clients.create + plan.clients.update + plan.signatures.create + plan.signatures.update : 0;

  return (
    <div className="import-area">
      <section className="import-intro">
        <h2>Backup do painel de cadastros</h2>
        <p className="muted">
          Escolha o arquivo <span className="num">backup_cadastros_AAAA-MM-DD.json</span> exportado pelo painel antigo. O CadastroAI confere cada registro e mostra o
          que vai acontecer antes de gravar. Importar o mesmo arquivo de novo não duplica nada: cada cliente é reconhecido pelo código que tinha no painel. Clientes
          alterados aqui depois da importação não são sobrescritos por um arquivo mais antigo.
        </p>
        <div className="row" style={{ marginTop: 14 }}>
          <input ref={input} type="file" accept=".json,application/json" hidden onChange={(e) => choose(e.target.files?.[0] ?? null)} />
          <button className="btn btn-primary" onClick={() => { if (input.current) { input.current.value = ""; input.current.click(); } }} disabled={preview.isPending || apply.isPending}>
            {preview.isPending ? "Conferindo o arquivo…" : file ? "Escolher outro arquivo" : "Escolher arquivo JSON"}
          </button>
          {file && <span className="meta">{file.name}</span>}
        </div>
        {preview.isError && <div style={{ marginTop: 14 }}><ErrorBox error={preview.error} /></div>}
      </section>

      {plan && (
        <section className="import-plan" aria-labelledby="plan-h">
          <h2 id="plan-h">Prévia da importação</h2>
          <p className="meta">
            {plan.file.exported_at ? `Exportado em ${fmtDateTime(plan.file.exported_at)}. ` : ""}
            {plan.file.previously_imported_at ? `Este mesmo arquivo já foi importado em ${fmtDateTime(plan.file.previously_imported_at)}.` : ""}
          </p>
          <Counts title="Clientes" c={plan.clients} />
          <Counts title="Contratos em assinatura" c={plan.signatures} />
          <div className="plan-notes">
            <p><span className="strong">{plural(plan.commercials.create, "comercial novo", "comerciais novos")}</span>{plan.commercials.names.length ? `: ${plan.commercials.names.join(", ")}.` : "."}</p>
            {plan.statuses.added.length > 0 && <p><span className="strong">Status do painel antigo que passam a existir aqui:</span> {plan.statuses.added.map((s) => s.label).join(", ")}.</p>}
            {plan.statuses.relabeled.length > 0 && <p><span className="strong">Status renomeados:</span> {plan.statuses.relabeled.map((s) => `${s.from} para ${s.to}`).join("; ")}.</p>}
          </div>
          {plan.issues.length > 0 && <Issues plan={plan} />}
          {plan.preview && (
            <details className="plan-rows">
              <summary>Ver os registros um a um</summary>
              <label className="check" style={{ margin: "10px 0" }}><input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} /> Só novos, alterados, mantidos e rejeitados</label>
              <table className="table compact">
                <thead><tr><th>Resultado</th><th>Cliente</th><th>Modalidade</th><th>Comercial</th><th>Status</th><th>Entrada</th><th>Motivo</th></tr></thead>
                <tbody>
                  {plan.preview.clients.filter((r) => !onlyProblems || r.action !== "unchanged").map((r, i) => (
                    <tr key={`${r.external_id}-${i}`}>
                      <td><Mark tone={ACTION[r.action].tone}>{ACTION[r.action].label}</Mark></td>
                      <td>{r.name || <span className="muted">sem nome</span>}</td>
                      <td>{r.modality ? <ModalityTag modality={r.modality} /> : "—"}</td>
                      <td>{r.commercial || <span className="muted">—</span>}</td>
                      <td>{r.status_label ?? "—"}</td>
                      <td className="num">{r.entry_date ? fmtDate(r.entry_date) : "—"}</td>
                      <td className="meta">{r.reason ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
          {apply.isError && <div style={{ marginTop: 12 }}><ErrorBox error={apply.error} /></div>}
          <div className="row" style={{ marginTop: 20 }}>
            <button className="btn btn-primary" disabled={!work || apply.isPending} onClick={() => apply.mutate()}>
              {apply.isPending ? "Importando…" : work ? `Importar ${plural(work, "registro", "registros")}` : "Nada a importar"}
            </button>
            <button className="btn btn-ghost" onClick={() => choose(null)}>Cancelar</button>
            <span className="meta">Tudo é gravado de uma vez: se algo falhar, nada fica pela metade.</span>
          </div>
        </section>
      )}

      {result && (
        <section className="import-result" role="status">
          <h2>Importação concluída</h2>
          <p>
            Clientes: {result.clients.create} novos, {result.clients.update} atualizados, {result.clients.unchanged} sem mudança, {result.clients.skipped} mantidos como estão
            no sistema, {result.clients.rejected} rejeitados. Contratos: {result.signatures.create} novos, {result.signatures.update} atualizados,{" "}
            {result.signatures.unchanged} sem mudança, {result.signatures.rejected} rejeitados. {plural(result.commercials.create, "comercial novo", "comerciais novos")}.
          </p>
          {result.issues.some((i) => i.level === "error") && <p className="warn-text">Os registros rejeitados não foram gravados. Corrija-os no painel de origem ou cadastre-os aqui.</p>}
        </section>
      )}

      <section className="import-history">
        <h2 style={{ marginBottom: 8 }}>Importações anteriores</h2>
        {history.isError ? <ErrorBox error={history.error} /> : !history.data ? null : history.data.items.length === 0 ? <p className="muted">Nenhuma importação ainda.</p> : (
          <table className="table compact">
            <thead><tr><th>Quando</th><th>Arquivo</th><th>Por</th><th className="num">Clientes novos</th><th className="num">Atualizados</th><th className="num">Rejeitados</th><th className="num">Contratos novos</th></tr></thead>
            <tbody>
              {history.data.items.map((h) => (
                <tr key={h.id}>
                  <td className="num">{fmtDateTime(h.imported_at)}</td>
                  <td>{h.filename}</td>
                  <td>{h.imported_by ?? "—"}</td>
                  <td className="num">{h.summary.clients?.create ?? 0}</td>
                  <td className="num">{h.summary.clients?.update ?? 0}</td>
                  <td className="num">{h.summary.clients?.rejected ?? 0}</td>
                  <td className="num">{h.summary.signatures?.create ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function Counts({ title, c }: { title: string; c: Record<ImportAction, number> }) {
  return (
    <div className="plan-counts">
      <h3>{title}</h3>
      <div className="plan-count-row">
        {(Object.keys(ACTION) as ImportAction[]).map((a) => (
          <div key={a} className="plan-count" data-tone={c[a] ? ACTION[a].tone : "none"}>
            <span className="num">{c[a]}</span>
            <span className="meta">{ACTION[a].label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Issues({ plan }: { plan: ImportPlan }) {
  const [level, setLevel] = useState<"error" | "warning" | "all">(plan.errors ? "error" : "all");
  const items = plan.issues.filter((i) => level === "all" || i.level === level);
  return (
    <div className="plan-issues">
      <div className="spread">
        <h3>Pontos a conferir</h3>
        <div className="segmented" role="group" aria-label="Filtrar pontos">
          <button aria-pressed={level === "error"} onClick={() => setLevel("error")}>Erros ({plan.errors})</button>
          <button aria-pressed={level === "warning"} onClick={() => setLevel("warning")}>Avisos ({plan.warnings})</button>
          <button aria-pressed={level === "all"} onClick={() => setLevel("all")}>Todos</button>
        </div>
      </div>
      <ul>
        {items.map((i, k) => (
          <li key={k}>
            <Mark tone={i.level === "error" ? "danger" : "warn"}>{i.level === "error" ? "Erro" : "Aviso"}</Mark>
            <span><span className="strong">{i.name || i.ref || i.entity}</span> <span className="meta">{i.entity}</span><br />{i.message}</span>
          </li>
        ))}
        {items.length === 0 && <li className="muted">Nada nesta lista.</li>}
      </ul>
    </div>
  );
}
