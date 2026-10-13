import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { isInsecureRemote, servedByServer, serverUrl, setServerUrl } from "../api/client";
import { useAuth } from "../auth";
import { Logo } from "../components/Logo";
import { Dialog, errorText } from "../components/ui";
import "./login.css";

export function Login() {
  const { signIn, sessionExpired } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(sessionExpired ? "Sua sessão terminou. Entre novamente." : null);
  const [busy, setBusy] = useState(false);
  const [editingServer, setEditingServer] = useState(false);

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
      <div className="login-top">
        <Link to="/" className="login-back">Voltar</Link>
        {!servedByServer && <button className="login-server" onClick={() => setEditingServer(true)}>Servidor: {host}</button>}
      </div>
      <main className="login-center">
        <h1 className="login-logo enter">
          <span style={{ ["--i" as string]: 0 }}><Logo size={44} /></span>
        </h1>
        <form className="login-form enter" onSubmit={submit}>
          <label className="label" style={{ ["--i" as string]: 1 }}>
            <span>E-mail</span>
            <input className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
          </label>
          <label className="label" style={{ ["--i" as string]: 2 }}>
            <span>Senha</span>
            <input className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button className="btn btn-primary login-submit" disabled={busy} style={{ ["--i" as string]: 3 }}>
            {busy ? "Entrando…" : "Entrar"}
          </button>
          <p className="meta login-help" style={{ ["--i" as string]: 4 }}>Esqueceu a senha? Fale com o administrador.</p>
        </form>
      </main>
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
