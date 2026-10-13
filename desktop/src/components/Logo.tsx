// The CadastroAI logo: the "conferido" stamp and the wordmark, set in the display face.

export function Mark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 22 22" aria-hidden="true" className="logo-mark">
      <rect width="22" height="22" rx="4" fill="var(--accent)" />
      <path d="M6 11.5l3.3 3.3L16 8" fill="none" stroke="var(--accent-ink)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Logo({ size = 22, label = true }: { size?: number; label?: boolean }) {
  return (
    <span className="logo" style={{ fontSize: size * 0.95 }}>
      <Mark size={size} />
      {label && <span className="logo-word">CadastroAI</span>}
    </span>
  );
}
