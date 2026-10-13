import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, hasToken, onSessionLost, setToken } from "./api/client";
import type { Meta } from "./api/types";

interface AuthState {
  meta: Meta | undefined;
  signedIn: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  sessionExpired: boolean;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [signedIn, setSignedIn] = useState(hasToken());
  const [sessionExpired, setExpired] = useState(false);

  useEffect(() => {
    onSessionLost(() => {
      setSignedIn(false);
      setExpired(true);
      qc.clear();
    });
  }, [qc]);

  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/api/meta"), enabled: signedIn, staleTime: 60_000 });

  const signIn = useCallback(async (email: string, password: string) => {
    const res = await api<{ token: string }>("/api/auth/login", { method: "POST", json: { email, password } });
    setToken(res.token);
    setExpired(false);
    setSignedIn(true);
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      setToken(null);
      setSignedIn(false);
      qc.clear();
    }
  }, [qc]);

  return <Ctx.Provider value={{ meta: meta.data, signedIn, signIn, signOut, sessionExpired }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside provider");
  return v;
}

export function usePerm() {
  const { meta } = useAuth();
  return meta?.permissions ?? { operate: false, approve: false, reject: false, override: false, audit: false, admin: false };
}
