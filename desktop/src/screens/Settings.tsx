import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api } from "../api/client";
import type { User } from "../api/types";
import { useAuth, usePerm } from "../auth";
import { Dialog, ErrorBox, LoadingRows, Mark, Switch, errorText, useToast } from "../components/ui";
import { ROLES, relative } from "../lib/format";
import "./settings.css";

interface SettingsData {
  settings: Record<string, any>;
  versions: Record<string, { version: number; updated_at: string }>;
  system: {
    ocr_provider: string; ocr_configured: boolean; ai_provider: string; ai_configured: boolean; ai_model: string;
    ai_images_allowed_by_server: boolean; storage_healthy: boolean; watch_roots: string[]; max_upload_mb: number; pipeline_version: string;
  };
}

const TABS = [
  { key: "processing", label: "Processamento" },
  { key: "watcher", label: "Pasta monitorada" },
  { key: "documents", label: "Documentos e validade" },
  { key: "requirements", label: "Exigências" },
  { key: "priority", label: "Prioridade" },
  { key: "retention", label: "Retenção" },
  { key: "users", label: "Usuários", admin: true },
  { key: "system", label: "Sistema" },
];

function useSave() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: ({ key, value }: { key: string; value: unknown }) => api(`/api/settings/${key}`, { method: "PUT", json: value }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["meta"] });
      toast("Configuração salva e registrada no histórico.");
    },
    onError: (e) => toast(errorText(e), "danger"),
  });
}

export function Settings() {
  const perm = usePerm();
  const [tab, setTab] = useState("processing");
  const q = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsData>("/api/settings") });
  return (
    <div className="page settings">
      <div className="page-head">
        <div>
          <h1>Configurações</h1>
          <p className="muted">{perm.admin ? "Regras operacionais. Senhas e chaves ficam só no servidor e não aparecem aqui." : "Somente administradores alteram estas regras. Você pode consultá-las."}</p>
        </div>
      </div>
      <div className="segmented settings-tabs" role="tablist">
        {TABS.filter((t) => !t.admin || perm.admin).map((t) => (
          <button key={t.key} role="tab" aria-pressed={tab === t.key} aria-selected={tab === t.key} onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </div>
      {q.isError ? <ErrorBox error={q.error} retry={() => q.refetch()} /> : !q.data ? <LoadingRows /> : (
        <div className="settings-body">
          {tab === "processing" && <Processing data={q.data} readOnly={!perm.admin} />}
          {tab === "watcher" && <WatcherForm data={q.data} readOnly={!perm.admin} />}
          {tab === "documents" && <DocTypes data={q.data} readOnly={!perm.admin} />}
          {tab === "requirements" && <Requirements data={q.data} readOnly={!perm.admin} />}
          {tab === "priority" && <Priority data={q.data} readOnly={!perm.admin} />}
          {tab === "retention" && <Retention data={q.data} readOnly={!perm.admin} />}
          {tab === "users" && perm.admin && <Users />}
          {tab === "system" && <System data={q.data} />}
        </div>
      )}
    </div>
  );
}

/* ---------- processing: sentences with switches ---------- */
function Processing({ data, readOnly }: { data: SettingsData; readOnly: boolean }) {
  const save = useSave();
  const p = data.settings.processing;
  const w = data.settings.watcher;
  const sys = data.system;
  const setP = (patch: object) => save.mutate({ key: "processing", value: { ...p, ...patch } });
  const bands: { id: string; sentence: string; on: boolean; set: (v: boolean) => void; consequence: string; off: string; disabled?: string }[] = [
    {
      id: "ai", sentence: "Analisar cada documento também com IA", on: p.ai_enabled, set: (v) => setP({ ai_enabled: v }),
      consequence: `O texto lido segue para ${sys.ai_model}; cerca de US$ 0,03 a 0,08 por documento. A IA só aponta; quem decide é a equipe.`,
      off: "Só OCR e regras. Nenhum conteúdo sai do servidor.",
      disabled: sys.ai_configured ? undefined : "Nenhum provedor de IA configurado no servidor (AI_PROVIDER e ANTHROPIC_API_KEY).",
    },
    {
      id: "images", sentence: "Mandar também as imagens das páginas", on: p.ai_send_images, set: (v) => setP({ ai_send_images: v }),
      consequence: "Até 3 páginas por documento; permite apontar sinais visuais, com custo e exposição maiores.",
      off: "A IA recebe apenas o texto lido.",
      disabled: !sys.ai_images_allowed_by_server ? "O servidor não permite envio de imagens (AI_ALLOW_IMAGES=false)." : !p.ai_enabled ? "Ligue a análise por IA primeiro." : undefined,
    },
    {
      id: "layer", sentence: "Conferir o texto embutido do PDF com a página", on: p.compare_text_layer, set: (v) => setP({ compare_text_layer: v }),
      consequence: "Aponta números e datas que existem no arquivo mas não aparecem impressos.",
      off: "PDFs digitais são lidos sem essa conferência.",
    },
    {
      id: "assign", sentence: "Associar arquivos da pasta pelo CPF ou CNPJ lido", on: p.auto_assign_by_extracted_id, set: (v) => setP({ auto_assign_by_extracted_id: v }),
      consequence: "Quando o número lido bate com um único cadastro aberto, o arquivo entra nele sozinho.",
      off: "O sistema só sugere; alguém confirma na caixa de entrada.",
    },
    {
      id: "watch", sentence: "Monitorar a pasta compartilhada", on: w.enabled, set: (v) => save.mutate({ key: "watcher", value: { ...w, enabled: v } }),
      consequence: `Lendo ${w.folder} a cada ${w.scan_interval_seconds} s; um arquivo entra quando fica ${w.stable_seconds} s sem mudar.`,
      off: "Arquivos deixados na pasta não são recebidos.",
    },
  ];
  return (
    <div className="sentences" data-ui-section>
      {bands.map((b, i) => (
        <div key={b.id} className="sentence-band" data-on={b.on} data-field={bands.slice(0, i).filter((x) => x.on).length % 2 ? "accent" : "paper"}>
          <div>
            <p className="sentence">{b.sentence}</p>
            <p className="consequence">{b.disabled ?? (b.on ? b.consequence : b.off)}</p>
          </div>
          <Switch checked={b.on} onChange={b.set} label={b.sentence} disabled={readOnly || !!b.disabled || save.isPending} />
        </div>
      ))}
      <p className="meta" style={{ marginTop: 14 }}>Valores de custo são estimativas de lista; o custo real de cada documento aparece em Sistema &gt; Métricas.</p>
    </div>
  );
}

/* ---------- watcher ---------- */
function WatcherForm({ data, readOnly }: { data: SettingsData; readOnly: boolean }) {
  const save = useSave();
  const [w, setW] = useState(data.settings.watcher);
  useEffect(() => setW(data.settings.watcher), [data]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate({ key: "watcher", value: w });
  };
  return (
    <form className="settings-form" onSubmit={submit}>
      <Explain>
        A pasta é lida pelo serviço de monitoramento no servidor, não por este computador. O caminho precisa estar dentro de {data.system.watch_roots.join(", ")}, que é onde o compartilhamento está montado.
      </Explain>
      <label className="label"><span>Caminho da pasta no servidor</span><input className="input" value={w.folder} disabled={readOnly} onChange={(e) => setW({ ...w, folder: e.target.value })} /></label>
      <div className="grid-3">
        <label className="label"><span>Ler a cada (segundos)</span><input className="input num" type="number" min={2} value={w.scan_interval_seconds} disabled={readOnly} onChange={(e) => setW({ ...w, scan_interval_seconds: +e.target.value })} /></label>
        <label className="label"><span>Arquivo estável por (segundos)</span><input className="input num" type="number" min={2} value={w.stable_seconds} disabled={readOnly} onChange={(e) => setW({ ...w, stable_seconds: +e.target.value })} /></label>
        <label className="label"><span>Depois de receber</span>
          <select className="select" value={w.after_ingest} disabled={readOnly} onChange={(e) => setW({ ...w, after_ingest: e.target.value })}>
            <option value="move">Mover para _processados</option>
            <option value="leave">Deixar no lugar</option>
          </select>
        </label>
      </div>
      <label className="label"><span>Código do cadastro no nome do arquivo ou da subpasta (expressão regular)</span><input className="input num" value={w.association.registration_code_pattern ?? ""} disabled={readOnly} onChange={(e) => setW({ ...w, association: { ...w.association, registration_code_pattern: e.target.value } })} /></label>
      <label className="row"><input type="checkbox" checked={w.association.use_parent_folder} disabled={readOnly} onChange={(e) => setW({ ...w, association: { ...w.association, use_parent_folder: e.target.checked } })} /> Usar o nome da subpasta como código do cadastro</label>
      <label className="row"><input type="checkbox" checked={w.association.match_tax_id_in_filename} disabled={readOnly} onChange={(e) => setW({ ...w, association: { ...w.association, match_tax_id_in_filename: e.target.checked } })} /> Associar pelo CPF/CNPJ escrito no nome do arquivo</label>
      <label className="label"><span>Ignorar arquivos com estes padrões</span><input className="input" value={w.ignore_patterns.join(", ")} disabled={readOnly} onChange={(e) => setW({ ...w, ignore_patterns: e.target.value.split(",").map((x: string) => x.trim()).filter(Boolean) })} /></label>
      {!readOnly && <SaveBar pending={save.isPending} />}
    </form>
  );
}

/* ---------- document types and validity ---------- */
function DocTypes({ data, readOnly }: { data: SettingsData; readOnly: boolean }) {
  const save = useSave();
  const [types, setTypes] = useState<Record<string, any>>(data.settings.document_types);
  useEffect(() => setTypes(data.settings.document_types), [data]);
  const setRule = (k: string, patch: object) => setTypes({ ...types, [k]: { ...types[k], validity: { ...types[k].validity, ...patch } } });
  return (
    <form className="settings-form wide" onSubmit={(e) => { e.preventDefault(); save.mutate({ key: "document_types", value: types }); }}>
      <Explain>Regras de validade por tipo. "Validade impressa" verifica a data de vencimento; "idade máxima" conta a partir da emissão. Estar dentro da regra não comprova autenticidade.</Explain>
      <div className="table-scroll"><table className="table">
        <thead><tr><th>Tipo</th><th>Validade impressa</th><th>Tolerância (dias)</th><th>Idade máxima (dias)</th><th>Observação</th></tr></thead>
        <tbody>
          {Object.entries(types).map(([k, t]) => (
            <tr key={k}>
              <td><div className="strong">{t.label}</div><div className="meta">{t.keywords.slice(0, 3).join(", ")}…</div></td>
              <td><input type="checkbox" checked={!!t.validity.has_expiry} disabled={readOnly} onChange={(e) => setRule(k, { has_expiry: e.target.checked, expiry_field: "validade" })} aria-label={`${t.label} tem validade impressa`} /></td>
              <td><input className="input num" style={{ width: 90 }} type="number" min={0} value={t.validity.grace_days ?? 0} disabled={readOnly || !t.validity.has_expiry} onChange={(e) => setRule(k, { grace_days: +e.target.value })} /></td>
              <td><input className="input num" style={{ width: 110 }} type="number" min={1} value={t.validity.max_age_days ?? ""} placeholder="sem limite" disabled={readOnly || t.validity.has_expiry} onChange={(e) => setRule(k, { max_age_days: e.target.value ? +e.target.value : null, max_age_from: t.validity.max_age_from ?? "data_emissao" })} /></td>
              <td><input className="input" value={t.validity.note ?? ""} disabled={readOnly} onChange={(e) => setRule(k, { note: e.target.value })} /></td>
            </tr>
          ))}
        </tbody>
      </table></div>
      {!readOnly && <SaveBar pending={save.isPending} />}
    </form>
  );
}

/* ---------- requirements ---------- */
function Requirements({ data, readOnly }: { data: SettingsData; readOnly: boolean }) {
  const save = useSave();
  const [profiles, setProfiles] = useState<Record<string, any>>(data.settings.requirement_profiles);
  const [approval, setApproval] = useState(data.settings.approval);
  useEffect(() => { setProfiles(data.settings.requirement_profiles); setApproval(data.settings.approval); }, [data]);
  const types = data.settings.document_types;
  const toggle = (pk: string, ri: number, t: string, on: boolean) => {
    const p = structuredClone(profiles);
    const req = p[pk].required[ri];
    req.any_of = on ? [...req.any_of, t] : req.any_of.filter((x: string) => x !== t);
    setProfiles(p);
  };
  return (
    <div className="stack" style={{ gap: 36 }}>
      <form className="settings-form wide" onSubmit={(e) => { e.preventDefault(); save.mutate({ key: "requirement_profiles", value: profiles }); }}>
        <Explain>Documentos obrigatórios por tipo de cadastro e quais tipos atendem cada exigência.</Explain>
        {Object.entries(profiles).map(([pk, prof]) => (
          <section key={pk} className="req-profile">
            <h2>{prof.label}</h2>
            {prof.required.map((req: any, ri: number) => (
              <div key={req.id} className="req-row">
                <span className="strong">{req.label}</span>
                <span className="req-types">
                  {Object.entries(types).map(([tk, tv]: [string, any]) => (
                    <label key={tk} className="row meta">
                      <input type="checkbox" checked={req.any_of.includes(tk)} disabled={readOnly} onChange={(e) => toggle(pk, ri, tk, e.target.checked)} />
                      {tv.label}
                    </label>
                  ))}
                </span>
              </div>
            ))}
          </section>
        ))}
        {!readOnly && <SaveBar pending={save.isPending} />}
      </form>
      <form className="settings-form wide" onSubmit={(e) => { e.preventDefault(); save.mutate({ key: "approval", value: approval }); }}>
        <h2>Quem decide</h2>
        {(["approve_roles", "reject_roles", "override_roles"] as const).map((k) => (
          <div key={k} className="req-row">
            <span className="strong">{k === "approve_roles" ? "Aprovar" : k === "reject_roles" ? "Reprovar" : "Sobrepor regras e aprovar com pendências"}</span>
            <span className="req-types">
              {["analyst", "supervisor", "admin"].map((r) => (
                <label key={r} className="row meta">
                  <input type="checkbox" checked={approval[k].includes(r)} disabled={readOnly} onChange={(e) => setApproval({ ...approval, [k]: e.target.checked ? [...approval[k], r] : approval[k].filter((x: string) => x !== r) })} />
                  {ROLES[r]}
                </label>
              ))}
            </span>
          </div>
        ))}
        <label className="row"><input type="checkbox" checked={approval.allow_approve_with_open_findings} disabled={readOnly} onChange={(e) => setApproval({ ...approval, allow_approve_with_open_findings: e.target.checked })} /> Permitir aprovar com pontos de severidade baixa ou média em aberto</label>
        {!readOnly && <SaveBar pending={save.isPending} />}
      </form>
    </div>
  );
}

/* ---------- priority ---------- */
function Priority({ data, readOnly }: { data: SettingsData; readOnly: boolean }) {
  const save = useSave();
  const [rules, setRules] = useState<any[]>(data.settings.priority_rules);
  useEffect(() => setRules(data.settings.priority_rules), [data]);
  return (
    <form className="settings-form" onSubmit={(e) => { e.preventDefault(); save.mutate({ key: "priority_rules", value: rules }); }}>
      <Explain>A posição na fila é a soma dos pontos das regras que se aplicam a cada cadastro. Nenhuma pontuação vem de IA.</Explain>
      <div className="stack" style={{ gap: 4 }}>
        {rules.map((r, i) => (
          <div key={r.id} className="priority-row">
            <span>{r.label}</span>
            {r.days !== undefined && (
              <label className="row meta">dias <input className="input num" style={{ width: 70 }} type="number" min={1} value={r.days} disabled={readOnly} onChange={(e) => setRules(rules.map((x, j) => (j === i ? { ...x, days: +e.target.value } : x)))} /></label>
            )}
            <input className="input num" style={{ width: 90 }} type="number" min={0} value={r.points} disabled={readOnly} aria-label={`Pontos para ${r.label}`} onChange={(e) => setRules(rules.map((x, j) => (j === i ? { ...x, points: +e.target.value } : x)))} />
          </div>
        ))}
      </div>
      {!readOnly && <SaveBar pending={save.isPending} />}
    </form>
  );
}

/* ---------- retention ---------- */
function Retention({ data, readOnly }: { data: SettingsData; readOnly: boolean }) {
  const save = useSave();
  const [r, setR] = useState(data.settings.retention);
  useEffect(() => setR(data.settings.retention), [data]);
  return (
    <form className="settings-form" onSubmit={(e) => { e.preventDefault(); save.mutate({ key: "retention", value: r }); }}>
      <Explain>Prazos de guarda. Ao vencer, os arquivos e dados pessoais são expurgados; a trilha de auditoria e os hashes permanecem. Cadastros sob retenção legal nunca são expurgados.</Explain>
      <div className="grid-3">
        <label className="label"><span>Reprovados: apagar após (dias; 0 = na hora da reprovação)</span><input className="input num" type="number" min={0} value={r.rejected_days ?? ""} disabled={readOnly} onChange={(e) => setR({ ...r, rejected_days: e.target.value ? +e.target.value : null })} /></label>
        <label className="label"><span>Pendentes sem resposta: expurgar após (dias)</span><input className="input num" type="number" min={30} value={r.abandoned_pending_days ?? ""} disabled={readOnly} onChange={(e) => setR({ ...r, abandoned_pending_days: e.target.value ? +e.target.value : null })} /></label>
      </div>
      <p className="muted">{r.approved_note}</p>
      {!readOnly && <SaveBar pending={save.isPending} />}
    </form>
  );
}

/* ---------- users ---------- */
function Users() {
  const qc = useQueryClient();
  const toast = useToast();
  const { meta } = useAuth();
  const q = useQuery({ queryKey: ["users"], queryFn: () => api<{ items: User[] }>("/api/users") });
  const [form, setForm] = useState({ name: "", email: "", role: "analyst", password: "" });
  const [editing, setEditing] = useState<User | null>(null);
  const [removing, setRemoving] = useState<User | null>(null);
  const remove = useMutation({
    mutationFn: (u: User) => api<{ mode: string; history_records: number }>(`/api/users/${u.id}`, { method: "DELETE" }),
    onSuccess: (res, u) => {
      qc.invalidateQueries({ queryKey: ["users"] });
      setRemoving(null);
      toast(res.mode === "removed" ? `Conta de ${u.name} excluída.` : `Conta de ${u.name} excluída. O nome continua no histórico do que foi feito com ela; o e-mail está livre para uma conta nova.`);
    },
    onError: (e) => toast(errorText(e), "danger"),
  });
  const create = useMutation({
    mutationFn: () => api("/api/users", { method: "POST", json: form }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); setForm({ name: "", email: "", role: "analyst", password: "" }); toast("Usuário criado. Entregue a senha inicial por um canal seguro."); },
    onError: (e) => toast(errorText(e), "danger"),
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: object }) => api(`/api/users/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); toast("Usuário atualizado. As sessões abertas dele foram encerradas."); },
    onError: (e) => toast(errorText(e), "danger"),
  });
  return (
    <div className="stack" style={{ gap: 32 }}>
      {q.isError ? <ErrorBox error={q.error} /> : !q.data ? <LoadingRows rows={4} /> : (
        <div className="table-scroll"><table className="table">
          <thead><tr><th>Nome</th><th>Perfil</th><th>Último acesso</th><th>Situação</th><th /></tr></thead>
          <tbody>
            {q.data.items.map((u) => (
              <tr key={u.id}>
                <td><div className="strong">{u.name}</div><div className="meta">{u.email}</div></td>
                <td>
                  <select className="select" style={{ width: 160 }} value={u.role} disabled={u.id === meta?.user.id} onChange={(e) => update.mutate({ id: u.id, body: { role: e.target.value } })} aria-label={`Perfil de ${u.name}`}>
                    {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </td>
                <td className="meta num">{relative(u.last_login_at)}</td>
                <td>{u.is_active ? <Mark tone="accent">Ativo</Mark> : <Mark tone="muted">Desativado</Mark>}</td>
                <td style={{ textAlign: "right" }}>
                  <button className="btn btn-sm btn-ghost" onClick={() => setEditing(u)}>Editar</button>{" "}
                  {u.id !== meta?.user.id && <button className="btn btn-sm btn-ghost" onClick={() => setRemoving(u)}>Excluir</button>}{" "}
                  {u.id !== meta?.user.id && (
                    <button className={u.is_active ? "btn btn-sm btn-danger" : "btn btn-sm"} onClick={() => update.mutate({ id: u.id, body: { is_active: !u.is_active } })}>
                      {u.is_active ? "Revogar acesso" : "Reativar"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
      <form className="settings-form" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
        <h2>Novo usuário</h2>
        <div className="grid-2">
          <label className="label"><span>Nome</span><input className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          <label className="label"><span>E-mail corporativo</span><input className="input" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
          <label className="label"><span>Perfil</span>
            <select className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="label"><span>Senha inicial (12+ caracteres, maiúsculas, minúsculas e número)</span><input className="input" type="password" required minLength={12} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" /></label>
        </div>
        <div><button className="btn btn-primary" disabled={create.isPending}>Criar usuário</button></div>
      </form>
      {removing && (
        <Dialog title={`Excluir ${removing.name}?`} onClose={() => setRemoving(null)}>
          <p className="muted">
            A conta deixa de existir e o acesso termina na hora. Se essa pessoa já registrou cadastros, documentos ou decisões, o nome dela continua aparecendo nesse histórico,
            como exige a auditoria. Para só suspender o acesso por um tempo, use "Revogar acesso".
          </p>
          <div className="dialog-actions">
            <button className="btn btn-ghost" onClick={() => setRemoving(null)}>Cancelar</button>
            <button className="btn btn-danger" disabled={remove.isPending} onClick={() => remove.mutate(removing)}>{remove.isPending ? "Excluindo…" : "Excluir"}</button>
          </div>
        </Dialog>
      )}
      {editing && <EditUser u={editing} self={editing.id === meta?.user.id} onClose={() => setEditing(null)} />}
    </div>
  );
}

function EditUser({ u, self, onClose }: { u: User; self: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(u.name);
  const [password, setPassword] = useState("");
  const save = useMutation({
    mutationFn: () => api(`/api/users/${u.id}`, { method: "PATCH", json: { ...(name.trim() !== u.name ? { name: name.trim() } : {}), ...(password ? { password } : {}) } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast(password ? (self ? "Senha trocada. Suas outras sessões foram encerradas." : `Senha de ${name.trim()} trocada. Entregue a nova senha por um canal seguro.`) : "Nome atualizado.");
      onClose();
    },
  });
  const changed = name.trim() !== u.name || password.length > 0;
  return (
    <Dialog title={self ? "Editar minha conta" : `Editar ${u.name}`} onClose={onClose}>
      <p className="muted" style={{ marginBottom: 16 }}>{u.email}</p>
      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <label className="label"><span>Nome</span><input className="input" required minLength={2} value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label className="label">
          <span>Nova senha (deixe em branco para manter a atual; 12+ caracteres, maiúsculas, minúsculas e número)</span>
          <input className="input" type="password" minLength={12} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
        </label>
        {password && !self && <p className="meta">As sessões abertas dessa pessoa são encerradas; ela entra de novo com a senha nova.</p>}
        {save.isError && <p className="form-error">{errorText(save.error)}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" disabled={!changed || save.isPending || name.trim().length < 2}>{save.isPending ? "Salvando…" : "Salvar"}</button>
        </div>
      </form>
    </Dialog>
  );
}

/* ---------- system ---------- */
function System({ data }: { data: SettingsData }) {
  const s = data.system;
  const perm = usePerm();
  const m = useQuery({ queryKey: ["metrics"], queryFn: () => api<any>("/api/metrics?days=30"), enabled: perm.approve || perm.admin });
  const rows: [string, ReactNode][] = [
    ["OCR", <>{s.ocr_provider === "tesseract" ? "Tesseract no servidor próprio (português)" : "Azure AI Document Intelligence"} {s.ocr_configured ? <Mark tone="accent">configurado</Mark> : <Mark tone="danger">sem credencial</Mark>}</>],
    ["IA", s.ai_configured ? <>{s.ai_model} <Mark tone="accent">configurada</Mark></> : <Mark tone="muted">Não configurada no servidor</Mark>],
    ["Imagens para a IA", s.ai_images_allowed_by_server ? "Permitidas pelo servidor" : "Bloqueadas pelo servidor"],
    ["Repositório de documentos", s.storage_healthy ? <Mark tone="accent">Acessível, criptografado</Mark> : <Mark tone="danger">Inacessível</Mark>],
    ["Raízes da pasta monitorada", s.watch_roots.join(", ")],
    ["Tamanho máximo por arquivo", `${s.max_upload_mb} MB`],
    ["Versão do pipeline", s.pipeline_version],
  ];
  return (
    <div className="stack" style={{ gap: 32 }}>
      <dl className="facts">{rows.map(([k, v]) => <div key={k}><dt className="muted">{k}</dt><dd>{v}</dd></div>)}</dl>
      {m.data && (
        <section>
          <h2 style={{ marginBottom: 10 }}>Últimos 30 dias</h2>
          <dl className="facts">
            <div><dt className="muted">Documentos analisados</dt><dd className="num">{m.data.documents_processed} ({m.data.pages_processed} páginas)</dd></div>
            <div><dt className="muted">Tempo de análise</dt><dd className="num">{m.data.processing_seconds.avg ?? "—"} s em média · p95 {m.data.processing_seconds.p95 ?? "—"} s</dd></div>
            <div><dt className="muted">Custo de IA</dt><dd className="num">US$ {m.data.ai_cost_usd} · {m.data.ai_cost_per_document_usd !== null ? `US$ ${m.data.ai_cost_per_document_usd} por documento` : "sem uso"}</dd></div>
            <div><dt className="muted">Decididos sem precisar resolver pontos</dt><dd className="num">{m.data.decided_without_manual_findings} de {m.data.registrations_decided}</dd></div>
            <div><dt className="muted">Campos corrigidos na revisão</dt><dd className="num">{m.data.fields_reviewed.corrected} de {m.data.fields_reviewed.corrected + m.data.fields_reviewed.confirmed} revisados</dd></div>
          </dl>
          <p className="meta" style={{ marginTop: 10 }}>{m.data.note}</p>
          <h2 style={{ margin: "28px 0 6px" }}>Aprendido com as revisões</h2>
          <Explain>Calculado a partir das confirmações e correções feitas pelas analistas, neste servidor. O modelo de IA não é treinado com os documentos; o que muda é como o sistema usa as leituras.</Explain>
          {m.data.learning.length === 0 ? <p className="muted">Ainda não há correções repetidas o bastante para mudar a leitura.</p> : (
            <div className="table-scroll"><table className="table">
              <thead><tr><th>Documento</th><th>Campo</th><th>O que mudou</th></tr></thead>
              <tbody>
                {m.data.learning.map((x: any) => (
                  <tr key={`${x.doc_type}.${x.field}`}>
                    <td>{x.doc_type_label}</td>
                    <td>{x.field_label}</td>
                    <td>{[
                      x.rejected_values ? `${x.rejected_values} ${x.rejected_values === 1 ? "leitura descartada não é mais oferecida" : "leituras descartadas não são mais oferecidas"}` : null,
                      x.prefer_ai ? `usa a leitura da IA (a IA acertou ${x.ai_wins}×, as regras ${x.rule_wins}×)` : null,
                    ].filter(Boolean).join(" · ")}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
        </section>
      )}
    </div>
  );
}

function Explain({ children }: { children: ReactNode }) {
  return <p className="muted settings-explain">{children}</p>;
}

function SaveBar({ pending }: { pending: boolean }) {
  return <div><button className="btn btn-primary" disabled={pending}>{pending ? "Salvando…" : "Salvar alterações"}</button></div>;
}
