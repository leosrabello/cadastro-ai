import { useEffect, useState, type FormEvent } from "react";
import { isInsecureRemote, serverUrl, setServerUrl } from "../api/client";
import { useAuth } from "../auth";
import { Dialog, Stamp, errorText } from "../components/ui";
import "./login.css";

// The interface fragment at the foot of the sign-in screen: the registration slip as it fills in.
const SLIP_STATES = [
  [
    { label: "Identidade com foto", state: "Recebido e conferido", tone: "accent" },
    { label: "Comprovante de endereço", state: "Falta", tone: "danger" },
  ],
  [
    { label: "Identidade com foto", state: "Recebido e conferido", tone: "accent" },
    { label: "Comprovante de endereço", state: "Em análise", tone: "muted" },
  ],
  [
    { label: "Identidade com foto", state: "Recebido e conferido", tone: "accent" },
    { label: "Comprovante de endereço", state: "Recebido e conferido", tone: "accent" },
  ],
];

export function Login() {
  const { signIn, sessionExpired } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(sessionExpired ? "Sua sessão terminou. Entre novamente." : null);
  const [busy, setBusy] = useState(false);
  const [editingServer, setEditingServer] = useState(false);
  const [slip, setSlip] = useState(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = setInterval(() => !document.hidden && setSlip((s) => (s + 1) % SLIP_STATES.length), 5600);
    return () => clearInterval(id);
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const host = (() => {
    try {
      return new URL(serverUrl()).host;
    } catch {
      return serverUrl();
    }
  })();

  return (
    <div className="login">
      <button className="login-server link-btn meta" onClick={() => setEditingServer(true)}>
        Servidor: {host}
      </button>
      <div className="login-column">
        <div className="login-mark">
          <Stamp />
        </div>
        <form className="login-form enter" onSubmit={submit}>
          <h1 className="login-title" style={{ ["--i" as string]: 0 }}>
            Cadastros conferidos,
            <br />
            decisões registradas.
          </h1>
          <p className="login-sentence" style={{ ["--i" as string]: 1 }}>Use a conta criada pelo administrador.</p>
          <label className="label" style={{ ["--i" as string]: 2 }}>
            <span>E-mail</span>
            <input className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="label" style={{ ["--i" as string]: 3 }}>
            <span>Senha</span>
            <input className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <div className="row" style={{ marginTop: 6, ["--i" as string]: 4 }}>
            <button className="btn btn-primary" disabled={busy}>
              {busy ? "Entrando…" : "Entrar"}
            </button>
            <span className="meta">Esqueceu a senha? Fale com o administrador.</span>
          </div>
        </form>
      </div>
      <div className="login-fragment" data-ui aria-hidden="true" style={{ animation: "rise 600ms var(--ease) 420ms both" }}>
        <div className="login-fragment-head">
          <span>Exigências do cadastro</span>
          <span className="meta">Pessoa física</span>
        </div>
        <div className="login-fragment-rows">
          {SLIP_STATES.map((rows, i) => (
            <div key={i} className="login-fragment-layer" data-on={i === slip}>
              {rows.map((r) => (
                <div key={r.label} className="login-fragment-row">
                  <span>{r.label}</span>
                  <span className="mark" data-tone={r.tone}>
                    {r.state}
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
      {editingServer && <ServerDialog onClose={() => setEditingServer(false)} />}
    </div>
  );
}

function ServerDialog({ onClose }: { onClose: () => void }) {
  const [url, setUrl] = useState(serverUrl());
  const insecure = isInsecureRemote(url);
  return (
    <Dialog title="Endereço do servidor" onClose={onClose}>
      <p className="muted" style={{ marginBottom: 16 }}>
        O endereço é informado pela equipe de TI. Todos os documentos e decisões ficam nesse servidor, nunca neste computador.
      </p>
      <form
        className="form-grid"
        onSubmit={(e) => {
          e.preventDefault();
          setServerUrl(url);
          onClose();
        }}
      >
        <label className="label">
          <span>Endereço</span>
          <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://cadastro.empresa.local" />
        </label>
        {insecure && <p className="warn-text meta">Endereços fora deste computador precisam usar https:// para que os documentos trafeguem criptografados.</p>}
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary">Salvar</button>
        </div>
      </form>
    </Dialog>
  );
}
