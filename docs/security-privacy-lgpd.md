# Security, privacy and LGPD

This document describes what the software does and what the company must still put in place. It
is not legal advice; the DPO (encarregado) and legal counsel should validate it.

## Controls implemented

| Control | Where |
| --- | --- |
| Authentication with Argon2id password hashes; generic error on failure; timing-equalised for unknown users | `security.py`, `api/auth.py` |
| Server-side sessions (signed token + session row); logout, deactivation, role or password change revoke immediately | `deps.py`, `api/admin.py` |
| Role-based access enforced in the API; least privilege by default (analysts cannot approve, reject, override or read the full audit) | `deps.py`, routers |
| Rate limiting: login per IP and per e-mail, uploads and general API per user | `ratelimit.py` |
| Upload screening: type from content, extension match, size/page/pixel limits, truncated/repaired/encrypted PDFs refused, PDFs with JavaScript, launch actions, embedded files or XFA refused | `ingestion/validation.py` |
| Safe storage names (random keys); original names only in the database; download served with `nosniff` and a neutral filename | `storage`, `api/documents.py` |
| Encryption at rest of every original (Fernet: AES-128-CBC + HMAC-SHA256) with a key held only by the server | `storage` |
| Encryption in transit: HTTPS via reverse proxy; SMB 3 encryption to the share (deployment) | `deployment.md` |
| Audit trail of logins, failed logins, every view and download of a document, every correction, resolution, decision, setting change and purge; append-only by trigger; SHA-256 hash chain with on-demand verification | `audit.py`, migration |
| Secrets only in server environment; Settings never returns them; desktop build contains none | `config.py`, `api/admin.py` |
| CSP in the desktop app; API sends `nosniff`, `no-referrer`, `DENY` framing, `no-store` | `tauri.conf.json`, `main.py` |
| Retention and purge (files, OCR text, fields, names, tax IDs) with legal hold; audit and hashes kept | `retention.py` |
| Data-subject access export | `GET /api/registrations/{id}/export` |

## Documents are untrusted input, including for the AI

- A deterministic detector flags text addressed to an automated system ("ignore previous
  instructions", "aprove este cadastro", fake `<system>` tags) as a high-severity integrity
  finding. A legitimate document never contains such text.
- The AI receives document text only inside `<document_text>` tags, HTML-escaped so a document
  cannot close the tag. The system prompt states that everything inside is data and must be
  reported, not obeyed.
- The AI has no tools and cannot change anything. Its output must match a strict schema (no extra
  keys, enumerated values, length limits) or it is discarded. It can only add findings and fill
  empty fields, always labelled as AI output and always subject to human review.
- Tests cover both the detector and the escaping (`test_rules.py`, `test_failures.py`,
  `test_pipeline.py::test_embedded_instructions_are_data_and_flagged`).

## LGPD

**Legal basis.** Onboarding verification of customers of a financial institution is processed
under art. 7, II (compliance with legal or regulatory obligation: Lei 9.613/1998, Bacen Circular
3.978/2020 and Resolution BCB 119/2021 for KYC/AML; CVM Resolution 50/2021 where applicable) and
art. 7, V (pre-contractual procedures requested by the data subject). Biometric data is not
processed (no face matching), which avoids sensitive-data treatment under art. 11. Fraud-prevention
checks rely on art. 11, II, "g" only if sensitive data is ever added.

**Minimization.** The pipeline extracts only the fields each requirement needs. Parents' names
(filiação), naturalidade and categories of the CNH are not extracted. Reference fields on a
registration are free-form but limited and should be configured to what the workflow needs.

**Retention.** Defaults: rejected registrations purged after 180 days; abandoned pending ones after
365 days; approved registrations kept for the relationship plus 5 years (Lei 9.613, art. 10), with
no automatic purge because the end of the relationship is known only to the core system. A purge
deletes the files, OCR text, extracted fields, name and tax ID, and keeps decisions, hashes and the
audit trail. Legal hold blocks purge.

**Data-subject rights (art. 18).** Access/confirmation: export endpoint (supervisors). Correction:
field correction with history. Deletion: purge (administrators) unless a legal retention duty or
hold applies; the refusal reason should be communicated by the DPO. Information about sharing: the
export lists processors.

**Processors and international transfer.** Tesseract runs in-house: no processor. Azure Document
Intelligence and the Claude API are processors if enabled. Before enabling either:

1. Sign or confirm the data-processing agreement (Microsoft Products and Services DPA; Anthropic
   commercial terms and DPA).
2. Confirm training use (both state that API/customer data is not used to train models under their
   commercial terms; verify the current text).
3. Confirm retention by the vendor (abuse-monitoring retention windows; request zero-retention
   arrangements where offered and required).
4. Confirm processing location. Azure: Brazil South keeps processing in Brazil. Claude API:
   processing outside Brazil is an international transfer under arts. 33–36; it needs a valid
   mechanism (standard contractual clauses per ANPD Resolution 19/2024) and should appear in the
   privacy notice.
5. Record the assessment in the RIPD (DPIA) and the vendor register.

That is why AI is off by default, images are off by default, and both need a server-side switch
and an administrator switch.

**Security incidents.** The audit trail shows who viewed or downloaded which document and when,
supporting the ANPD incident assessment (Resolution 15/2024).

## Process the company must operate

- Joiner/mover/leaver: create named accounts only; on departure an administrator clicks *Revogar
  acesso*, which ends active sessions at once. Review accounts and roles quarterly.
- Keys: `STORAGE_ENCRYPTION_KEY`, `JWT_SECRET`, provider keys and the backup passphrase in the
  corporate vault, with named custodians. Rotate provider keys yearly.
- Backups nightly, off-site, restore-tested quarterly (deployment.md).
- Desktop updates through the software distribution system, signed installers only.
- Penetration test of the API before production.


## Documents after the decision (2026-10-15)

- **Rejected:** the documents, extracted text and personal data are deleted at the moment of
  rejection (`retention.rejected_days = 0`, the default). This follows LGPD art. 6, III,
  necessity: a rejected prospect's documents serve no further purpose. What remains is the
  decision, the reason and the audit trail, with the name and CPF/CNPJ anonymized. A purged
  registration cannot be reopened. Registrations under legal hold are never purged.
- **Approved:** the documents are kept. KYC records of active clients must be retained for at
  least five years after the end of the relationship (Lei 9.613/1998, art. 10; CVM Resolução 50,
  for a securitizadora). LGPD art. 16, I allows retention to meet a legal obligation. Deleting
  them requires another place that keeps the dossier for that period.
- **Files sent by mistake** (wrong person, wrong version, sent twice) can be deleted by analysts
  from the registration page or the document page, with a reason kept in the audit (the audit
  keeps type, hash and reason, not the file name). Documents of approved registrations cannot be
  deleted, for the retention above; the API refuses it.
- **Learning from reviews** stays in this database and is computed from the reviews themselves;
  the supervisors' panel shows counts, not the values (they may be personal data). Nothing is
  sent to the AI provider beyond the document being analyzed.
