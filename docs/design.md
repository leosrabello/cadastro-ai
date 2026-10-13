# Design: how the Taste Skill was used

The installed skill is `~/.agents/skills/design-taste-frontend` (tasteskill v2). Its own
description says it is written for public web pages and "not for dashboards or app screens". This
project used every part of it that transfers to a product interface, adapted the rest, and set
aside the parts that only make sense for a marketing page. Each point below is visible in the code.

## The draw

`node scripts/draw.mjs --sector finance --tone quiet --have product-ui --options 3` dealt three
directions (*The dark room*, *The product performs*, *Type and nothing else*). *The product
performs* was chosen because its idea is that software is most convincing doing its job: in an
internal tool, the interface is the material. The full sheet (`.taste-skill/direction.json`, seed
1203172118) dealt:

| Slot | Dealt | Where it lives |
| --- | --- | --- |
| Type | Bricolage Grotesque, one family | `styles.css`, self-hosted via `@fontsource-variable` so the app works offline |
| Palette | Soot and lime: `#0f0f0f` ground, `#1a1a1a` surface, white ink, `#8f8f8f` muted, `#dafa9c` accent, white field | `styles.css` tokens |
| Hero: Column on one line | One alignment 27% from the left, small mark, two-line headline, one sentence, one action, an interface fragment peeking from the bottom edge, right half empty | Sign-in screen (`Login.tsx`, `login.css`) |
| Features: Sentences with switches | Full-width bands, one plain sentence ending in a real switch; on, the band fills with a field colour and the consequence appears in figures | *Configurações > Processamento* |
| List: Day tabs, banded agenda | Stacked day tabs, the day's items as alternating tone bands with the time in tabular figures | *Histórico* |
| Proof: Large marks on tiles | Filled tiles four across, 8px gaps, large numerals, the first tile double width in the accent carrying the heading | *Painel* |
| Motion: Slow crossfade | The sign-in fragment crossfades between three states of a registration slip (1.6 s, every 5.6 s, paused when hidden, off under reduced motion) | `Login.tsx` |

## The idea

> In this app, **the registration slip that analysts used to staple to every paper file** becomes
> **the one paper-white object in the dark room**.

The checklist on the registration screen (*Ficha de conferência*) is the only white surface in the
app. The mark is a lime "conferido" stamp. The one live thing is in the review workspace: hovering a
field or a piece of evidence lights the exact region of the original document where it was read,
and dims the rest of the page.

## House rules applied

- One ground, one ink, one accent. Lime appears on primary actions and on one recurring meaning:
  approved/conferred. Danger and warning tones were added for severity, an app need the palette did
  not cover; status never relies on colour alone (each has a word).
- Surfaces separated by tone steps; no shadows at rest (dialogs and toasts only); no gradients, no
  glass, no eyebrows, no tiny tracked capitals, no monospace (identifiers use tabular figures), no
  numbered labels, no icon cards.
- Lines only where the rules allow them: tables and form fields. Status bars are 4px filled bars.
- Five type sizes (13, 15, 18, 26, 44 px). The skill's body minimum of 16px was relaxed to 15px for
  dense tables; meta text never goes below 13px.
- One corner radius (4px) and one button shape throughout.
- Motion: staggered entrances per screen part, feedback on every control, transform and opacity
  only, full `prefers-reduced-motion` fallback.

## The gate

`scripts/lint.mjs desktop/src`: first run 24 FAIL (inset shadows used as bars, `transition: all`,
1px field borders, em-dash habit). After fixes: **0 FAIL, 2 WARN**, both defended: zero-padding
that builds an ISO date, and an em dash used as the empty-value marker in data cells.

`scripts/inspect.mjs http://localhost:1420/` on the sign-in screen (the only screen reachable without
a session): headline two lines at all widths, one typeface rendered, three sizes, contrast passes.
Remaining FAILs are rules for marketing pages that were deliberately not followed:

- *few-pictures* (at least four photographs): a sign-in screen for a document-verification tool has
  no honest subject for photographs; stock imagery would be decoration. The interface fragment is
  the picture.
- *still-page* (eight moving elements): six move on load; a sign-in screen does not need more.
- *no-footage*: no clip fits the subject.

The skill's look-and-fix loop was run on screenshots of the working app, and the fixes are in the
code: orphan word in the sign-in sentence, wrapped fragment rows, decision buttons wrapping,
untranslated audit actions and statuses, field colour repeating between switched-on bands.

## Landing page and sign-in (second pass)

Requested: a landing page with a way in, a centred sign-in with a real logo, the name "CadastroAI".

- **Draw:** `draw.mjs --keep palette,type --have product-ui`, three options; chose *Type and nothing
  else* because the name itself is the first screen. Sections dealt and used: *Headline you can
  type* (a live CPF/CNPJ check-digit line, the page's one interactive thing), *Two-ended rows* (the
  validity rules and queue points, the real defaults), *Sentences with switches*, *Call and response*
  (document to decision, with the CNH field regions taken from a real Tesseract run), *Recognition
  as a table* (the history), *Contact as the headline* (a lime field whose display line is "Entrar").
- **Idea:** the "verificado por / visto" box of the paper registry becomes the CPF line you can type
  and the field that lights where it was read.
- **Pictures:** two found in open collections and credited on the page (a Ministério da Agricultura
  drawing with its stamped title block, LabDoc-UFRRJ, CC BY-SA 4.0; a card-catalogue drawer at the
  Finnish National Archives, Fuje23, CC BY-SA 4.0), four synthetic documents rendered by the test
  generator and labelled as such, and interface fragments. No clip fitted the subject.
- **Gate:** lint 0 FAIL. Inspector on the landing: 0 FAIL after three look-and-fix rounds (type sizes
  consolidated to five steps and body text in ink, hero sentence capped at 44ch, the name sized to
  run margin to margin, phone rule rows recomposed). Remaining WARNs: no footage; secondary notes at
  15px in the muted ink. The sign-in screen deliberately keeps one centred axis and no pictures; its
  inspector FAILs (picture floor, focal size, motion count) are landing-page rules the landing now
  meets.

## Analysis image (third pass)

- **Draw:** `--keep palette,type`, three options; chose *The printed annual*, because a credit analysis
  is content for a committee. Dealt blueprints used: *Mosaic masthead* (visit photograph and
  cropped headers of the case's own documents, greyscale, butted with flat ink and accent tiles),
  *Column aligned on the decimal* (the key figures), *Fixed output beside a reading column*
  (revenue chart in an accent field, points of attention), *Day tabs, banded agenda* (the checklist
  by stage), *Plain names in columns* (partners, creditors, customers), and a full ink close with the
  analyst's opinion. Motion does not apply to an image.
- **Chart:** dataviz skill procedure; the first palette (brand lime and grey) failed the validator
  (lime above the lightness band, grey below the chroma floor); `#6a9a1c` / `#2f78b0` on paper pass
  every check. Legend plus a direct label; per-bar tooltips on screen.
- **Look-and-fix rounds:** repeated AI observations grouped and ranked after rule findings; CSS reset
  specificity fixed (lost margins); figures in two decimal-aligned columns; document thumbnails
  cropped to their printed headers; captions widened. Lint 0 FAIL.
