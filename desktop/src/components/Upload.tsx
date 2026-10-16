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

const OK_EXT = /\.(pdf|jpe?g|png|docx?|xlsx?)$/i;

export function UploadZone({ registrationId, disabled }: { registrationId: string; disabled?: boolean }) {
  const qc = useQueryClient();
  const { meta } = useAuth();
  const maxBytes = (meta?.limits.max_upload_mb ?? 25) * 1024 * 1024;
  const [items, setItems] = useState<Item[]>([]);
  const [over, setOver] = useState(false);
  const [showList, setShowList] = useState(false);
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
      if (!OK_EXT.test(f.name)) return { key, file: f, state: "error", progress: 0, message: "Formato não aceito. Envie PDF, JPEG, PNG, Word ou Excel." };
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
            <span className="meta">PDF, imagens (JPEG, PNG), Word ou Excel, até {meta?.limits.max_upload_mb ?? 25} MB cada</span>
          </>
        )}
      </div>
      {items.length > 0 && (
        <UploadSummary items={items} open={showList || items.some((x) => x.state === "error")} onToggle={() => setShowList((v) => !v)} onClear={() => { setItems((xs) => xs.filter((x) => x.state !== "done")); setShowList(false); }} />
      )}
      {items.length > 0 && (showList || items.some((x) => x.state === "error")) && (
        <ul className="upload-list" aria-live="polite">
          {[...items].sort((a, b) => Number(b.state === "error") - Number(a.state === "error")).map((it) => (
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

/** One line for the whole batch, so twenty files do not push the page down. */
function UploadSummary({ items, open, onToggle, onClear }: { items: Item[]; open: boolean; onToggle: () => void; onClear: () => void }) {
  const done = items.filter((x) => x.state === "done").length;
  const failed = items.filter((x) => x.state === "error").length;
  const active = items.length - done - failed;
  const sent = items.filter((x) => x.state === "done" || x.state === "error").length + items.filter((x) => x.state === "sending").reduce((a, x) => a + x.progress, 0);
  return (
    <div className="upload-summary" aria-live="polite">
      <span className="upload-bar upload-total" aria-hidden="true"><span style={{ transform: `scaleX(${items.length ? sent / items.length : 0})` }} /></span>
      <span>
        {active > 0 ? `Enviando ${done + failed + 1} de ${items.length}` : `${done} ${done === 1 ? "arquivo enviado" : "arquivos enviados"}, em análise`}
        {failed > 0 && <span className="danger-text">{` · ${failed} com erro`}</span>}
      </span>
      <button className="link-btn meta" onClick={onToggle} disabled={failed > 0}>{open ? "Ocultar a lista" : "Ver a lista"}</button>
      {active === 0 && done > 0 && <button className="link-btn meta" onClick={onClear}>Limpar</button>}
    </div>
  );
}
