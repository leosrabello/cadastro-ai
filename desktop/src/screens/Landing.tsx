import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { servedByServer, serverUrl } from "../api/client";
import { Logo } from "../components/Logo";
import fields from "../assets/landing-fields.json";
import "./landing.css";

/* ---------- CPF / CNPJ check digits, the same rule the server applies ---------- */
const onlyDigits = (s: string) => s.replace(/\D/g, "");

function cpfOk(d: string) {
  if (d.length !== 11 || /^(\d)\1+$/.test(d)) return false;
  for (const n of [9, 10]) {
    let sum = 0;
    for (let i = 0; i < n; i++) sum += Number(d[i]) * (n + 1 - i);
    if (((sum * 10) % 11) % 10 !== Number(d[n])) return false;
  }
  return true;
}

function cnpjOk(d: string) {
  if (d.length !== 14 || /^(\d)\1+$/.test(d)) return false;
  const w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
  for (const [w, pos] of [[w1, 12], [[6, ...w1], 13]] as [number[], number][]) {
    const r = w.reduce((s, x, i) => s + Number(d[i]) * x, 0) % 11;
    if ((r < 2 ? 0 : 11 - r) !== Number(d[pos])) return false;
  }
  return true;
}

function check(input: string) {
  const d = onlyDigits(input);
  if (d.length === 11) {
    const ok = cpfOk(d);
    return { kind: "CPF", ok, formatted: `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}` };
  }
  if (d.length === 14) {
    const ok = cnpjOk(d);
    return { kind: "CNPJ", ok, formatted: `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}` };
  }
  return { kind: d.length > 11 ? "CNPJ" : "CPF", ok: null as boolean | null, formatted: input, missing: (d.length > 11 ? 14 : 11) - d.length };
}

const EXAMPLES = ["529.982.247-25", "529.982.247-26", "11.222.333/0001-81"];

/* ---------- the rules, as the server applies them by default ---------- */
const RULES: { group: string; rows: { name: string; value: string; tone: string }[] }[] = [
  {
    group: "Pessoa física",
    rows: [
      { name: "RG sem validade impressa", value: "até 10 anos da expedição", tone: "ink" },
      { name: "Carteira de Identidade Nacional", value: "até a validade impressa", tone: "ink" },
      { name: "CNH", value: "até a validade, sem tolerância", tone: "ink" },
      { name: "Comprovante de endereço", value: "emitido há até 90 dias", tone: "warn" },
    ],
  },
  {
    group: "Pessoa jurídica",
    rows: [
      { name: "Comprovante de inscrição CNPJ", value: "até 30 dias e situação ATIVA", tone: "warn" },
      { name: "Contrato social consolidado", value: "não expira", tone: "accent" },
      { name: "Identidade do representante", value: "mesmas regras da pessoa física", tone: "ink" },
    ],
  },
  {
    group: "Ordem da fila",
    rows: [
      { name: "Falha no processamento", value: "100 pontos", tone: "danger" },
      { name: "Indício crítico em aberto", value: "80 pontos", tone: "danger" },
      { name: "Escalado para supervisão", value: "70 pontos", tone: "warn" },
      { name: "Ponto de alta severidade", value: "50 pontos", tone: "warn" },
      { name: "Documento vencido", value: "40 pontos", tone: "warn" },
      { name: "Documento obrigatório ausente", value: "30 pontos", tone: "ink" },
      { name: "Aguardando há mais de 2 dias", value: "20 pontos", tone: "ink" },
      { name: "Pronto para decisão", value: "10 pontos", tone: "accent" },
    ],
  },
];

const SWITCHES = [
  { id: "server", on: true, sentence: "Ler tudo no servidor da empresa", consequence: "OCR em português, cerca de 0,2 s por página. Nenhum documento sai da rede." },
  { id: "layer", on: false, sentence: "Conferir o texto escondido do PDF", consequence: "Número que existe no arquivo e não aparece impresso vira ponto de alta severidade." },
  { id: "ai", on: true, sentence: "Pedir uma segunda leitura à IA", consequence: "Cerca de US$ 0,03 por documento. A IA aponta; quem aprova é a equipe." },
  { id: "folder", on: false, sentence: "Receber pela pasta compartilhada", consequence: "Arquivo com CAD-2026-000123 no nome entra direto no cadastro certo." },
];

const HISTORY: { day: string; rows: [string, string, string, string, string][] }[] = [
  {
    day: "Hoje",
    rows: [
      ["15:29", "Aprovou", "“Documentos conferidos com o original.”", "Sérgio Prado", "CAD-2026-000001"],
      ["15:16", "Análise automática concluída", "CNH, dentro da validade, nenhum ponto", "sistema", "CAD-2026-000008"],
      ["15:16", "Recebeu documento", "CAD-2026-000008_cnh.png, pela pasta", "pasta monitorada", "CAD-2026-000008"],
      ["15:14", "Corrigiu campo", "Validade: 01/01/2025 → 01/01/2035", "Ana Ribeiro", "CAD-2026-000003"],
      ["15:12", "Escalou para supervisão", "“Conferir assinatura do contrato”", "Ana Ribeiro", "CAD-2026-000005"],
    ],
  },
  {
    day: "Ontem",
    rows: [
      ["17:48", "Solicitou documentos", "Comprovante de endereço recente", "Ana Ribeiro", "CAD-2026-000006"],
      ["09:02", "Tentativa de acesso recusada", "senha incorreta", "joao.lima", ""],
    ],
  },
];

type Box = { value: string; raw: string; conf: number; bbox: number[] };
const CNH = (fields as any).cnh.fields as Record<string, Box>;
const CNH_ROWS: [string, string][] = [["nome", "Nome"], ["cpf", "CPF"], ["data_nascimento", "Nascimento"], ["validade", "Validade"]];

function scrollTo(id: string) {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.getElementById(id)?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
}

function useReveal() {
  useEffect(() => {
    const els = document.querySelectorAll<HTMLElement>("[data-reveal]");
    if (!("IntersectionObserver" in window)) {
      els.forEach((el) => el.classList.add("in"));
      return;
    }
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && (e.target.classList.add("in"), io.unobserve(e.target))),
      { rootMargin: "0px 0px -8% 0px" },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
}

export function Landing() {
  const nav = useNavigate();
  const [typed, setTyped] = useState(EXAMPLES[0]);
  const [switches, setSwitches] = useState(SWITCHES.map((s) => s.on));
  const [lit, setLit] = useState<string>("cpf");
  const photo = useRef<HTMLDivElement>(null);
  useReveal();

  useEffect(() => {
    document.documentElement.classList.add("landing-scroll");
    return () => document.documentElement.classList.remove("landing-scroll");
  }, []);

  // the one moving picture: the archive drawer drifts slowly as it crosses the screen
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0;
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const el = photo.current;
        if (!el) return;
        const r = el.getBoundingClientRect();
        const p = Math.min(1, Math.max(0, 1 - (r.top + r.height) / (window.innerHeight + r.height)));
        el.style.setProperty("--drift", String(p));
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const result = check(typed);
  const host = (() => {
    try {
      return new URL(serverUrl()).host;
    } catch {
      return serverUrl();
    }
  })();
  const box = CNH[lit]?.bbox;

  return (
    <div className="landing">
      {/* ---------- hero: the name, full width ---------- */}
      <header className="l-hero">
        <div className="l-top">
          <Logo size={20} />
          <nav className="l-links" aria-label="Seções">
            <a href="#/" onClick={(e) => { e.preventDefault(); scrollTo("como-funciona"); }}>Como funciona</a>
            <a href="#/" onClick={(e) => { e.preventDefault(); scrollTo("regras"); }}>Regras</a>
            <Link to="/entrar">Entrar</Link>
          </nav>
        </div>
        <h1 className="l-name" aria-label="CadastroAI">
          <span className="l-mask"><span className="l-line">CadastroAI</span></span>
        </h1>
        <div className="l-bottom">
          <p className="l-sentence">Lê os documentos do cadastro, confere as regras da casa e mostra à equipe o que precisa de decisão.</p>
          <button className="l-action" onClick={() => nav("/entrar")}>Entrar</button>
        </div>
      </header>

      {/* ---------- showcase: a headline you can type ---------- */}
      <section className="l-type" aria-labelledby="type-h">
        <h2 id="type-h" className="visually-hidden">Confira um CPF ou CNPJ</h2>
        <div className="l-type-field" data-ui>
          <input
            className="l-type-input num"
            value={typed}
            onChange={(e) => setTyped(e.target.value.slice(0, 24))}
            aria-label="Digite um CPF ou CNPJ"
            inputMode="numeric"
            spellCheck={false}
          />
        </div>
        <div className="l-answer" data-ui aria-live="polite" data-reveal>
          <div className="l-answer-row">
            <span className="muted">{result.kind}</span>
            <span className="num strong">{result.formatted || "—"}</span>
          </div>
          <div className="l-answer-row">
            <span className="muted">Dígitos verificadores</span>
            {result.ok === null ? (
              <span className="mark" data-tone="hollow">Faltam {(result as any).missing} dígitos</span>
            ) : result.ok ? (
              <span className="mark" data-tone="accent">Conferem</span>
            ) : (
              <span className="mark" data-tone="danger">Não conferem</span>
            )}
          </div>
          <p className="l-answer-note">
            {result.ok === false
              ? "Leitura errada ou número adulterado. No cadastro, isso vira um ponto de alta severidade para alguém conferir no original."
              : "No cadastro, o número também é comparado com o informado na abertura e com os outros documentos do cliente."}
          </p>
        </div>
        <div className="l-examples">
          {EXAMPLES.map((ex) => (
            <button key={ex} className="l-example num" onClick={() => setTyped(ex)} aria-pressed={typed === ex}>{ex}</button>
          ))}
        </div>
      </section>

      {/* ---------- list: the rules with their dates ---------- */}
      <section className="l-rules" id="regras" aria-labelledby="rules-h">
        <div className="l-rules-col">
          <h2 id="rules-h" data-reveal>Regras com data</h2>
          {RULES.map((g, gi) => (
            <div key={g.group} className="l-group" data-reveal style={{ ["--i" as string]: gi }}>
              <p className="l-group-name">{g.group}</p>
              <ul>
                {g.rows.map((r) => (
                  <li key={r.name}>
                    <span className="l-dot" data-tone={r.tone} />
                    <span className="l-rule-name">{r.name}</span>
                    <span className="l-rule-value num">{r.value}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <p className="l-group-name" data-reveal>Todas ajustáveis em Configurações, com registro de quem mudou.</p>
        </div>
        <figure className="l-archive" data-reveal>
          <img src="landing/visto-verificado.jpg" width={1920} height={1489} loading="lazy"
            alt="Desenho técnico do Ministério da Agricultura com carimbo de título: projetado, calculado, desenhado, verificado por e visto" />
          <figcaption>Antes, o “verificado por” e o “visto” eram carimbos. Desenho de Ruth Crivamo, acervo LabDoc-UFRRJ, CC BY-SA 4.0.</figcaption>
        </figure>
      </section>

      {/* ---------- features: sentences with switches ---------- */}
      <section className="l-switches" aria-label="O que você liga e desliga">
        {SWITCHES.map((s, i) => (
          <div key={s.id} className="l-band" data-on={switches[i]} data-field={i % 2 ? "accent" : "paper"}>
            <div>
              <p className="l-band-sentence">{s.sentence}</p>
              <p className="l-band-consequence">{switches[i] ? s.consequence : "Desligado."}</p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={switches[i]}
              aria-label={s.sentence}
              className="switch"
              data-ui
              onClick={() => setSwitches((xs) => xs.map((x, j) => (j === i ? !x : x)))}
            />
          </div>
        ))}
      </section>

      {/* ---------- how it works: call and response ---------- */}
      <section className="l-flow" id="como-funciona" aria-labelledby="flow-h">
        <h2 id="flow-h" data-reveal>Do arquivo à decisão</h2>

        <div className="l-step" data-reveal>
          <p className="l-step-say">Primeiro, o documento chega.</p>
          <div className="l-call" data-ui>
            <div className="ui-row"><span>cnh-maria.jpg</span><span className="muted num">94 KB</span><span className="mark" data-tone="accent">Recebido, em análise</span></div>
          </div>
          <div className="l-response" data-ui>
            <p className="ui-title">Carteira Nacional de Habilitação (CNH)</p>
            <p className="muted">Classificado por regras · Emissor: DETRAN/SP</p>
            <p><span className="mark" data-tone="accent">Dentro da validade até 04/04/2032</span></p>
          </div>
        </div>

        <div className="l-step" data-reveal>
          <p className="l-step-say">Depois, cada valor mostra onde foi lido.</p>
          <div className="l-call" data-ui>
            {CNH_ROWS.filter(([k]) => CNH[k]).map(([k, label]) => (
              <button key={k} className="ui-field" data-active={lit === k} onMouseEnter={() => setLit(k)} onFocus={() => setLit(k)} onClick={() => setLit(k)}>
                <span className="muted">{label}</span>
                <span className="num strong">{CNH[k].value.match(/^\d{4}-\d{2}-\d{2}$/) ? CNH[k].value.split("-").reverse().join("/") : CNH[k].value}</span>
                <span className="muted num">{Math.round(CNH[k].conf * 100)}%</span>
              </button>
            ))}
          </div>
          <div className="l-response l-doc" data-ui>
            <img src="landing/cnh.jpg" width={1700} height={1100} loading="lazy" alt="CNH sintética de teste usada para demonstrar a leitura" />
            {box && (
              <span className="l-lit" style={{ left: `${box[0] * 100 - 0.6}%`, top: `${box[1] * 100 - 0.9}%`, width: `${(box[2] - box[0]) * 100 + 1.2}%`, height: `${(box[3] - box[1]) * 100 + 1.8}%` }} />
            )}
          </div>
        </div>

        <div className="l-step" data-reveal>
          <p className="l-step-say">Por fim, a equipe decide.</p>
          <div className="l-call" data-ui>
            <div className="ui-finding">
              <span className="mark" data-tone="danger">Alto</span>
              <span className="strong">Emitido há 160 dias (limite 90)</span>
              <span className="muted">Comprovante de endereço · regra</span>
            </div>
          </div>
          <div className="l-response l-wide" data-ui>
            <div className="ui-slip">
              <p className="strong">Ficha de conferência</p>
              <div className="ui-slip-row"><span>Documento de identidade com foto</span><span className="mark" data-tone="accent">Recebido e conferido</span></div>
              <div className="ui-slip-row"><span>Comprovante de endereço</span><span className="mark" data-tone="danger">Emitido há tempo demais</span></div>
              <div className="ui-slip-row"><span>CPF legível em um documento</span><span className="mark num" data-tone="accent">938.570.839-21</span></div>
            </div>
            <div className="ui-actions">
              <span className="ui-btn">Escalar</span>
              <span className="ui-btn ui-btn-on">Solicitar documentos</span>
              <span className="ui-btn ui-btn-off">Aprovar</span>
            </div>
          </div>
        </div>

        <div className="l-papers" data-reveal>
          <img src="landing/rg.jpg" width={1700} height={1100} loading="lazy" alt="RG sintético de teste" />
          <img src="landing/comprovante.jpg" width={1700} height={1100} loading="lazy" alt="Conta de energia sintética de teste" />
          <img src="landing/cartao-cnpj.jpg" width={1240} height={875} loading="lazy" alt="Comprovante de CNPJ sintético de teste" />
          <p className="l-papers-note">Documentos sintéticos, gerados para testes. Os da sua equipe ficam criptografados no servidor.</p>
        </div>
      </section>

      {/* ---------- one full-bleed photograph between type sections ---------- */}
      <div className="l-photo" ref={photo}>
        <img src="landing/fichario-arquivo.jpg" width={1920} height={1280} loading="lazy"
          alt="Gaveta aberta de um fichário de catálogo no Arquivo Nacional da Finlândia, com fichas de papel" />
        <p className="l-photo-credit">Fichário do Arquivo Nacional da Finlândia. Foto de Fuje23, CC BY-SA 4.0.</p>
      </div>

      {/* ---------- proof: the record as a table ---------- */}
      <section className="l-record" aria-labelledby="record-h">
        <h2 id="record-h" data-reveal>
          <span>Tudo fica</span>
          <span className="l-indent">registrado</span>
        </h2>
        <table className="l-table" data-reveal>
          <thead className="visually-hidden">
            <tr><th>Dia</th><th>Hora</th><th>O que aconteceu</th><th>Detalhe</th><th>Quem</th><th>Cadastro</th></tr>
          </thead>
          <tbody>
            {HISTORY.flatMap((g) =>
              g.rows.map((r, i) => (
                <tr key={g.day + i}>
                  <td className="l-day">{i === 0 ? g.day : ""}</td>
                  <td className="num">{r[0]}</td>
                  <td className="strong">{r[1]}</td>
                  <td>{r[2]}</td>
                  <td>{r[3]}</td>
                  <td className="num l-right">{r[4]}</td>
                </tr>
              )),
            )}
          </tbody>
        </table>
        <p className="l-record-note" data-reveal>Cada linha guarda o resumo criptográfico da anterior. Um clique em “Conferir integridade” mostra se alguma foi alterada.</p>
      </section>

      {/* ---------- close: the way in is the display line ---------- */}
      <footer className="l-close">
        <div className="l-close-top">
          <div>
            <Logo size={18} />
            <p>Uso interno da equipe de cadastro.</p>
            {!servedByServer && <p className="num">Servidor: {host}</p>}
          </div>
          <a href="#/" onClick={(e) => { e.preventDefault(); window.scrollTo({ top: 0, behavior: "smooth" }); }}>Voltar ao topo</a>
        </div>
        <Link to="/entrar" className="l-close-line">Entrar</Link>
        <div className="l-close-meta">
          <span>Senha esquecida? Fale com o administrador.</span>
          <span>Fotos: Fuje23 e Ruth Crivamo (LabDoc-UFRRJ), CC BY-SA 4.0, via Wikimedia Commons.</span>
          <span>FinTrust, 2026</span>
        </div>
      </footer>
    </div>
  );
}
