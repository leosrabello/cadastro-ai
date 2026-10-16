# Known limitations and future improvements

## Not verified in this environment

- **Live AI calls.** No Anthropic key was available. The provider is implemented against the
  documented SDK and tested with recorded and fake responses (valid, malformed, extra keys,
  refusal). The first real calls should be reviewed on a handful of synthetic documents.
- **Live Azure OCR.** Adapter tested with recorded response shapes only.
- **Windows installer.** The workflow builds it on a Windows runner; it was not built or installed
  from this Mac. The macOS app bundle was built here.
- **Real documents.** All measurements use synthetic documents (docs/evaluation.md).

## Functional limits

- **Word and Excel** are converted to PDF with LibreOffice at intake. Layout follows LibreOffice's
  rendering; very wide spreadsheets span several pages. Files with macros or a password are refused.
- **Administrators and signing** in the articles of association are read by keyword rules and, when
  AI is on, by the AI from the clause. Unusual drafting (powers by amount, attorneys in fact) needs a
  look at the clause, which is quoted with the value.

- **Signing portal.** No integration: Assinaturas records the dates the analyst checks on the
  portal; nothing is queried or automated there.
- **Status catalog and SLA** are settings (`client_statuses`, `portfolio`) editable through the
  settings API; there is no screen for them yet.
- **Commercials** can be renamed, deactivated and merged; there is no un-merge (the audit event
  records what moved).

- Field extraction is rule-based and tuned on the layouts in `tests/synthetic.py`. Real RG layouts
  vary by state and era; new labels may need adding to `pipeline/extract.py` (or AI enabled to fill
  gaps). Phone photos with perspective distortion are not rectified.
- Small rotations (up to about 4°) are corrected before OCR; larger rotations and upside-down pages
  are not.
- Integrity signals are indications. ELA produces false positives (stamps, photos, reflections).
  "Reused image with swapped data" is detected only when identity data also matches; a photo pasted
  onto another person's document is not detected without face or photo-region comparison, which is
  deliberately not implemented (biometrics would be sensitive data under LGPD).
- No authoritative verification sources are queried (Receita Federal CPF/CNPJ status, Serpro
  DataValid, Detran). The validity rules check dates, not authenticity. Integrating an authorised
  source is the most valuable next step for fraud prevention and needs a contract.
- Near-duplicate search compares against all documents with a perceptual hash; above roughly 100,000
  documents it should use an index (hash prefix buckets) instead of a scan.
- One requirement profile per registration kind (PF, PJ). Profiles per product or risk level would
  extend `requirement_profiles`.
- Settings for document types edit validity rules and notes; adding a brand-new document type with
  its own extraction rules needs code.
- No SSO yet. Authentication is local with strong hashing; Entra ID (OIDC) is the natural next step.
- No MFA in the local authentication.
- Retention runs daily for rejected and abandoned registrations; approved registrations need an
  end-of-relationship signal from the core system before they can be purged automatically.
- The desktop app has no offline mode, by design (central system of record).
- Interface language is Brazilian Portuguese only.

## Future improvements, in suggested order

1. Measure on a real labelled sample; choose OCR provider and AI use from the numbers.
2. Entra ID single sign-on with MFA.
3. Authorised verification sources (CPF/CNPJ situation, DataValid).
4. Outlook intake (integrations-roadmap.md).
5. Perspective correction for phone photos; more RG layouts.
6. Per-product requirement profiles and reviewer workload assignment.
7. WhatsApp intake.
