---
name: KnicksIQ Homepage
description: A Knicks season program on warm paper.
colors:
  signal-blue: "#006bb6"
  signal-blue-deep: "#004f8c"
  signal-orange: "#f58426"
  surface-ink: "#071b2d"
  surface-paper: "#f3eee5"
  surface-sheet: "#fffdf9"
  text-muted: "#5c6874"
  text-on-ink: "#ffffff"
  line-subtle: "rgb(7 27 45 / 14%)"
typography:
  display:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "clamp(4.5rem, 8.7vw, 8rem)"
    fontWeight: 800
    lineHeight: 0.9
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "clamp(2.5rem, 5vw, 4.5rem)"
    fontWeight: 800
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Söhne, Sohne, Helvetica Neue, Helvetica, Arial, system-ui, sans-serif"
    fontSize: "0.94rem"
    lineHeight: 1.65
  navigation:
    fontSize: "0.85rem"
    fontWeight: 650
rounded:
  prompt: "4px"
  field: "6px"
  button: "8px"
  panel: "12px"
spacing:
  gutter: "clamp(1.25rem, 4vw, 4rem)"
  panel: "2rem"
  section: "4rem"
components:
  button-primary:
    backgroundColor: "{colors.signal-blue}"
    textColor: "{colors.text-on-ink}"
    rounded: "{rounded.button}"
    padding: "8px 16px"
  button-archive:
    backgroundColor: "{colors.signal-orange}"
    textColor: "{colors.surface-ink}"
    rounded: "{rounded.field}"
    width: "100%"
  question-field:
    backgroundColor: "{colors.surface-paper}"
    textColor: "{colors.surface-ink}"
    rounded: "{rounded.field}"
    padding: "1rem 1.1rem"
  question-panel:
    backgroundColor: "{colors.surface-sheet}"
    rounded: "{rounded.panel}"
    padding: "{spacing.panel}"
---

# Design System: KnicksIQ Homepage

## Overview

**Creative North Star: "The Knicks Season Program"**

The reconstructed homepage pairs compressed sports headlines and a panoramic Garden photograph with warm paper, editorial rules, and a dark question desk. Large display type establishes identity; quiet controls keep the archive usable.

This is a scoped record of `SeasonArchivePage`, not a global redesign specification. Its source of truth is `archive.tsx` and `landing.css`, with inherited tokens in `../../styles/theme.css`. The existing KnicksIQ mark and credited arena photograph remain identity assets. Page strategy lives in the root `.impeccable/landing-direction.md`.

**Key Characteristics:**
- Condensed display type with generous page margins.
- Blue navigation and orange emphasis against paper and ink.
- Flat editorial sections with softly rounded functional panels.

## Colors

Primary Knicks blue marks the headline emphasis, links, focus, and opening CTA; its deeper shade marks active navigation and text links. Secondary Knicks orange carries the search action and short accents on dark sections. Warm paper is the page canvas, sheet is the form and answer surface, ink supplies text and dark sections, and muted slate supports secondary copy. Subtle ink rules divide editorial content.

**The Semantic Color Rule.** Reuse the existing CSS color roles; do not create a competing homepage palette.

## Typography

Display uses locally served Barlow Condensed 800 with swap loading. The opening headline uses the display token; section headings use the headline token with line heights around one. Body and controls inherit the existing UI font stack; the stack does not imply that Söhne is bundled. Supporting workspace copy is constrained to 65 characters. Small uppercase edition labels use positive tracking; long answers retain the shared, more relaxed reading typography.

## Layout

The centered shell caps at 80rem and uses the fluid gutter token. The opening headline and introduction form a 1.5:1 grid; the dark question desk uses a 0.8:1.2 grid. The image is a cropped panoramic plate with an anchored caption. Browse links form three columns, starter questions two, and source guidance two.

At 64rem the edition label disappears, gaps tighten, and form padding becomes 1.5rem. At 46rem the main grids and question rows stack, while navigation remains visible. At 30rem navigation wraps to its own row, the desk introduction stacks, and form padding becomes 1.25rem. Persisted conversations cap at 60rem. These are homepage breakpoints, not mandates for other routes.

## Elevation & Depth

The page derives depth from paper, dark ink bands, and image overlays. The question panel and homepage answer panel have no shadow or backdrop blur. Shared buttons retain their small component shadow and focus rings; fields use an inset stroke and focused halo. This is a predominantly flat composition, not a blanket removal of every component shadow.

## Shapes

Editorial sections and the photographic plate have square edges. Functional panels use the panel radius; text fields and the orange search control use the field radius. Quick question controls are compact rectangles using the prompt radius. Existing receipt cards retain their shared geometry.

## Components

- **Buttons:** The opening blue shadcn Button is a native anchor to the focusable search section. The orange archive variant fills the form width. Both have a minimum height of 3rem. Canonical press feedback scales to 0.98; reduced motion removes movement.
- **Question field:** A shadcn Field label explicitly names the Textarea. The field is vertically resizable with a 7.5rem minimum height and readable 1rem text. Enter submits, Shift+Enter inserts a line, and IME composition is protected.
- **Navigation:** Full text navigation stays visible on phones. The current archive link combines deep blue and an underline. Interactive controls receive a visible blue outline (3px with a 5px offset).
- **Quick questions:** Bordered, wrapping buttons sit above the search control. They inherit color feedback without a hover lift. Larger editorial starter rows have a topic label, divider, and arrow; pointer hover moves the arrow slightly upward and right.
- **Question desk:** A sheet-colored form panel sits inside the dark section. Readiness status, disabled controls, pending feedback, and retries are functional states, not decorative content.
- **Answers and receipts:** Preserve the shared answer, citation, analytics, warning, and conversation components. On this homepage, answer entrance animation and shadow are removed, and completed answers receive heading focus. `archive.css` remains necessary shared styling, including for the analyst; do not delete it as obsolete homepage CSS.

## Do's and Don'ts

- **Do** preserve the mark, arena credit, visible navigation, evidence links, and accessible form behavior.
- **Do** keep large editorial typography outside the dense answer-reading content.
- **Do** respect reduced motion and keep content visible without entrance animations.
- **Don't** extend this homepage reconstruction to games, reports, or analyst routes by implication.
- **Don't** replace real archive content with invented scores, coverage, or claims.
- **Don't** remove shared answer styles while cleaning up old homepage selectors.
