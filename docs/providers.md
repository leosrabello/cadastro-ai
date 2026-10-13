# OCR and AI providers

## OCR: what was considered

| Option | Accuracy on Brazilian IDs and bills | Privacy | Cost | Effort |
| --- | --- | --- | --- | --- |
| **Tesseract 5 (`por`), self-hosted** | Good on clean scans and digital PDFs; weaker on photos taken with phones, glare, strong skew | Nothing leaves the server | No per-page charge; CPU only | Low; already integrated |
| Azure AI Document Intelligence (Read / ID document) | Strong on photos and handwriting; returns word confidences and polygons | Processing in Brazil South available; Microsoft DPA | Per-page charge (see costs.md) | Low; adapter written |
| AWS Textract | Strong; no Brazil-specific ID model | São Paulo region available | Per-page charge | Medium |
| Google Document AI | Strong; specialised processors | São Paulo region available | Per-page charge, higher for specialised processors | Medium |
| PaddleOCR / docTR self-hosted | Can beat Tesseract on photos; heavier models | Local | GPU recommended | Medium–high to operate |

**Initial choice: Tesseract, self-hosted.** It needs no contract, sends nothing outside, costs
nothing per page, and the synthetic evaluation shows it reads typical scans and digital PDFs well.
Digital PDFs (CNPJ cards, bills downloaded from the issuer) are read from their embedded text, and
OCR is used to check that text against what is printed.

**When to switch to Azure:** if the field-level accuracy measured on a real, labelled sample of the
company's documents (docs/evaluation.md) falls short, especially for phone photos. The switch is
one environment variable; nothing else changes. One paid OCR service is enough; running several in
parallel is not justified.

Region-level evidence (word boxes) is kept for every provider, so the review screen can show where
each value was read.

## AI-assisted analysis

The AI is not an agent. It performs one bounded task per document through
`pipeline/ai/anthropic_provider.py`:

- Input: the OCR text wrapped as quoted, HTML-escaped data inside `<document_text>`, the allowed
  document types, the fields to read, the rule-based reading, and (only if allowed) up to three
  page images.
- Output: a JSON object constrained by a JSON schema at decoding time **and** validated again with
  Pydantic (`extra="forbid"`, enumerations, length limits). Malformed output is retried once, then
  the AI result is discarded and recorded as not run. Refusals are failures, not results.
- No tools, no network access, no ability to change state. The pipeline decides what to do with
  the output: AI fields fill only gaps left by the rules (marked "lido pela IA"), disagreements
  become findings, observations become findings whose severity is capped by the model's own stated
  certainty, and "certainty" is labelled as not a calibrated probability.
- The AI never approves, rejects or changes a status.

Model: `claude-opus-5-5` by default (`AI_MODEL`), effort `medium`, server-side refusal fallback
enabled. A cheaper model can be configured; measure it on the labelled set first.

Without a key, everything else works and the documents show "Análise por IA desligada".
