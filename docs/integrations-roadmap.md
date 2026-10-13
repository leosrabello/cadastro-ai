# Integrations roadmap: Outlook and WhatsApp

Not implemented in this version, by design. The intake architecture is ready for them: every
channel ends in `ingestion.service.ingest(data, filename, source, source_ref, registration)`, so the
pipeline, review and audit need no change. A new channel only has to fetch attachments, decide the
registration (or leave it for the inbox), and call that function.

## Outlook (shared mailbox, e.g. cadastro@empresa.com.br)

- Microsoft Graph with an Entra ID app registration, **application permission `Mail.Read` restricted
  to the one mailbox** with an Exchange application access policy (not tenant-wide).
- A service like the folder watcher: Graph delta query or change notifications (webhook plus
  periodic delta as a safety net), one advisory lock, idempotency on the message id plus attachment
  hash.
- `source="email"`, `source_ref="<message-id>/<attachment-name>"`.
- Association: registration code in the subject, sender matched to a registration's contact e-mail
  (a new reference field), otherwise inbox.
- Mark processed messages with a category instead of moving them, so the team's mailbox habits are
  undisturbed.
- Attachments go through the same screening; inline images and signatures are skipped by size and
  content-ID rules.

## WhatsApp

- Only the official WhatsApp Business Platform (Cloud API) through a Business Solution Provider or
  Meta directly; no unofficial clients.
- Webhook endpoint on the API (signature verified with the app secret) receives media ids; a worker
  downloads media with the system-user token and calls `ingest()` with `source="whatsapp"`,
  `source_ref="<wa-message-id>"`.
- Association by the customer's phone number (a reference field), or by a code sent in the chat.
- Opt-in and a privacy notice for the channel; Meta as an additional processor in the RIPD.
- Customers often send photos of documents: this is where Azure Document Intelligence (better on
  photos) is most likely to pay for itself. Measure first.

## Order

Outlook first (lower regulatory and operational effort, likely the larger current channel), then
WhatsApp once the photo-quality question is measured.
