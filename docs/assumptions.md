# Assumptions

Decisions taken where the brief left a gap. Each can be changed; most are settings.

| Topic | Assumption |
| --- | --- |
| Location | A new repository next to the existing projects; the debenture platform in SistemaInvestimentos is unrelated and was not reused |
| Customers | Brazilian individuals (PF) and companies (PJ) |
| Interface language | Brazilian Portuguese; code and technical documentation in English |
| PF requirements | Photo ID (RG, CIN or CNH) and proof of address; CPF and birth date readable on the ID |
| PJ requirements | CNPJ card, consolidated articles of association, ID of the legal representative, company address (the CNPJ card may serve) |
| Old RG without expiry | Accepted up to 10 years from issue; older goes to review (medium severity) |
| CNH | Expiry date applies with no grace period for identification purposes |
| Proof of address | Issued within 90 days; held by someone else is low severity because it is common |
| CNPJ card | Issued within 30 days and status ATIVA |
| Articles of association | No expiry; reviewer confirms it is the latest consolidation |
| Who approves | Supervisors and administrators; analysts prepare, correct, request documents and escalate |
| Approval with open items | Blocked unless a supervisor overrides with a written justification of 20+ characters |
| Retention | Rejected 180 days, abandoned pending 365 days, approved kept (end of relationship + 5 years, handled by the core system) |
| OCR | Tesseract self-hosted by default |
| AI | Off by default; Claude when configured; text only unless images are explicitly allowed twice |
| Watcher association | Registration code `CAD-YYYY-NNNNNN` in the file name or the first subfolder; otherwise a CPF/CNPJ in the file name; otherwise the inbox |
| Registration code format | `CAD-<year>-<6 digits>`, sequential per year |
| Reference date for validity | The day of analysis; re-analysis uses the new date |
| Desktop updates | Through the company's software distribution system, not in-app |
