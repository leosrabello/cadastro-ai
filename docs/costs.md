# Cost estimate

All prices are list prices in US dollars as understood in October 2026 and must be checked against
the vendors' current price pages and the company's contracts before budgeting. Brazilian cloud
regions usually cost 30–50% more than US regions. Taxes (IOF on foreign services, ISS/PIS/COFINS on
import of services) are not included.

## Assumptions

- 2.2 documents per registration, 1.4 pages per document.
- OCR on every page; AI (if enabled) once per document.
- AI per document, text only: about 3,000 input tokens (instructions, schema, document text) and
  1,500–2,500 output tokens (including the model's reasoning at medium effort). With up to three
  page images, about 3,000–5,000 more input tokens.
- `claude-opus-5-5` at US$4 per million input tokens and US$20 per million output tokens.
- Azure Document Intelligence *Read* at about US$1.50 per 1,000 pages (first price tier).

## Fixed infrastructure (per month)

| Option | What | Estimate |
| --- | --- | --- |
| Existing corporate server | 1 VM (4 vCPU, 16 GB), the company's PostgreSQL, file share, backup storage | Marginal: internal hosting cost, typically small |
| Private cloud, Brazil region | VM 4 vCPU/16 GB (US$180–280), managed PostgreSQL small (US$120–220), 200 GB encrypted storage + backups (US$20–40), egress negligible | US$320–540 |

Plus, either way: code-signing certificate (US$300–600 per year) and staff time for operations.

## Variable (per month)

| Registrations / month | Documents | Pages | Tesseract | Azure Read | AI, text only | AI, with images |
| --- | --- | --- | --- | --- | --- | --- |
| 500 | 1,100 | 1,540 | US$0 | ≈US$2 | ≈US$45–65 | ≈US$60–90 |
| 2,000 | 4,400 | 6,160 | US$0 | ≈US$9 | ≈US$180–260 | ≈US$240–360 |
| 10,000 | 22,000 | 30,800 | US$0 (one more worker VM above ≈15,000 pages/day) | ≈US$46 | ≈US$900–1,300 | ≈US$1,200–1,800 |

Per document with AI: about US$0.04–0.06 text only, US$0.055–0.08 with images. Per completed
registration (2.2 documents): about US$0.09–0.13 text only.

## What dominates

- Without AI, the cost is the fixed infrastructure. Tesseract has no per-page charge.
- With AI, the model is the largest variable cost by far. Levers, in order: keep images off unless
  they measurably help; send AI only the document types where it adds value; measure a cheaper model
  (for example `claude-sonnet-5-5` at US$2/US$10 per million tokens, or `claude-haiku-5-5` at
  US$0.10/US$0.50) against the labelled set before switching; batch non-urgent analysis.
- The real cost of every analysed document is recorded (`processing_jobs.metrics.ai_cost_usd`) and
  summarised in *Configurações > Sistema*, so the estimate can be replaced by actuals within a week
  of use.
