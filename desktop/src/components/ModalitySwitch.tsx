import type { Modality, Scope } from "../api/types";
import { MODALITY_LABEL } from "../lib/modality";

/** Normal on the left, One7 on the right; the active side is lit. A switch, because there are exactly two lines of business. */
export function ModalitySwitch({ value, onChange }: { value: Modality; onChange: (m: Modality) => void }) {
  const one7 = value === "one7";
  return (
    <div className="modality-switch" data-value={value}>
      <button type="button" className="modality-side" aria-pressed={!one7} onClick={() => onChange("normal")}>{MODALITY_LABEL.normal}</button>
      <button
        type="button"
        role="switch"
        aria-checked={one7}
        aria-label={`Modalidade: ${MODALITY_LABEL[value]}. Alternar para ${one7 ? MODALITY_LABEL.normal : MODALITY_LABEL.one7}`}
        className="switch modality-track"
        data-ui
        onClick={() => onChange(one7 ? "normal" : "one7")}
      />
      <button type="button" className="modality-side" aria-pressed={one7} onClick={() => onChange("one7")}>{MODALITY_LABEL.one7}</button>
    </div>
  );
}

/** For reports, where the consolidated view of both modalities is also a choice. */
export function ScopePicker({ value, onChange }: { value: Scope; onChange: (s: Scope) => void }) {
  const opts: { key: Scope; label: string }[] = [
    { key: "normal", label: "Normal" },
    { key: "one7", label: "One7" },
    { key: "all", label: "Consolidado" },
  ];
  return (
    <div className="segmented" role="group" aria-label="Modalidade">
      {opts.map((o) => (
        <button key={o.key} type="button" aria-pressed={value === o.key} onClick={() => onChange(o.key)}>{o.label}</button>
      ))}
    </div>
  );
}

export function ModalityTag({ modality }: { modality: Modality }) {
  return <span className="modality-tag" data-modality={modality}>{MODALITY_LABEL[modality]}</span>;
}
