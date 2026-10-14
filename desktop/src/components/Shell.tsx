import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Dashboard, Modality, Page, PortfolioClient, RegistrationRow } from "../api/types";
import { useAuth, usePerm } from "../auth";
import { ROLES } from "../lib/format";
import { MODALITY_LABEL } from "../lib/modality";
import { Logo } from "./Logo";
import { Dialog, errorText } from "./ui";

export function Shell() {
  const { meta, signOut } = useAuth();
  const perm = usePerm();
  const [creating, setCreating] = useState(false);
  const dash = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/api/dashboard"), refetchInterval: 20_000 });
  const c = dash.data?.counts;

  const links: { to: string; label: string; count?: number; hot?: boolean; show?: boolean }[] = [
    { to: "/", label: "Painel" },
    { to: "/fila", label: "Fila de revisão", count: c ? c.awaiting_review + c.processing_failed : undefined, hot: true },
    { to: "/cadastros", label: "Cadastros" },
    { to: "/carteira", label: "Carteira" },
    { to: "/assinaturas", label: "Assinaturas" },
    { to: "/relatorios", label: "Relatórios" },
    { to: "/entrada", label: "Caixa de entrada", count: c?.inbox },
    { to: "/historico", label: "Histórico", show: perm.audit },
    { to: "/configuracoes", label: "Configurações", show: perm.admin || perm.approve },
  ];

  return (
    <div className="app">
      <nav className="rail" aria-label="Navegação principal">
        <div className="wordmark">
          <Logo size={20} />
        </div>
        {perm.operate && (
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            Novo cadastro
          </button>
        )}
        {links
          .filter((l) => l.show !== false)
          .map((l) => (
            <NavLink key={l.to} to={l.to} end={l.to === "/"} className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}>
              <span>{l.label}</span>
              {l.count ? <span className={"count" + (l.hot ? " hot" : "")}>{l.count}</span> : null}
            </NavLink>
          ))}
        <div className="rail-foot">
          <span>{meta?.user.name ?? "…"}</span>
          <span className="meta">{meta ? ROLES[meta.user.role] : ""}</span>
          <button className="link-btn meta" style={{ justifySelf: "start", marginTop: 8, color: "var(--muted)" }} onClick={signOut}>
            Sair
          </button>
        </div>
      </nav>
      <main className="main" id="conteudo">
        <Outlet />
      </main>
      {creating && <NewRegistration onClose={() => setCreating(false)} />}
    </div>
  );
}

function NewRegistration({ onClose }: { onClose: () => void }) {
  const { meta } = useAuth();
  const nav = useNavigate();
  const qc = useQueryClient();
  const profiles = Object.entries(meta?.profiles ?? {});
  const [kind, setKind] = useState(profiles[0]?.[0] ?? "PF");
  // no default: the analyst says which line of business this is
  const [modality, setModalityChoice] = useState<Modality | null>(null);
  const [clientId, setClientId] = useState("");
  const [name, setName] = useState("");
  const [taxId, setTaxId] = useState("");
  const [tried, setTried] = useState(false);
  const kindInfo = meta?.profiles[kind];
  const clients = useQuery({
    queryKey: ["portfolio-clients-names", modality],
    enabled: !!modality,
    queryFn: () => api<Page<PortfolioClient>>(`/api/portfolio/clients?modality=${modality}&sort=name&page_size=500`),
  });
  const create = useMutation({
    mutationFn: () => api<RegistrationRow>("/api/registrations", { method: "POST", json: { kind, modality, client_id: clientId || null, subject_name: name, tax_id: taxId || null } }),
    onSuccess: (reg) => {
      qc.invalidateQueries({ queryKey: ["registrations"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      onClose();
      nav(`/cadastros/${reg.id}`, { state: { justCreated: true } });
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    if (!modality) return;
    create.mutate();
  };
  const pickClient = (id: string) => {
    setClientId(id);
    const c = clients.data?.items.find((x) => x.id === id);
    if (c && !name.trim()) setName(c.name);
  };
  return (
    <Dialog title="Novo cadastro" onClose={onClose}>
      <p className="muted" style={{ marginBottom: 18 }}>
        Depois de criar, anexe os documentos. A análise começa assim que cada arquivo chega.
      </p>
      <form className="form-grid" onSubmit={submit}>
        <fieldset className="label field-set" aria-invalid={tried && !modality}>
          <legend>Modalidade</legend>
          <div className="segmented" role="radiogroup" aria-label="Modalidade" aria-required="true">
            {(["normal", "one7"] as Modality[]).map((m) => (
              <button type="button" role="radio" key={m} aria-checked={modality === m} aria-pressed={modality === m}
                onClick={() => { setModalityChoice(m); setClientId(""); }}>
                {MODALITY_LABEL[m]}
              </button>
            ))}
          </div>
          {tried && !modality && <span className="form-error">Escolha a modalidade do cadastro.</span>}
        </fieldset>
        {modality && (
          <label className="label">
            <span>Cliente da carteira {MODALITY_LABEL[modality]} (opcional)</span>
            <select className="select" value={clientId} onChange={(e) => pickClient(e.target.value)}>
              <option value="">Nenhum: cliente ainda fora da carteira</option>
              {clients.data?.items.map((c) => (
                <option key={c.id} value={c.id}>{c.name}{c.commercial ? `, ${c.commercial.name}` : ""}</option>
              ))}
            </select>
          </label>
        )}
        <div className="segmented" role="group" aria-label="Tipo de cadastro">
          {profiles.map(([k, p]) => (
            <button type="button" key={k} aria-pressed={kind === k} onClick={() => setKind(k)}>
              {p.label}
            </button>
          ))}
        </div>
        <label className="label">
          <span>{kindInfo?.tax_id_kind === "cnpj" ? "Razão social" : "Nome completo"}</span>
          <input className="input" required minLength={3} value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" />
        </label>
        <label className="label">
          <span>{kindInfo?.tax_id_kind === "cnpj" ? "CNPJ" : "CPF"} (opcional, conferido contra os documentos)</span>
          <input className="input num" value={taxId} onChange={(e) => setTaxId(e.target.value)} inputMode="numeric" autoComplete="off" />
        </label>
        {create.isError && <p className="form-error">{errorText(create.error)}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={create.isPending || name.trim().length < 3 || (tried && !modality)}>
            {create.isPending ? "Criando…" : "Criar e anexar documentos"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
