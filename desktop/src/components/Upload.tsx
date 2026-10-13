import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type DragEvent } from "react";
import { uploadFile } from "../api/client";
import { useAuth } from "../auth";
import { fmtBytes } from "../lib/format";
import { fromBrowserFiles, pickFiles, type PickedFile } from "../lib/files";

interface Item {
  key: string;
  file: PickedFile;
  state: "waiting" | "sending" | "done" | "error";
  progress: number;
  message?: string;
}

const OK_EXT = /\.(pdf|jpe?g|png)$/i;

export function UploadZone({ registrationId, disabled }: { registrationId: string; disabled?: boolean }) {
  const qc = useQueryClient();
  const { meta } = useAuth();
  const maxBytes = (meta?.limits.max_upload_mb ?? 25) * 1024 * 1024;
  const [items, setItems] = useState<Item[]>([]);
  const [over, setOver] = useState(false);
  const running = useRef(0);

  const patch = (key: string, p: Partial<Item>) => setItems((xs) => xs.map((x) => (x.key === key ? { ...x, ...p } : x)));

  async function send(item: Item) {
    running.current += 1;
    patch(item.key, { state: "sending", progress: 0, message: undefined });
    try {
      const blob = await item.file.read();
      const res = await uploadFile(registrationId, blob, item.file.name, (f) => patch(item.key, { progress: f }));
      if (res.ok) patch(item.key, { state: "done", progress: 1 });
      else patch(item.key, { state: "error", message: res.message });
    } catch {
      patch(item.key, { state: "error", message: "Não foi possível ler o arquivo neste computador." });
    } finally {
      running.current -= 1;
      qc.invalidateQueries({ queryKey: ["registration", registrationId] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    }
  }

  async function add(files: PickedFile[]) {
    const fresh: Item[] = files.map((f) => {
      const key = `${f.name}-${f.size}-${Math.random()}`;
      if (!OK_EXT.test(f.name)) return { key, file: f, state: "error", progress: 0, message: "Formato não aceito. Envie PDF, JPEG ou PNG." };
      if (f.size > maxBytes) return { key, file: f, state: "error", progress: 0, message: `Passa do limite de ${meta?.limits.max_upload_mb ?? 25} MB.` };
      return { key, file: f, state: "waiting", progress: 0 };
    });
    setItems((xs) => [...fresh, ...xs.filter((x) => x.state !== "done")]);
    // two at a time keeps progress readable and the server calm
    const queue = fresh.filter((x) => x.state === "waiting");
    const workers = Array.from({ length: Math.min(2, queue.length) }, async () => {
      while (queue.length) await send(queue.shift()!);
    });
    await Promise.all(workers);
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (!disabled && e.dataTransfer.files.length) add(fromBrowserFiles(e.dataTransfer.files));
  };

  return (
    <div>
      <div
        className="dropzone"
        data-over={over}
        data-disabled={disabled}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
      >
        {disabled ? (
          <span className="muted">Cadastro decidido. Reabra-o para anexar documentos.</span>
        ) : (
          <>
            <span>Arraste os documentos para cá</span>
            <span className="muted">ou</span>
            <button className="btn btn-sm" onClick={async () => add(await pickFiles())}>
              Escolher arquivos
            </button>
            <span className="meta">PDF, JPEG ou PNG, até {meta?.limits.max_upload_mb ?? 25} MB cada</span>
          </>
        )}
      </div>
      {items.length > 0 && (
        <ul className="upload-list" aria-live="polite">
          {items.map((it) => (
            <li key={it.key} data-state={it.state}>
              <span className="upload-name">{it.file.name}</span>
              <span className="meta num">{fmtBytes(it.file.size)}</span>
              <span className="upload-state">
                {it.state === "waiting" && <span className="muted">Na fila</span>}
                {it.state === "sending" && (
                  <span className="upload-bar" aria-label={`Enviando ${Math.round(it.progress * 100)}%`}>
                    <span style={{ transform: `scaleX(${it.progress})` }} />
                  </span>
                )}
                {it.state === "done" && <span className="mark" data-tone="accent">Recebido, em análise</span>}
                {it.state === "error" && (
                  <span className="danger-text">
                    {it.message}{" "}
                    {OK_EXT.test(it.file.name) && it.file.size <= maxBytes && (
                      <button className="link-btn" onClick={() => send(it)}>
                        Tentar de novo
                      </button>
                    )}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
