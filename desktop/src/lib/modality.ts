import { useSyncExternalStore } from "react";
import type { Modality } from "../api/types";

// The modality an employee is looking at follows them from the Painel to the other screens.
const KEY = "cadastro.modalidade";
const listeners = new Set<() => void>();

function read(): Modality {
  try {
    return localStorage.getItem(KEY) === "one7" ? "one7" : "normal";
  } catch {
    return "normal";
  }
}

export function setModality(m: Modality) {
  try {
    localStorage.setItem(KEY, m);
  } catch {
    /* storage unavailable: keep the choice for this window only */
  }
  current = m;
  listeners.forEach((l) => l());
}

let current = read();

export function useModality(): [Modality, (m: Modality) => void] {
  const value = useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => current,
  );
  return [value, setModality];
}

export const MODALITY_LABEL: Record<Modality, string> = { normal: "Normal", one7: "One7" };
