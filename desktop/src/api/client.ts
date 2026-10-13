// The desktop app talks only to the Cadastro AI API. It stores no secrets: the session token
// lives in memory (and sessionStorage, so a reload does not log the employee out) and dies
// with the window. The server address is a per-machine preference.

const SERVER_KEY = "cadastro.server";
const TOKEN_KEY = "cadastro.session";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

function safeGet(store: Storage, key: string): string | null {
  try {
    return store.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(store: Storage, key: string, value: string | null) {
  try {
    if (value === null) store.removeItem(key);
    else store.setItem(key, value);
  } catch {
    /* storage unavailable: keep working in memory */
  }
}

let token: string | null = safeGet(sessionStorage, TOKEN_KEY);
let onUnauthorized: (() => void) | null = null;

/** Opened in a browser from the company server: the API is on the same address, nothing to configure. */
export const servedByServer = typeof window !== "undefined" && !("__TAURI_INTERNALS__" in window) && import.meta.env.PROD;

export function serverUrl(): string {
  if (servedByServer) return window.location.origin;
  return (safeGet(localStorage, SERVER_KEY) || import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/+$/, "");
}

export function setServerUrl(url: string) {
  safeSet(localStorage, SERVER_KEY, url.trim().replace(/\/+$/, ""));
}

export function isInsecureRemote(url: string): boolean {
  try {
    const u = new URL(url);
    return u.protocol === "http:" && !["localhost", "127.0.0.1"].includes(u.hostname);
  } catch {
    return true;
  }
}

export function setToken(value: string | null) {
  token = value;
  safeSet(sessionStorage, TOKEN_KEY, value);
}

export function hasToken() {
  return token !== null;
}

export function onSessionLost(fn: () => void) {
  onUnauthorized = fn;
}

async function toError(res: Response): Promise<ApiError> {
  let body: { error?: { code?: string; message?: string; details?: unknown } } = {};
  try {
    body = await res.json();
  } catch {
    /* not JSON */
  }
  const e = body.error ?? {};
  return new ApiError(res.status, e.code ?? "error", e.message ?? `Erro ${res.status} no servidor.`, e.details);
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  let res: Response;
  try {
    res = await fetch(serverUrl() + path, { ...init, headers, body });
  } catch {
    throw new ApiError(0, "network", "Não foi possível falar com o servidor. Verifique a rede ou o endereço do servidor.");
  }
  if (res.status === 401 && token) {
    setToken(null);
    onUnauthorized?.();
  }
  if (!res.ok) throw await toError(res);
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function apiBlob(path: string): Promise<Blob> {
  const res = await fetch(serverUrl() + path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw await toError(res);
  return res.blob();
}

export type UploadOutcome =
  | { ok: true; documentId: string }
  | { ok: false; code: string; message: string };

/** Uploads one file with progress. Uses XHR because fetch cannot report upload progress. */
export function uploadFile(registrationId: string, file: Blob, name: string, onProgress: (fraction: number) => void): Promise<UploadOutcome> {
  return new Promise((resolve) => {
    const form = new FormData();
    form.append("files", file, name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${serverUrl()}/api/registrations/${registrationId}/documents`);
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onerror = () => resolve({ ok: false, code: "network", message: "A conexão caiu durante o envio. Tente de novo." });
    xhr.onload = () => {
      let body: any = {};
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status === 401) {
        setToken(null);
        onUnauthorized?.();
      }
      const first = body?.results?.[0] ?? body?.error?.details?.[0];
      if (xhr.status < 300 && first?.ok) return resolve({ ok: true, documentId: first.document.id });
      const err = first?.error ?? body?.error ?? {};
      resolve({ ok: false, code: err.code ?? "error", message: err.message ?? `Erro ${xhr.status} no envio.` });
    };
    xhr.send(form);
  });
}
