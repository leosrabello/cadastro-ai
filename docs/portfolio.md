# Carteira, modalidades, assinaturas e relatórios

This part brings the team's previous dashboard (a standalone HTML page that kept its data in the
browser and exported `backup_cadastros_*.json`) into CadastroAI. Its data now lives in the same
PostgreSQL database as the registrations, with the same roles and audit trail.

## Modalities: Normal and One7

- `Modality` (`normal`, `one7`) is a column on **registrations** and on **portfolio clients**.
- Creating a registration requires choosing it: the API has no default (`422` without it), and the
  dialog has no preselection. A registration may link to a portfolio client; the API refuses a
  client from the other modality.
- **Existing registrations:** migration `0002` adds the column with `server_default 'normal'`.
  Every registration before this change was Normal (One7 was not handled by CadastroAI). Any of
  them can be changed under *Modalidade e cliente da carteira* on the registration page, and the
  change is audited.
- **Painel:** a switch (Normal / One7) filters every work tile, the review queue link and the
  portfolio section. The inbox tile is labeled as covering both modalities, because a document
  has no modality until it has a registration.
- **Other screens:** the review queue and the registration list have a modality filter. Carteira
  follows the switch. Relatórios has a third option, *Consolidado*, which is stated explicitly on
  screen and on the image.
- The chosen modality is remembered per computer (`localStorage`) and shared by the screens.

## Commercial and economic group of a registration

- **Comercial responsável** is chosen when the registration is created (active commercials only)
  and can be changed under *Modalidade, comercial e cliente da carteira*. The new-registration
  dialog no longer lists portfolio clients; linking a client stays on the registration page.
  Without its own commercial, a registration shows its portfolio client's.
- **Grupo econômico** (companies and people under common control; migration `0006`,
  `api/groups.py`). The registration page suggests members from what the documents show: another
  registration with the same CNPJ root (head office and branches), or a partner, administrator or
  signatory in common (names of two words or more). The analyst decides; nothing is grouped
  automatically. The registration list has *Agrupar por grupo econômico*, which orders the
  members of each group together and adds a filter by group. Deleting a group only unlinks its
  registrations.

## Data: why the database, with JSON as the input format

| Option | Verdict |
| --- | --- |
| Read the JSON on every use | No concurrency, no audit, no integrity rules, no growth path; the old dashboard's problem |
| Database only, typed in by hand | Loses 105 clients and 25 signature records already kept by the team |
| **JSON imported into PostgreSQL** | Chosen. The database already exists, with roles, audit and backups. The JSON is a one-off (or occasional) input; PostgreSQL is the source of truth |

**Tables** (migration `0002_modality_and_portfolio.py`):
- `commercials`: unique by an accent- and case-insensitive key, so `Gabriel` and `gabriel` are one commercial.
  Two names of the same person are merged in Carteira, Comerciais, *Juntar com…* (supervisors):
  clients and contracts move, and the merged name is kept as an alias (migration `0003`), so a
  later import of the old backup resolves it to the surviving commercial instead of recreating it.
- `portfolio_clients`: modality, status, business dates, flags, milestones, follow-ups, status
  history, the old dashboard's log, and `external_id`.
- `signature_trackings` with `signature_contracts`: one SEC and one FIDC row per company.
- `data_imports`: who imported which file (sha256), when, and with what result.

**Import rules** (`backend/app/portfolio/importer.py`):

- **Two steps.** A preview validates everything and writes nothing. The import repeats the
  validation, checks the file is the one previewed (sha256), and writes in one transaction.
- **Matching.** Records are matched by the id they had in the old dashboard (`external_id`). A
  reimport of the same file gives 0 new and N unchanged.
- **Local edits win.** A record edited in CadastroAI after its last import is kept, and reported
  as *mantido no sistema*.
- **Rejected** (with the reason shown):
  - no id, or an id repeated in the file;
  - unknown status;
  - an invalid date;
  - a signature date before the emission date;
  - an id already used by the other modality.
- **Warnings** (imported anyway):
  - Same name as another record in the file: kept, because the real file has two different
    folders named PIERINO GOTTI.
  - Missing entry date: imported as incomplete and left out of the time averages. MAXBELT
    (One7) has no date because it was not yet registered at ONE7.
  - A signature record without a client link: linked when exactly one client has the same name.
  - Two signature records pointing at the same client.
  - Attachments embedded in the file: not imported.
- **Statuses.** Statuses created or renamed in the old dashboard (`customStatuses`,
  `statusLabels`) join the Normal catalog, which is the `client_statuses` setting.

**Result with the real file** (`backup_cadastros_2026-10-14.json`): 105 clients (100 Normal, 5 One7),
25 signature records, 16 commercials, 4 custom statuses, 0 rejected, 9 warnings. A reimport gives
0 new, 105 unchanged.

The real file is not in the repository (client data); tests use an invented file with the same structure.

## Indicators (`backend/app/portfolio/metrics.py`)

The rules of the old dashboard's *Relatórios* tab, computed from stored data on each request:

| Indicator | Rule |
| --- | --- |
| Situação | concluído = a status with outcome *approved* (Apto a Operar); negado = outcome *denied* (Negada); atrasado = same status for `sla_days` (7) or more; em andamento = the rest |
| One7 outcome | Apto a Operar, or the ONE7 committee result (aprovado / negado) |
| Taxa de aprovação | aptos / (aptos + negados) |
| Tempo até apto | entry date to the first time in an approved status (status history) |
| Tempo de assinatura | contract emission to signature, per contract (SEC and FIDC) in Assinaturas; a client's own dates are used only when it has no contracts there |
| Comercial destaque | the commercial with most clients |
| By commercial | clients, share, aptos, negados, em andamento, atrasados, approval rate, average time to apto |
| Lists | maior tempo parado (top 5), acima do prazo, saída de risco, limite vencido, entradas por mês |

`sla_days` and the status catalog (labels, which status means approved or denied, which one opens
the signature tracking) are settings (`portfolio`, `client_statuses`), validated by the API.

## Assinaturas (signature check on the portal)

- **What carries over.** The old area is kept: the average-time cards, both contracts per company
  with emission and signature dates, days, follow-ups, and automatic creation when a client
  reaches *Aguardando Assinatura* (the record stays when the client moves on).
- **Status per contract:** não emitido, aguardando (with the days open, in red past the SLA) or
  assinado (with the days it took). Per company: aguardando, parcial, assinado or sem emissão.
- **Cards:**
  - average time overall, plus SEC and FIDC separately;
  - contracts in process, with their average and oldest open time;
  - contracts signed and contracts not yet issued;
  - follow-ups.
  All of them show their basis (how many contracts).
- **Filters:** company or commercial search, situation, modality and commercial. Pending
  companies come first, oldest emission on top.
- **Validation (API and screen):** no signature without emission, no signature before emission,
  no signature in the future.
- **Limitation:** the signing portal has no integration. CadastroAI never queries it or acts on
  it. The dates are what the analyst checks on the portal and types in; every indicator comes
  from those dates. This is stated on the screen.

## Reports

- *Relatórios* shows the cards, the insight blocks, the commercials table and the client table
  with the same columns and filters as the old dashboard: client, commercial, status, situação,
  entry and committee periods.
- *Gerar imagem do relatório* renders the same numbers on the "printed annual" sheet used by the
  per-registration analysis report. It is exported to PNG by the same shared function
  (`desktop/src/lib/sheet.ts`), so there is no second report engine.

## Test data removed

- **Before the cleanup:** `backups/cadastro-antes-limpeza-2026-10-14.dump` (pg_dump) and
  `backups/documentos-antes-limpeza-2026-10-14.tar.gz` (encrypted document store), in the
  project folder, git-ignored.
- **Tool:** `backend/scripts/remove_test_data.py`. It shows a preview by default and only deletes
  with `--apply`. It finds automatically:
  - registrations with a document carrying the synthetic generator's banner;
  - registrations made by the bootstrap admin with a demo-seed name;
  - synthetic documents in the inbox.

  Registrations created by hand while testing are removed only when named with `--codes`.
- **Removed on 2026-10-14:**
  - nine seed registrations (CAD-2026-000001 to 000008 and 000010), each with synthetic
    documents;
  - four manual tests: 000009 FINTRUST INVESTIMENTOS and 000011 JOHN (no documents), and
    000012 and 000013 (a developer's own CNH, used to test the OCR);
  - 32 documents with their stored files, and one synthetic inbox file;
  - the demo accounts (ana.analista, sergio.supervisor, aud.auditoria), which were deactivated,
    not deleted.
- **What stayed:** audit events (append-only; the chain still verifies), settings, and the real
  accounts.
- **Seed scripts:** `seed_demo.py` and `seed_company_demo.py` were deleted, and a test asserts
  they stay gone. Startup creates only settings and the first administrator.
