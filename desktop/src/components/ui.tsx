import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../api/client";
import type { RegStatus, Severity } from "../api/types";
import { SEVERITY, STATUS } from "../lib/format";

export function Mark({ tone, children }: { tone: string; children: ReactNode }) {
  return (
    <span className="mark" data-tone={tone}>
      {children}
    </span>
  );
}

export function StatusMark({ status }: { status: RegStatus }) {
  const s = STATUS[status];
  return <Mark tone={s.tone}>{s.label}</Mark>;
}

export function SeverityMark({ severity }: { severity: Severity }) {
  const s = SEVERITY[severity];
  return <Mark tone={s.tone}>{s.label}</Mark>;
}

export function Stamp() {
  // The "conferido" stamp: the product's mark.
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
      <rect width="22" height="22" rx="4" fill="var(--accent)" />
      <path d="M6 11.5l3.3 3.3L16 8" fill="none" stroke="var(--accent-ink)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Skeleton({ h = 18, w = "100%" }: { h?: number; w?: number | string }) {
  return <div className="skeleton" style={{ height: h, width: w }} />;
}

export function LoadingRows({ rows = 6 }: { rows?: number }) {
  return (
    <div className="stack" aria-busy="true" aria-label="Carregando">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} h={44} />
      ))}
    </div>
  );
}

export function ErrorBox({ error, retry }: { error: unknown; retry?: () => void }) {
  const msg = error instanceof ApiError ? error.message : "Algo deu errado ao carregar.";
  return (
    <div className="error-box" role="alert">
      <p>{msg}</p>
      {retry && (
        <button className="link-btn" onClick={retry} style={{ marginTop: 8 }}>
          Tentar de novo
        </button>
      )}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      {children && <p className="muted">{children}</p>}
    </div>
  );
}

export function Dialog({ title, children, onClose, labelledBy = "dialog-title" }: { title: string; children: ReactNode; onClose: () => void; labelledBy?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const first = ref.current?.querySelector<HTMLElement>("input, textarea, select, button");
    first?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus();
    };
  }, [onClose]);
  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby={labelledBy} ref={ref}>
        <h2 id={labelledBy}>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      className="switch"
      data-ui
      onClick={() => onChange(!checked)}
    />
  );
}

export function Confidence({ value }: { value: number | null }) {
  if (value === null || value === undefined) return <span className="meta">—</span>;
  const tone = value >= 0.85 ? "var(--ink)" : value >= 0.6 ? "var(--warn)" : "var(--danger)";
  return (
    <span className="meta num" title="Confiança informada pelo OCR ou pela regra. Não é uma probabilidade calibrada." style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{ display: "inline-block", width: 28, height: 4, background: "var(--surface-2)", borderRadius: 2, overflow: "hidden" }}>
        <span style={{ display: "block", height: "100%", width: `${Math.round(value * 100)}%`, background: tone }} />
      </span>
      {Math.round(value * 100)}%
    </span>
  );
}

/* ---------- toasts ---------- */
interface Toast {
  id: number;
  text: string;
  tone?: "danger";
}
const ToastCtx = createContext<(text: string, tone?: "danger") => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone?: "danger") => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, text, tone }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), tone ? 7000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="toast" data-tone={t.tone}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (Array.isArray(e.details) && e.details.length && typeof e.details[0] === "string") return `${e.message} ${e.details.join("; ")}.`;
    return e.message;
  }
  return "Algo deu errado. Tente de novo.";
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;
  return (
    <div className="spread" style={{ marginTop: 16 }}>
      <span className="meta num">
        {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} de {total}
      </span>
      <div className="row">
        <button className="btn btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Anterior
        </button>
        <button className="btn btn-sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Próxima
        </button>
      </div>
    </div>
  );
}
