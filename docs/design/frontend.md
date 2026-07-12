# BookLens Frontend — Design Specification

> Status: north-star spec for Phase 2 (redesign of the SvelteKit skeleton).
> Source: five reference mockups produced during design exploration, annotated
> with the reader's specific modifications. This document is the single source
> of truth for *what* the new frontend looks like and behaves like. It does
> *not* prescribe implementation details (component breakdown, state shape,
> routing) — those belong in the Phase 2 implementation plan.

---

## 1. Voice and motif

BookLens presents itself as **a reader's private index of a private library** —
not an app, not a dashboard, not a chat tool. Every surface should reinforce
that voice. Two phrases from the mockups capture it:

- The tagline beside the wordmark: *"a reader's index"*.
- The reader's bookmark caption on Ask: *"Answers will not reach beyond this
  point."*

The visual language drawn from the mockups:

- **Roman numerals everywhere meaningful** — volume numbers (vol. iii), inquiry
  numbers (Inquiry No. XXVI), step numbers in Upload (I, II, III), chapter
  positions in lists (II · 14). Arabic numerals are reserved for counts that
  must read instantly: percentages, page totals, chapter-of-total ("Ch. 14 of
  31"), file sizes.
- **Small-caps sans labels** above content blocks — `CURRENTLY READING`,
  `INDEX OF SERIES`, `INQUIRIES`, `ACQUISITION`, `ENDPAPER · DIAGRAM OF
  ACQUAINTANCE`. Always introduced with an em dash and an italic gloss when
  the label needs context (`— the ribbons mark where you set the book down`).
- **Dotted leaders** between a primary label and a secondary value (series →
  author in the Library table). Borrowed from typeset catalogue indexes.
- **Hairline rules**, never heavy borders. Section breaks are a single thin
  brass-warm or ink-muted line, often with a label flowing through it.
- **The ribbon bookmark** as a recurring motif: optional on covers, present in
  the Explore scrubber, echoed in the Ask sidebar's left-edge highlight on the
  active inquiry.
- **Italics carry meaning.** Display titles, in-progress thoughts, and editorial
  asides are italic. Plain serif is reserved for the body of an answer or a
  record.
- **No emoji. No icons except where typographically inevitable** (the legend
  symbols on the Explore graph).

---

## 2. Design tokens

These are the values every component reads from. They live in
`frontend-svelte/src/lib/styles/tokens.css` as CSS custom properties.

### 2.1 Palette

This is a **twilight library** — dark mode as a literary tool, not a tech app.
Eyeballed from the mockups; exact hex values can be tuned once on the first
real screen.

| Token              | Approx hex   | Use                                                                 |
|--------------------|--------------|---------------------------------------------------------------------|
| `--ink-bg`         | `#0b1118`    | Page background — near-black with a slight navy cast.                |
| `--ink-surface`    | `#101821`    | Panels, cards (Upload left rail, Ask inquiries rail, scrubber rail). |
| `--ink-hairline`   | `#1f2a36`    | Section rules; barely visible against `--ink-bg`.                    |
| `--bone`           | `#e9e1cf`    | Primary text. Warm off-white, NOT pure white.                        |
| `--bone-muted`     | `#a39c8c`    | Secondary text, meta labels, dotted leaders.                         |
| `--bone-faint`     | `#6c685e`    | Disabled / pending step labels (e.g., "III. Place on the shelf").    |
| `--brass`          | `#b8924a`    | Primary accent. Ribbons, active nav underline, "Shelve volume" CTA, "Aenor" highlight, recap key phrases. |
| `--brass-dim`      | `#5a4830`    | Brass at low emphasis — secondary edges in graph, faint chapter tick.|
| `--oxblood`        | `#a14a3a`    | The "Drawn from Ch. 1–14…" citation chip border, rivalry edges, step-number `I.` in Upload. Use sparingly — one or two appearances per screen. |
| `--quote`          | `#c79a52`    | Inline quoted text inside an answer (e.g., "a woman in the manner of an unlit lamp"). A slightly lighter brass for readability inside prose. |

### 2.2 Typography

Two families, distinct roles.

| Token              | Family (proposed)         | Role                                                                              |
|--------------------|---------------------------|-----------------------------------------------------------------------------------|
| `--serif-display`  | *Source Serif 4* (italic) | Big italic titles: greeting, question, Explore subtitle, Upload "Catalog entry." |
| `--serif-body`     | *Source Serif 4* (roman)  | All running prose, answer body, recap, table values.                              |
| `--sans-caps`      | A clean geometric / humanist sans, all small-caps with tracking | Section labels (`CURRENTLY READING`), nav, meta (`SERIES`, `AUTHOR`, `VOLS.`). |
| `--mono`           | A spaced mono (existing JetBrains Mono is fine) | File metadata only (`hollow-coast.epub · 1.8 MB · sha 4b7a…e019`), keyboard shortcut hint (`⌘K`). |

Notes:
- The fonts proposed are placeholders that match the *feel*. Final pick happens
  on the first real screen. If Source Serif 4 doesn't carry the literary weight
  at large display sizes, swap the display role for *Tiempos Headline*,
  *GT Sectra*, or *Recoleta*.
- **No Inter, no system sans for UI labels.** The sans is small-caps only and
  must read as typeset, not "app-like".

### 2.3 Scale

A simple modular scale; exact values to be tuned in `tokens.css`.

- Spacing: `4, 8, 12, 16, 24, 32, 48, 64, 96` (px).
- Type scale: `12, 13, 14, 16, 18, 22, 28, 40, 56` (px). Display greeting and
  "Catalog entry." live at 56; question at 40; reply body at 18.
- Radii: `2px` (chip / button) and `4px` (book cover corners). No `12px+`
  rounded cards — that's SaaS.
- Shadows: avoid. The dark surface + hairlines do the structural work. A single
  very subtle warm glow behind brass accents is allowed where it adds depth
  (visible faintly on the "Currently Reading" book covers and around the
  legend in Explore).

---

## 3. Shared chrome

Visible on every authenticated route.

### 3.1 Header

A single horizontal bar, ~80px tall, with hairlines top and bottom.

- **Left:** wordmark `BookLens` in display serif at ~24px, followed by the
  italic muted tagline `· a reader's index` at ~14px.
- **Center:** five nav links — `LIBRARY`, `UPLOAD`, `ASK`, `EXPLORE`, `HELP`
  — in `--sans-caps`, ~12px, ~0.18em letter-spacing. The active link has a
  single 1px brass underline directly beneath it (no pill, no background).
- **Right:** the keyboard hint `⌘K — inquire` in `--mono` muted, then the
  reader's display name (`E. BRONTË`) in `--sans-caps` muted, then a circular
  avatar with brass-hairline border containing the reader's two-letter
  monogram (`EB`).
  - **Display-name derivation:** if `user_metadata.full_name` is set, render
    as `<first initial>. <last name>` uppercased — `"Emily Brontë"` → `E.
    BRONTË`. Otherwise render the email's local-part in uppercase small-caps
    — `r.anshumaan01@gmail.com` → `R.ANSHUMAAN01`.
  - **Avatar monogram derivation:** same two-pass logic. Pass 1: if
    `full_name` is set, take the first character of the first and last
    whitespace-separated tokens — `"Emily Brontë"` → `EB`. Pass 2: split the
    email local-part on `.` and `-`, take the first character of the first
    one or two segments — `r.anshumaan01@gmail.com` → `RA`. Always two
    characters, always uppercase.

The header is shown only when authenticated. The login screen owns its own
chrome.

### 3.2 Page frame

Each route renders inside an inset frame: about 32px of padding from the
viewport edge on desktop, with a single hairline rule defining the inner
content area. The frame creates the "this is a single page from a much larger
volume" feel.

### 3.3 Footer (development only)

The bottom-left annotations on the mockups (`DESKTOP · 1440`, `DESKTOP · 1440 ·
DEEP · VOL. III · CH. 18`) are *not* production chrome — they are reference
captions on the mockups. Don't ship them.

---

## 4. Library

The home screen. Three vertical sections, top to bottom.

### 4.1 Greeting strip

- A meta line in `--sans-caps`: `YOUR LIBRARY · VI SERIES · XXIV VOLUMES`.
  Series and volume counts are roman numerals derived from the reader's library
  state.
- The greeting at display size: `Good evening, Emily.` Time-of-day chosen by
  local clock (`Good morning,` / `Good afternoon,` / `Good evening,`). Reader's
  first name comes from auth profile.
- Top-right: two muted italic lines — *"1,847 pages read this month"* and
  *"last opened — 17 m ago"*. These are nice-to-haves; if the data isn't there
  in Phase 2, omit the block. **Do not invent fake stats.**

### 4.2 Currently Reading

A horizontal carousel. Strict spec, because this is the most-used surface.

- Section header: `CURRENTLY READING` in `--sans-caps`, followed by the italic
  gloss `— pick up where you left off`, then a hairline rule stretching to the
  right edge of the frame, which terminates in a small caps count `· IV BOOKS
  ·` (the total in the carousel). Pagination arrows on the far right.
- Each carousel entry is a **two-column unit**:
  - **Left column:** the book cover, rendered as a tall illustrated panel
    (~160×240). The cover shows the book's title in italic serif against the
    series' assigned color (Hollow Coast slate-navy, An Index of Faults
    oxblood, South of the Reading forest-green, Lessons in Astronomy brass).
    Cover chrome: author surname in small-caps at the top, a tiny roman
    numeral and "BOOKLENS" in small caps at the bottom. **No ribbon on
    covers.** The ribbon motif lives in Ask (active-inquiry left border) and
    Explore (scrubber tab); on the home screen, progress is conveyed by the
    brass percentage below the cover.
  - **Right column:** four stacked lines —
    1. `SERIES NAME · VOLUME III/V` in `--sans-caps`.
    2. Title (`Hollow Coast`) in italic display serif at ~28px.
    3. `by A. Hilcaster` in serif roman, muted.
    4. `your bookmark — Ch. 14 of 31` in serif roman, muted, with an em dash.
  - Beneath the right column, at the bottom of the unit:
    - Percentage in brass at ~14px (`45%`).
    - To its right, the action link `RESUME READING` in small caps with a
      hairline underline. The link is only shown when the unit is hovered or
      focused; the percentage is always visible.

- Carousel behavior: horizontal scroll, snap to each unit. Mouse wheel +
  trackpad swipe both work. The last visible unit may be clipped to suggest
  more content (see the partial `Lessons in Astronomy` card in the mockup).

- Empty state: if no book is in progress, omit the whole section. The greeting
  strip above remains.

### 4.3 Index of Series — with the reader's filter modifications

This is where the design departs from the mockup. The reader has specified:

- A **filter row** at the top of this section with two options:
  - **Series** (default) — show every series the reader owns as a typeset
    table (the mockup behavior).
  - **Standalone** — show every book the reader owns that does *not* belong to
    a series, presented as a horizontal carousel using the same two-column
    unit shape as Currently Reading. Standalone units show full reading
    progress on the cover but use the metadata block to convey title +
    author + status rather than "your bookmark".

Section header (same pattern as Currently Reading):

- Small-caps label `INDEX OF SERIES` (or `INDEX OF STANDALONES` when that
  filter is active), italic gloss `— all the shelves; hover to draw a cover`,
  hairline rule terminating at a sort control on the right with three
  small-caps tabs: `BY AUTHOR · BY RECENCY · BY STATUS`. The active sort has a
  brass underline; sorts are mutually exclusive.

#### 4.3.1 Series view (default)

A four-column typeset table, no row separators except a single hairline below
the column headers.

| Column        | Content                                                      | Style                                |
|---------------|--------------------------------------------------------------|--------------------------------------|
| `SERIES`      | Series name                                                  | Italic display serif, ~22px.         |
| `AUTHOR`      | Author surname or full name                                  | Serif roman, ~16px.                  |
| `VOLS.`       | Total count as roman numeral (`v`, `iv`, `iii`)              | Serif roman, muted.                  |
| `LAST OPENED` | "vol. iii · 17 m ago" + small "read/total" indicator at right| Italic muted + small-caps mini-pill. |

The signature detail is a **dotted leader** between the series name and the
author — a row of `·` characters filling the negative space. This leader is
the visual mark that says "this is a catalogue, not a dashboard". The dotted
leader length varies with series title length; it must terminate at a
consistent right margin so author names align in a column.

The mini "read/total" pill on the right (`2/5 READ`, `1/4 READ`, `3/4 READ`)
is a small-caps capsule with a brass-tinted background, shown alongside a
miniature visual representation: a small row of vertical brass tick marks
where filled ticks = books read. This is a small but characterful detail
worth preserving.

**Expansion behavior (reader's modification):** clicking anywhere on a series
row expands the row to reveal **the book covers belonging to that series**,
displayed inline beneath the row. Covers are shown at a smaller scale than
the Currently Reading carousel (~100×150), aligned horizontally with the
SERIES column. Only one series row is expanded at a time; clicking a second
row collapses the first. The expansion is the same "just covers" layout from
the legacy Alpine app — title and metadata appear only on hover/focus of a
specific cover, as a small overlay.

The italic gloss on the section header (`hover to draw a cover`) refers to
this hover behavior: hovering an expanded book cover "draws" its label.

#### 4.3.2 Standalone view

When the filter switches to `Standalone`, the table disappears and is
replaced with a horizontal carousel structurally identical to Currently
Reading: same two-column units, same scroll/snap behavior. The metadata block
varies by reading state:

- **In progress** — identical to a Currently Reading entry: title, author,
  `your bookmark — Ch. X of Y`, percentage in brass, `RESUME READING` link on
  hover. (Standalone in-progress books also appear in the Currently Reading
  carousel above; both surfaces show them.)
- **Unread** — title and author only. No bookmark line, no percentage. Below
  the cover, in place of the percentage, a single small-caps chip: `UNREAD`
  in `--bone-muted` on a `--brass-dim` background.
- **Finished** — title and author only. No bookmark line, no percentage. Chip
  below reads `FINISHED` in `--brass` on a `--brass-dim` background.

Apply the same in-progress/unread/finished rule on the Currently Reading
carousel for consistency — though by definition the Currently Reading
carousel only contains in-progress books, so the chip variants only render
on the Standalone view.

If the reader has zero standalone books, show an italic muted note centered in
the section: *"Your shelves hold only series — no standalone volumes yet."*

---

## 5. Upload

A focused, single-purpose page. The reader described this as "good as-is" —
preserve it.

### 5.1 Layout

Two columns: a narrow left rail (~25% width) and a main content panel.

### 5.2 Left rail — Acquisition steps

- Small-caps label `ACQUISITION` at the top.
- Three steps, each as `<roman numeral>. <step text>`:
  - `I. Drop the file` — completed state. Roman numeral is `--oxblood`. To the
    right of the step text: `DONE` in small caps muted.
  - `II. Inspect the catalog entry` — current state. Text is in `--bone`,
    underlined with a hairline.
  - `III. Place on the shelf` — pending state. Roman numeral and text both at
    `--bone-faint`.
- Below the steps, a paragraph break, then the italic muted aside:
  *"BookLens reads only what you give it — and only as far as your bookmark."*
  This is the spoiler-safe promise expressed in the app's voice.

### 5.3 Main panel — Catalog entry

- Top: big italic display heading `Catalog entry.` (with the period — the
  period is part of the title and signals "this record, complete").
- Top right: file metadata in `--mono` muted —
  `hollow-coast.epub · 1.8 MB · sha 4b7a…e019`. The sha is the first eight
  characters of the file's SHA-256, truncated. This is one of the few places
  mono type appears; it is signalling "this is a system-known fact, not
  authored copy".

- Body is a two-column layout:
  - **Left:** the book cover preview (~280×400), rendered the same way as on
    Library carousel covers — series-colored background, italic title, brass
    elements. This is generated from the EPUB's cover image if present;
    otherwise composed from extracted metadata against a default neutral
    series color.
  - **Right:** a metadata "form" rendered as a typeset table. Each row is a
    pair: label on the left in `--sans-caps`, value on the right in serif.
    Hairline rule between rows. Rows:

    | Label                | Value                                                 |
    |----------------------|-------------------------------------------------------|
    | `TITLE`              | Editable serif text input. `Hollow Coast`.            |
    | `AUTHOR`             | Editable. `A. Hilcaster`.                             |
    | `SERIES`             | Editable. `The Mistwarden Cycle`. Annotated to the right with the italic muted note *"matched · 2 prior volumes on shelf"* when the series already exists in the reader's library. |
    | `POSITION IN SERIES` | Editable. `Volume III` (roman numeral).               |
    | `CHAPTERS DETECTED`  | Read-only system value. `31 · with prologue`.         |
    | `WORD COUNT`         | Read-only system value. `124,310`.                    |

    "Editable" means the value is a text input that *looks* like body type —
    no visible input box chrome. It only reveals as editable on hover/focus or
    when `EDIT FIELDS` is clicked.

- Beneath the table:
  - **Primary CTA:** `Shelve volume` in italic display serif on a brass-fill
    rectangle (~`--brass` background, `--ink-bg` text). The button copy uses
    the same voice as the rest of the app — never `Submit`, never `Upload`.
  - To its right: `EDIT FIELDS` as a small-caps link with hairline underline.
  - Far right: italic muted note *"Reader position will start at Chapter 1."*

### 5.4 States

The upload state machine from Phase 1 stays. The visual treatment per state:

- **idle** — left rail step I is current, II/III pending; main panel shows a
  drop-zone with an italic prompt *"Drop a volume here, or browse to acquire."*
- **extracting** — left rail step I `DONE`, step II current; main panel shows
  a placeholder cover and metadata rows filled with a faint shimmer in
  `--bone-muted` while the LLM extraction call runs. Italic note: *"Reading
  the title page…"*.
- **confirming** — the screen as drawn in the mockup.
- **uploading** — `Shelve volume` button becomes muted and shows a small
  italic *"shelving…"*. Optionally restore the staged progress text from the
  legacy app — *"Parsing chapters…"* → *"Generating embeddings…"* → *"Indexing
  vectors…"* — rendered in italic muted text below the CTA. Drop the fake
  percentage; the staged text is enough.
- **done** — left rail step III becomes current, then a brief transition
  message in the main panel: *"Shelved. The Mistwarden Cycle now holds 3
  volumes."* before the page resets after ~4s.
- **error** — main panel shows an italic muted note in `--oxblood`:
  *"The shelving did not take. <reason>"*. The CTA becomes `Try again`.

---

## 6. Ask

A reading-room interface for the spoiler-safe Q&A.

### 6.1 Layout

Two columns: a narrow left rail of past inquiries, a wide main panel for the
current Q&A.

### 6.2 Left rail — Inquiries

- Small-caps label `INQUIRIES` at the top.
- A vertical list of the reader's past questions. Each entry is two lines:
  1. The question text in italic display serif at ~16px (truncated if needed
     with an ellipsis after ~50 characters).
  2. A small-caps meta line: roman numeral for volume + arabic chapter
     position (`II · 14` = "asked while on Volume II, Chapter 14"). This
     anchors the question in the reader's progress at the time of asking.
- The **active** (currently displayed) inquiry has a 2px brass left border
  along the full height of its entry. No background fill — just the rule. This
  is the ribbon-bookmark motif again, scaled down.
- New questions appear at the top. Clicking an old inquiry re-displays its
  answer in the main panel; it does not re-run the query.

### 6.3 Left rail bottom — Bookmark anchor

Pinned to the bottom of the left rail:

- A small ribbon-bookmark glyph (a brass right-angle hooked shape ~16×16).
- The label `BOOKMARK` in small-caps.
- The current book + chapter in italic serif: *"Hollow Coast · Ch. 14"*.
- A muted italic gloss: *"Answers will not reach beyond this point."*

This is the spoiler-safe promise made visible. It should be present on every
state of the Ask screen.

### 6.4 Main panel — A single inquiry

- Top meta strip: `QUESTION — INQUIRY NO. XXVI` in small-caps. The inquiry
  number is roman, derived from the reader's lifetime question count.
- The question itself rendered in italic display serif at ~40px.
- A horizontal divider with two elements on a single line:
  - The small-caps label `REPLY` on the left, followed by a hairline rule
    running through the line.
  - A **citation chip** floating on the rule: a rounded `2px`-radius rectangle
    with a 1px `--oxblood` border, containing small-caps text
    `DRAWN FROM CH. 1–14 OF VOL. III · AND THE TWO PRIOR VOLS.`. This chip is
    the visible expression of the spoiler-safe boundary on this particular
    answer. Content of the chip comes from the backend's response — chapter
    range it actually used.
- The reply body in serif roman at ~18px, ~1.6 line-height. Reads like prose.
  - Inline quoted text (passages drawn from the book) is wrapped in italic
    and colored `--quote`. The mockup shows: *"a woman in the manner of an
    unlit lamp."*
  - **Quote-marker contract:** the answer-generation LLM is prompted to wrap
    verbatim passages from the book in `<q>…</q>` for inline quotes and
    `<blockquote>…</blockquote>` for multi-sentence passages. The existing
    `marked` renderer passes raw HTML through; the frontend CSS styles
    `q { font-style: italic; color: var(--quote); }` and gives
    `blockquote` the same treatment with a brass left-rule and indent.
  - Em-dashed bullets used in place of `*` or `-` for lists. The mockup shows
    *"— She moves only at the turning of the tide."* style.
- A trailing italic muted sentence flagged as an **editorial aside** when the
  answer reaches the edge of the spoiler-safe boundary:
  *"You have not yet read the chapter in which her name is given."*
- Bottom strip below a final hairline rule:
  - Left: two action links in `--sans-caps` — `CITE PASSAGES` and
    `ASK A FOLLOW-UP`. The first opens the source nodes view (Phase 2 can
    treat this as a simple expandable list of source chapters with links into
    the book — design parity with the mockup is enough). The second focuses a
    follow-up question input.
  - Right: a small-caps timing line — `COMPILED IN 1.4 S · XI PASSAGES
    CONSULTED`. Both values come from the backend response (`elapsed_ms`,
    `source_count`).

### 6.5 Composing a new question

When no inquiry is active — on first arrival at `/ask`, or after clicking
`ASK A FOLLOW-UP` — the main panel renders the composer:

- The italic display serif heading *"What do you want to know?"* at ~40px,
  centered in the main panel's content column.
- A single-line italic input below the heading, ~24px serif italic,
  borderless against the page background, with a hairline rule beneath it
  the width of the content column. No placeholder text inside the input;
  the heading above serves as the prompt.
- A small-caps hint below the rule: `PRESS ⌘↩ TO INQUIRE` in `--bone-muted`.
  Pressing `⌘↩` (or `Ctrl↩` on non-Mac) submits.

On submit, the question is pushed onto the inquiries rail (becoming the
active entry with the brass left-border) and the main panel transitions to
the answered-state layout (§6.4) — same composer chrome is dismissed in
place.

`ASK A FOLLOW-UP` from a current answer re-renders the composer beneath the
just-shown answer with no chrome change (the prior answer remains visible
above). The new request includes the prior Q+A pair in the backend's
`conversation_history` field.

---

## 7. Explore

The most visually ambitious screen. Three columns: graph (~60%), recap
(~30%), scrubber (~10%).

### 7.1 Header strip

- Small-caps label `ENDPAPER · DIAGRAM OF ACQUAINTANCE`. "Endpaper" is the
  voice — this graph is positioned as the diagram you'd find printed on the
  inside cover of a book.
- Below: an italic display serif title that **changes with the scrubber
  position**. The mockup shows two states:
  - Early (vol. i, ch. 4): *"Five figures, lightly drawn."*
  - Deep (vol. iii, ch. 18): *"A dozen figures; the order, at last, named."*
- Below the title, a small italic subtitle locating the scrubber:
  *"— as of vol. i · chapter 4"*.

**The titles must come from the backend, not be hardcoded.** Suggested
implementation: a thin LLM call that, given the current set of revealed
characters and relationships, returns one literary sentence describing the
state of the diagram. Cache by `(series_id, chapter_index)`. **Open question
in Section 9.**

### 7.2 The graph

Hand-drawn, ink-on-paper feel. Specifications:

- **Background:** a single very faint orbit circle (a thin `--brass-dim` ring
  at ~30% opacity) centered loosely behind the densest node cluster. Not a
  guide — a visual artifact, like a compass scratch on parchment. Static; does
  not rotate or animate.
- **Nodes:** each character is a circular roundel ~56px diameter with a 1.5px
  `--brass` border. Inside the circle: the character's initial (or two-letter
  initial for ambiguous cases) in italic display serif. Below the circle: the
  character's full name in serif roman at ~13px.
  - **Filled vs outlined:** key characters (POV, named, frequently appearing)
    get a filled `--ink-surface` background — they "feel" present.
    Lesser/unrevealed characters get a transparent background, the orbit
    visible through them.
  - **Unrevealed characters** (the "?" character in the mockup, "the figure"):
    use a dashed border instead of solid, `?` in italic inside, and italic
    label below. They appear only when the chapter has referenced them as
    unknown. Once revealed (the scrubber crosses the reveal chapter), the
    node morphs to a normal solid-bordered node with the real name.
  - **Identity reveals** (a known character later confirmed to be the same as
    an alias) appear as a single node once the reveal chapter is crossed, not
    two merged nodes. Aenor in the deep-state mockup is shown as
    `--oxblood`-tinted text — first appearance of a revealed identity gets
    the oxblood highlight in the recap on the right.
- **Edges:** lines between nodes carry both a *type* and a *label*.
  - **Bond** — solid `--brass`, 1.5px. Used for primary relationships
    (`travel together`, `kept faith`).
  - **Kin** — solid `--bone-muted`, 1px. Used for family / lineage
    (`ward of`).
  - **Rivalry** — dashed `--oxblood`, 1.5px. Used for antagonism
    (`names her at last`, `burned the archive`).
  - **Passing** — thin `--bone-faint`, 0.5px, often barely visible. Used for
    glancing encounters (`glimpsed once`).
  - Each edge has an inline italic label set in the middle of the curve at
    ~12px. Label background is the page bg (no halo) so the line breaks
    through.

- **Layout:** the reader emphasized the graph should not look like a
  d3-force-default demo. The recommendation in BACKLOG is **hand-positioned
  SVG** (no force simulation) — for the typical 5–25 node case this is both
  feasible and produces a more "drawn by an editor" feel. The backend
  exposes the character + relationship data per `to_chapter` cutoff (existing
  `GET /library/series/{id}/timeline`); the frontend's job is to lay them out
  intentionally. Proposed layout heuristic: place the POV character at the
  visual center-left, fan primary relationships outward along subtle radial
  positions, allow some intentional asymmetry. **This is a Phase 2 design
  task to prototype standalone before integrating.**

- **Legend:** anchored at the bottom-left of the graph panel. Four short rows:
  `── BOND` (brass solid), `── KIN` (bone solid), `--- RIVALRY` (oxblood
  dashed), `── PASSING` (faint solid). All in small-caps with the line glyph
  rendered as actual SVG.

### 7.3 Recap panel

To the right of the graph. Voice and visual style:

- Top label: `PREVIOUSLY, IN THE CYCLE —` in small-caps. The em dash is part
  of it, signalling "and now we will recap".
- Body: italic serif paragraphs. Reads like a "previously, in…" recap before
  a book chapter, not bullet points. The mockup early-state copy:
  *"Caelin has left the Warden's house under quiet duress. At the
  river-crossing she meets Marek; their bond is new and untested."*
- Inline highlights for revealed identities and key phrases use `--oxblood`
  (revealed names) or `--brass` (key phrases). The mockup shows: *"Aenor"* in
  oxblood, *"new and untested"* in brass.
- Closing line of the recap when the scrubber is at the reader's current
  bookmark: italic muted *"The recap ends here, at your bookmark."* When the
  scrubber is behind the bookmark, no closing line is shown.

The recap content comes from the backend. Proposed: a new lightweight
endpoint `GET /library/series/{id}/recap?to_chapter=N` returning the recap
paragraphs as markdown with the highlight markers. **Open question.**

### 7.4 Scrubber

A vertical scrubber on the far right of the page.

- A tall thin vertical ribbon (`--ink-surface` with a 1px `--brass-dim`
  inside edge) running from the top of the content area to the bottom.
- **Tick marks** along the ribbon, one per chapter across all volumes in the
  series. Major ticks every 5 chapters; minor ticks in between.
- **Volume break labels** at the position of each volume's first chapter, in
  small-caps: `VOL. I`, `VOL. II`, `VOL. III`.
- **The ribbon-bookmark indicator:** a brass tab projecting to the left of the
  ribbon at the current scrubber position. Above the tab, the current chapter
  is labeled prominently: `ch. 4` in display serif italic. The tab itself
  carries the gradient of the brass ribbon motif from earlier surfaces.
- Bottom of the scrubber: a small-caps muted hint `drag`. The interaction is
  vertical drag of the tab. Optional: click-anywhere on the ribbon jumps the
  tab; arrow keys move ±1 chapter.

The scrubber is constrained to chapters up to the reader's current bookmark.
Chapters past the bookmark are visible on the ribbon (the volume labels and
ticks render the full series) but the tab cannot be dragged past the
bookmark — attempting to does a small ribbon flutter and surfaces a muted
italic note over the scrubber: *"Beyond your bookmark."*

### 7.5 State transitions

Dragging the scrubber updates:
- The display title (one literary sentence).
- The graph (new nodes appear, edges re-route, unrevealed dashed circles
  resolve into named nodes at their reveal chapter).
- The recap text.

This implies a single state change that re-fetches the timeline at the new
`to_chapter`. Debounce drag-end (~200ms) before firing the request. While
loading, fade the recap and graph to ~60% opacity but do not blank — the
prior state remains legible during the transition.

---

## 8. Help

Treated as low-design utility. A single-column page with the same display
heading style (`Help.` in big italic display serif), followed by short prose
sections in italic muted explaining each tab in the app's voice. No
screenshots, no FAQ accordions. About 200 words total.

Defer the actual copy to a separate task; the design is "match the chrome,
write good prose later."

---

## 9. Decisions log

A record of the gaps the mockups didn't address and how each was resolved.
The body of this document already reflects every resolution below — this
section exists as a paper trail, not as a list of open work.

Status key: **Resolved** = answer is now in the main spec; **Deferred** =
revisit when the relevant screen is being built, with a likely landing place
noted.

1. ~~Quoted-passage marker from the backend.~~ **Resolved:** the answer-generation
   LLM is prompted to wrap verbatim quoted passages from the book in `<q>…</q>`
   (and longer multi-sentence quotes in `<blockquote>…</blockquote>`). The
   existing `marked` renderer passes raw HTML through; the frontend styles
   `<q>` with `color: var(--quote)` and italic. Backend prompt change is small.
   Update §6.4 (Ask main panel) accordingly when implementing.

2. **Source of the literary Explore title.** **Deferred.** Ship Phase 2 with
   the title bound to whatever placeholder the Explore screen needs; revisit
   when the route is live and we have a concrete sense of cost/value. Likely
   landing place when revisited: generated at ingest, cached per chapter.

3. **Recap text on Explore.** **Deferred.** Decide when the Explore route is
   being built. Most likely landing place: concatenate existing per-chapter
   summaries from the `/timeline` endpoint as the initial implementation; add
   LLM fusion or a dedicated recap endpoint only if the concatenated version
   reads disjointed.

4. ~~Ask compose state.~~ **Resolved:** the empty/compose state in §6.5 is the
   canonical layout — the italic display prompt *"What do you want to know?"*
   centered in the main panel, a single borderless italic input below it, and
   the small-caps hint `PRESS ⌘↩ TO INQUIRE`. The input reads as writing in a
   margin, not typing in a chat. Same pattern applies to follow-ups: the
   composer reappears below the just-rendered answer with no chrome change.

5. ~~Standalone-book metadata block.~~ **Resolved:** the "your bookmark — Ch.
   X of Y" line and the percentage are shown **only** for in-progress books
   (standalone or series). For unread and completed books, the metadata block
   collapses to: series-name (or empty for true standalones) · title · author,
   plus a single small-caps state chip below the cover (`UNREAD` or
   `FINISHED`). No bookmark line, no percentage. Apply this rule consistently
   on both the Currently Reading carousel and the Standalone carousel.

6. ~~Ribbon-on-cover progress visualisation.~~ **Resolved:** the ribbon is
   **not** rendered on book covers in either carousel. Progress is conveyed
   by the brass percentage (`45%`) below the cover for in-progress books and
   by the `UNREAD` / `FINISHED` chip for the others. The ribbon motif still
   appears in Ask (active-inquiry left border) and Explore (scrubber tab), so
   the visual language remains coherent without crowding the home screen.
   Update §4.2 (Currently Reading) and §4.3.2 (Standalone carousel) to drop
   the ribbon from the cover spec when implementing.

7. ~~Avatar monogram.~~ **Resolved:** derive the avatar text from the Supabase
   auth identity in two passes. **Pass 1:** if `user_metadata.full_name`
   exists, split on whitespace, take the first character of the first and
   last tokens, uppercase. `"Emily Brontë"` → `EB`. **Pass 2 (fallback):**
   split the email's local-part on `.` and `-`, take the first character of
   the first one or two segments, uppercase. `r.anshumaan01@gmail.com` → `RA`.
   The display-name line beside the avatar (`E. BRONTË`) follows the same
   pass-1/pass-2 logic — first initial + period + last name in small-caps, or
   the email local-part rendered in small-caps if no name is set.

8. **Sort options on Library index.** **Deferred.** Decide the exact
   orderings when the sort interaction is being built. The proposed defaults
   are a reasonable starting point: author A→Z, recency newest first, status
   grouped as currently-reading → unread → completed with recency as the
   in-group tiebreaker.

---

## 10. Explicit non-goals for Phase 2

- **Mobile views.** Out of scope by reader's earlier decision. Desktop only.
- **Animations beyond functional transitions.** Scrubber drag, carousel
  scroll, series row expansion — yes. Page-load animations, parallax,
  decorative motion — no.
- **Light mode.** This is a twilight library. No light theme.
- **Customisation surfaces** (theme switcher, font size, density). The design
  is opinionated; the reader doesn't get to undo it.
- **The fake upload progress percentage (15% → 85%).** Staged status text
  only.
- **Real extraction polling.** Already deferred in BACKLOG; the cover
  "extracting" badge is not rendered in Phase 2.

---

## 11. The order to build

A suggested sequence — not binding, but the rationale is that each screen
proves something the next depends on.

1. **Shared chrome** (`+layout.svelte` with header) — proves typography and
   palette in one place; every screen reads from this.
2. **Library — Currently Reading carousel** — the most-used surface, and the
   one whose details (carousel, cover treatment, brass ribbon) propagate to
   Upload's cover and to the Explore scrubber. If the carousel feels wrong,
   stop and fix.
3. **Library — Index of Series with the filter + expansion** — the table,
   dotted leaders, expansion. Tests sort interactions.
4. **Upload — Catalog entry** — should be fast once the cover treatment from
   step 2 is solid. The state-machine wiring already exists from Phase 1.
5. **Ask** — typography test under load (long-form prose), citation chip,
   inquiries rail.
6. **Explore graph (early state, static data first)** — prototype the graph
   independently before wiring to the timeline endpoint. Decide here whether
   hand-positioned SVG holds up; if not, fall back to D3 force layout with
   heavy styling.
7. **Explore scrubber + recap + state transitions** — the most interaction-heavy
   work, leverages a working graph from step 6.
8. **Help** — last, since it's structurally trivial once everything else has
   set the type and chrome.

---

## 12. Mockups

The five source mockups are the visual ground truth for everything above.
Save copies at `docs/design/mockups/`:

- `library.png` — image 1 of the design exploration.
- `upload-catalog-entry.png` — image 2.
- `ask-inquiry.png` — image 3.
- `explore-early.png` — image 4 (vol. i, ch. 4).
- `explore-deep.png` — image 5 (vol. iii, ch. 18).

Where a written spec in this document disagrees with a mockup, the mockup
wins for *appearance* and the spec wins for *behavior* (reader filter,
expansion, state machine, etc., which the mockups don't depict).
