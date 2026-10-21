import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, apiBlob } from "../api/client";
import type { DocumentDetail, Evidence, ExtractedField } from "../api/types";
import { useAuth, usePerm } from "../auth";
import { DeleteDocument } from "../components/DeleteDocument";
import { FindingCard } from "../components/FindingCard";
import { Confidence, ErrorBox, Mark, Skeleton, errorText, useToast } from "../components/ui";
import { SOURCE, VALIDITY, fmtBytes, fmtDateTime, fmtFieldValue, pct } from "../lib/format";
import "./review.css";

type Region = { page: number; bbox: number[] } | null;

export function DocumentReview() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const perm = usePerm();
  const { meta } = useAuth();

  const [page, setPage] = useState(Number(params.get("pagina") ?? 0));
  const [zoom, setZoom] = useState(1);
  const [hover, setHover] = useState<Region>(null);
  const [deleting, setDeleting] = useState(false);
  const [showNotes, setShowNotes] = useState(false);
  const [focus, setFocus] = useState<Region>(() => {
    const r = params.get("regiao");
    return r ? { page: Number(params.get("pagina") ?? 0), bbox: r.split(",").map(Number) } : null;
  });
  const [showBoxes, setShowBoxes] = useState(false);

  const q = useQuery({
    queryKey: ["document", id],
    queryFn: () => api<DocumentDetail>(`/api/documents/${id}`),
    refetchInterval: (query) => (query.state.data && ["queued", "processing"].includes(query.state.data.status) ? 2500 : false),
  });
  const d = q.data;
  const pageCount = d?.page_count ?? 1;

  const img = useQuery({
    queryKey: ["page", id, page],
    queryFn: async () => URL.createObjectURL(await apiBlob(`/api/documents/${id}/pages/${page}`)),
    enabled: !!d && d.status !== "purged",
    staleTime: Infinity,
  });

  useEffect(() => {
    setPage(Number(params.get("pagina") ?? 0));
  }, [id, params]);

  useEffect(() => {
    if (focus) {
      setPage(focus.page);
      setZoom((z) => Math.max(z, 1.6));
    }
  }, [focus]);

  const reprocess = useMutation({
    mutationFn: () => api(`/api/documents/${id}/reprocess`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["document", id] });
      toast("Documento enviado para nova análise.");
    },
    onError: (e) => toast(errorText(e), "danger"),
  });

  const classify = useMutation({
    mutationFn: (doc_type: string) => api(`/api/documents/${id}/classification`, { method: "PATCH", json: { doc_type, reason: "classificação manual na revisão" } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["document", id] });
      toast("Tipo alterado. O documento será analisado de novo com as regras desse tipo.");
    },
    onError: (e) => toast(errorText(e), "danger"),
  });

  if (q.isError) return <div className="page"><ErrorBox error={q.error} retry={() => q.refetch()} /></div>;
  if (!d) return <div className="review"><div className="stage"><Skeleton h={600} /></div><div className="inspector"><Skeleton h={400} /></div></div>;

  const regionOnPage = (r: Region) => (r && r.page === page ? r.bbox : null);
  const lit = regionOnPage(hover) ?? regionOnPage(focus);
  const idx = d.siblings.findIndex((s) => s.id === d.id);
  const prev = idx > 0 ? d.siblings[idx - 1] : null;
  const next = idx >= 0 && idx < d.siblings.length - 1 ? d.siblings[idx + 1] : null;
  const busy = d.status === "queued" || d.status === "processing";
  const closed = d.registration?.status === "approved" || d.registration?.status === "rejected";
  const typeLabel = d.doc_type ? meta?.document_types[d.doc_type]?.label ?? d.doc_type : "Tipo não identificado";
  const openFindings = d.findings.filter((f) => f.status === "open" || f.status === "escalated");
  const notes = d.findings.filter((f) => f.status === "note");
  const onEvidence = (e: Evidence) => {
    if (e.document_id && e.document_id !== d.id) {
      const qs = new URLSearchParams();
      if (e.page !== null) qs.set("pagina", String(e.page));
      if (e.bbox) qs.set("regiao", e.bbox.join(","));
      nav(`/documentos/${e.document_id}?${qs}`);
    } else if (e.page !== null) {
      setFocus(e.bbox ? { page: e.page, bbox: e.bbox } : null);
      setPage(e.page);
    }
  };

  return (
    <div className="review">
      <section className="stage" aria-label="Documento original">
        <div className="stage-bar">
          <div className="row">
            {d.registration ? <Link to={`/cadastros/${d.registration.id}`} className="meta">{d.registration.subject_name}</Link> : <Link to="/entrada" className="meta">Caixa de entrada</Link>}
            <span className="meta">/</span>
            <span>{d.original_filename}</span>
          </div>
          <div className="row stage-tools">
            <button className="btn btn-sm" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0} aria-label="Página anterior">‹</button>
            <span className="num meta">pág. {page + 1} de {pageCount}</span>
            <button className="btn btn-sm" onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))} disabled={page >= pageCount - 1} aria-label="Próxima página">›</button>
            <span className="stage-gap" />
            <button className="btn btn-sm" onClick={() => setZoom((z) => Math.max(0.5, +(z - 0.25).toFixed(2)))} aria-label="Diminuir zoom">−</button>
            <span className="num meta" style={{ width: 44, textAlign: "center" }}>{Math.round(zoom * 100)}%</span>
            <button className="btn btn-sm" onClick={() => setZoom((z) => Math.min(4, +(z + 0.25).toFixed(2)))} aria-label="Aumentar zoom">+</button>
            <button className="btn btn-sm btn-ghost" onClick={() => { setZoom(1); setFocus(null); }}>Ajustar</button>
            <button className="btn btn-sm btn-ghost" aria-pressed={showBoxes} onClick={() => setShowBoxes((v) => !v)}>{showBoxes ? "Ocultar campos" : "Mostrar campos"}</button>
            <button className="btn btn-sm btn-ghost" onClick={async () => {
              const blob = await apiBlob(`/api/documents/${id}/file`);
              const a = document.createElement("a");
              a.href = URL.createObjectURL(blob);
              a.download = d.original_filename;
              a.click();
            }}>Baixar original</button>
            {perm.operate && d.registration?.status !== "approved" && <button className="btn btn-sm btn-ghost" onClick={() => setDeleting(true)}>Excluir</button>}
          </div>
        </div>
        <Viewer src={img.data} loading={img.isLoading} error={img.error} zoom={zoom} lit={lit} focus={regionOnPage(focus)}
          boxes={showBoxes ? d.fields.filter((f) => f.page === page && f.bbox).map((f) => ({ key: f.id, bbox: f.bbox!, label: f.label })) : []}
          purged={d.status === "purged"} />
      </section>

      {deleting && <DeleteDocument d={d} onClose={() => setDeleting(false)} onDone={() => nav(d.registration ? `/cadastros/${d.registration.id}` : "/entrada")} />}
      <aside className="inspector" aria-label="Análise do documento">
        <div className="inspector-nav">
          {prev ? <Link to={`/documentos/${prev.id}`} className="meta">‹ Anterior</Link> : <span />}
          <span className="meta num">{idx >= 0 ? `${idx + 1} de ${d.siblings.length}` : ""}</span>
          {next ? <Link to={`/documentos/${next.id}`} className="meta">Próximo ›</Link> : <span />}
        </div>

        <header className="inspector-head">
          <h1 className="inspector-title">{typeLabel}</h1>
          <p className="meta">
            {d.doc_type_source === "human" ? "Classificado pelo revisor" : d.doc_type_source === "ai" ? "Classificado pela IA" : d.doc_type ? `Classificado por regras, indicador ${pct(d.doc_type_confidence)}` : "As regras não reconheceram o tipo"}
            {d.issuer && ` · Emissor: ${d.issuer}`}
          </p>
          {perm.operate && !closed && (
            <select className="select" style={{ marginTop: 10 }} value={d.doc_type ?? ""} onChange={(e) => e.target.value && classify.mutate(e.target.value)} aria-label="Corrigir o tipo do documento" disabled={busy}>
              <option value="" disabled>Escolher o tipo…</option>
              {Object.entries(meta?.document_types ?? {}).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          )}
        </header>

        {busy ? (
          <div className="processing-note"><Mark tone="muted">{d.status === "queued" ? "Na fila de análise" : "Lendo o documento"}</Mark><p className="meta">Os campos e os pontos aparecem aqui em alguns segundos.</p></div>
        ) : d.status === "failed" ? (
          <div className="error-box">
            <p>A análise automática falhou: {d.processing_error}</p>
            {perm.operate && <button className="btn btn-sm" style={{ marginTop: 10 }} onClick={() => reprocess.mutate()}>Tentar de novo</button>}
          </div>
        ) : d.validity && (
          <div className="validity" data-state={d.validity.state}>
            <Mark tone={VALIDITY[d.validity.state].tone}>{VALIDITY[d.validity.state].label}</Mark>
            <p>{d.validity.summary}</p>
            {d.validity.rule && <p className="meta">Regra: {d.validity.rule}. Referência: {fmtFieldValue("data_ref", d.validity.reference_date)}.</p>}
          </div>
        )}

        {d.fields.length > 0 && (
          <section>
            <h2 className="inspector-h">Campos lidos</h2>
            <p className="meta" style={{ marginBottom: 8 }}>Passe o mouse sobre um campo para ver de onde ele foi lido.</p>
            <ul className="fields">
              {d.fields.map((f) => (
                <FieldRow key={f.id} f={f} docId={d.id} editable={perm.operate && !closed}
                  onHover={(on) => setHover(on && f.bbox && f.page !== null ? { page: f.page, bbox: f.bbox } : null)}
                  onFocus={() => f.bbox && f.page !== null && setFocus({ page: f.page, bbox: f.bbox })} />
              ))}
            </ul>
          </section>
        )}
        {d.missing_fields.length > 0 && !busy && (
          <section>
            <h2 className="inspector-h">Não encontrados</h2>
            <ul className="fields">
              {d.missing_fields.map((m) => (
                <FieldRow key={m.name} docId={d.id} editable={perm.operate && !closed} onHover={() => {}} onFocus={() => {}}
                  f={{ id: m.name, name: m.name, label: m.label, value: null, raw_value: null, confidence: null, source: "ocr", page: null, bbox: null, valid: null, validation_note: null, status: "extracted", previous_value: null }} />
              ))}
            </ul>
          </section>
        )}

        <section>
          <h2 className="inspector-h">Pontos deste documento</h2>
          {openFindings.length === 0 ? (
            <p className="muted">{busy ? "Aguardando análise." : "Nenhum ponto em aberto neste documento."}</p>
          ) : (
            <div className="stack">
              {openFindings.map((f) => (
                <div key={f.id} onMouseEnter={() => { const e = f.evidence.find((x) => x.bbox && x.document_id === d.id); if (e) setHover({ page: e.page ?? 0, bbox: e.bbox! }); }} onMouseLeave={() => setHover(null)}>
                  <FindingCard f={f} onEvidence={onEvidence} closed={closed} />
                </div>
              ))}
            </div>
          )}
          {notes.length > 0 && (
            <div className="notes">
              <button className="link-btn meta" aria-expanded={showNotes} onClick={() => setShowNotes((v) => !v)}>
                {showNotes ? "Ocultar" : "Ver"} {notes.length === 1 ? "1 observação" : `${notes.length} observações`} sem ação necessária
              </button>
              {showNotes && (
                <div className="stack" style={{ marginTop: 10 }}>
                  {notes.map((f) => <FindingCard key={f.id} f={f} compact closed onEvidence={onEvidence} />)}
                </div>
              )}
            </div>
          )}
        </section>

        <section className="processing-facts">
          <h2 className="inspector-h">Processamento</h2>
          <dl>
            <div><dt>Recebido</dt><dd>{fmtDateTime(d.received_at)} · {d.source === "shared_folder" ? `pasta: ${d.source_ref}` : "envio manual"}</dd></div>
            <div><dt>Arquivo</dt><dd>{d.mime_type.replace("application/", "").replace("image/", "").toUpperCase()} · {fmtBytes(d.size_bytes)} · {pageCount} pág.</dd></div>
            <div><dt>Leitura</dt><dd>{d.ocr_provider === "pdf_text" ? "Texto embutido no PDF (com conferência por OCR)" : d.ocr_provider ? `OCR ${d.ocr_provider}` : "—"}</dd></div>
            <div><dt>IA</dt><dd>{d.ai_status === "done" ? "Análise complementar concluída" : d.ai_status === "failed" ? `Não concluída: ${d.ai_error}` : d.ai_error ?? "—"}</dd></div>
            {d.job?.duration_ms && <div><dt>Duração</dt><dd className="num">{(d.job.duration_ms / 1000).toFixed(1).replace(".", ",")} s · {d.processing_attempts} tentativa(s)</dd></div>}
            <div><dt>SHA-256</dt><dd className="num" title={d.sha256}>{d.sha256.slice(0, 16)}…</dd></div>
          </dl>
          {perm.operate && !busy && d.status !== "purged" && (
            <button className="btn btn-sm" onClick={() => reprocess.mutate()} disabled={reprocess.isPending}>Analisar de novo</button>
          )}
        </section>
      </aside>
    </div>
  );
}

function Viewer({ src, loading, error, zoom, lit, focus, boxes, purged }: {
  src?: string; loading: boolean; error: unknown; zoom: number; lit: number[] | null; focus: number[] | null;
  boxes: { key: string; bbox: number[]; label: string }[]; purged: boolean;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const sheet = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!focus || !scroller.current || !sheet.current) return;
    const t = setTimeout(() => {
      const s = scroller.current!, sh = sheet.current!;
      const x = sh.offsetLeft + focus[0] * sh.offsetWidth - s.clientWidth / 3;
      const y = sh.offsetTop + focus[1] * sh.offsetHeight - s.clientHeight / 3;
      s.scrollTo({ left: x, top: y, behavior: "smooth" });
    }, 200); // after the zoom transition settles
    return () => clearTimeout(t);
  }, [focus, zoom, src]);

  if (purged) return <div className="viewer"><p className="muted" style={{ padding: 40 }}>O arquivo original foi expurgado pela política de retenção.</p></div>;
  return (
    <div className="viewer" ref={scroller}>
      {error ? <div style={{ padding: 40 }}><ErrorBox error={error} /></div> : !src || loading ? (
        <div className="sheet-wrap"><Skeleton h={520} w={760} /></div>
      ) : (
        <div className="sheet-wrap">
          <div className="sheet" ref={sheet} style={{ ["--zoom" as string]: zoom }}>
            <img src={src} alt="Página do documento original" draggable={false} />
            {boxes.map((b) => <Box key={b.key} bbox={b.bbox} kind="field" title={b.label} />)}
            {lit && <Box bbox={lit} kind="lit" />}
          </div>
        </div>
      )}
    </div>
  );
}

function Box({ bbox, kind, title }: { bbox: number[]; kind: "lit" | "field"; title?: string }) {
  const pad = 0.006;
  const [x0, y0, x1, y1] = bbox;
  return (
    <span className={`box box-${kind}`} title={title} style={{
      left: `${(x0 - pad) * 100}%`, top: `${(y0 - pad) * 100}%`, width: `${(x1 - x0 + 2 * pad) * 100}%`, height: `${(y1 - y0 + 2 * pad) * 100}%`,
    }} />
  );
}

function FieldRow({ f, docId, editable, onHover, onFocus }: { f: ExtractedField; docId: string; editable: boolean; onHover: (on: boolean) => void; onFocus: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(f.value ? fmtFieldValue(f.name, f.value) : "");
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: (body: object) => api(`/api/documents/${docId}/fields/${f.name}`, { method: "PATCH", json: body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["document", docId] });
      qc.invalidateQueries({ queryKey: ["registration"] });
      setEditing(false);
      setReason("");
    },
    onError: (e) => toast(errorText(e), "danger"),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate({ action: "correct", value, reason });
  };
  const differs = f.raw_value && f.value && f.raw_value.replace(/\W/g, "").toUpperCase() !== fmtFieldValue(f.name, f.value).replace(/\W/g, "").toUpperCase();
  return (
    <li className="field" data-status={f.status} data-invalid={f.valid === false} onMouseEnter={() => onHover(true)} onMouseLeave={() => onHover(false)}>
      <div className="field-top">
        <span className="meta">{f.label}</span>
        {f.status !== "extracted" ? <span className="meta">{f.status === "confirmed" ? "Confirmado" : "Corrigido"} pelo revisor</span> : <Confidence value={f.confidence} />}
      </div>
      {editing ? (
        <form className="form-grid field-edit" onSubmit={submit}>
          <input className="input" value={value} onChange={(e) => setValue(e.target.value)} autoFocus aria-label={`Valor correto de ${f.label}`} />
          <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Motivo da correção" aria-label="Motivo da correção" />
          <div className="row">
            <button className="btn btn-sm btn-primary" disabled={m.isPending || !value.trim() || reason.trim().length < 5}>Salvar</button>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setEditing(false)}>Cancelar</button>
          </div>
        </form>
      ) : (
        <>
          <button className="field-value" onClick={onFocus} disabled={!f.bbox} title={f.bbox ? "Ampliar a região no documento" : undefined}>
            {f.value ? fmtFieldValue(f.name, f.value) : <span className="muted">Não encontrado</span>}
          </button>
          {differs && <span className="meta">Lido como “{f.raw_value}”</span>}
          {f.validation_note && <span className={f.valid === false ? "meta danger-text" : "meta"}>{f.validation_note}</span>}
          {f.previous_value && <span className="meta">Antes: {fmtFieldValue(f.name, f.previous_value)}</span>}
          <div className="field-foot">
            <span className="meta">{SOURCE[f.source] ?? f.source}{f.page !== null ? ` · pág. ${f.page + 1}` : ""}</span>
            {editable && (
              <span className="row" style={{ gap: 4 }}>
                {f.value && f.status === "extracted" && <button className="btn btn-sm btn-ghost" onClick={() => m.mutate({ action: "confirm" })}>Confirmar</button>}
                <button className="btn btn-sm btn-ghost" onClick={() => setEditing(true)}>{f.value ? "Corrigir" : "Preencher"}</button>
              </span>
            )}
          </div>
        </>
      )}
    </li>
  );
}
