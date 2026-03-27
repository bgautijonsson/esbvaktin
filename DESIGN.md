# Design System — ESB Vaktin

## Product Context
- **What this is:** Independent, data-driven civic information platform for Iceland's EU membership referendum
- **Who it's for:** Icelandic general public approaching a once-in-a-generation vote
- **Space/industry:** Civic information, fact-checking, editorial data journalism
- **Project type:** Editorial site with data dashboards, claim tracking, evidence database, weekly digests

## Aesthetic Direction
- **Direction:** Editorial / Civic Almanac — a research publication you actually want to read. What if Hagtíðindi met Monocle.
- **Decoration level:** Intentional — structural rules, typographic contrast, whitespace. Lines, blocks, stamps. No decorative elements.
- **Mood:** Serious but warm. Data-dense but inviting. Trustworthy without being cold. The 3-second reaction: "This was made by people who care about this country."
- **Reference sites:** ProPublica (editorial gravitas), Zetland.dk (warm, inviting), Full Fact (clear hierarchy)
- **Anti-slop rules:** No gradients in core identity. No icon feature grids. No fully centred hero stacks. No floating glass cards. No decorative blobs. No purple/violet accents. Use lines, blocks, stamps, tables, and typographic contrast.

## Typography
- **Display/Hero:** Fraunces (variable, optical sizing) — wonky serif with personality at headline sizes. Full Icelandic support (þ, ð, æ). Warm, confident, distinctly editorial.
- **Body:** Source Serif 4 (variable, optical sizing) — screen-optimised serif designed for long-form reading. Excellent Icelandic character support.
- **UI/Nav/Labels:** Source Sans 3 — matches Source Serif metrics. Clean, professional for navigation and metadata.
- **Data/Tables:** DM Sans (tabular-nums) — modern, legible, compact for statistics and dashboards.
- **Code:** JetBrains Mono
- **Loading:** Google Fonts CDN. Preconnect to fonts.googleapis.com and fonts.gstatic.com.
- **Scale:**
  - Display XL: clamp(2.5rem, 5vw, 4rem), weight 500, line-height 1.1, letter-spacing -0.02em
  - Display: clamp(2rem, 4vw, 3rem), weight 500, line-height 1.12
  - H2: 1.5rem, weight 500, line-height 1.2
  - H3: 1.25rem, weight 600, line-height 1.3
  - Body: 1.0625rem, line-height 1.65
  - Small/UI: 0.875rem, line-height 1.5
  - Caption: 0.75rem, line-height 1.4
  - Label: 0.6875rem, weight 700, uppercase, letter-spacing 0.06em
- **Blacklist:** Never use Inter, Roboto, Arial, Helvetica, Open Sans, Poppins, Montserrat, or system-ui as primary fonts.

## Colour
- **Approach:** Restrained — one primary accent + warm neutrals. Colour is reserved for meaning (verdicts, links, emphasis).

### Light Mode
| Token | Hex | Usage |
|-------|-----|-------|
| `--bg` | `#F5F0E8` | Page background (warm cream, like good paper) |
| `--bg-surface` | `#EDE8DD` | Card/surface backgrounds |
| `--bg-surface-hover` | `#E5DFD3` | Card hover state |
| `--text` | `#1C1A17` | Primary text (warm near-black) |
| `--text-muted` | `#6B6358` | Secondary text, metadata |
| `--accent` | `#0F766E` | Links, buttons, interactive elements (deep teal) |
| `--accent-hover` | `#0D6560` | Accent hover state |
| `--accent-muted` | `rgba(15,118,110,0.08)` | Accent backgrounds |
| `--accent-muted-border` | `rgba(15,118,110,0.2)` | Accent border tints |
| `--rule` | `#D5CFC5` | Borders, dividers |
| `--rule-strong` | `#B8B0A3` | Emphasis borders, active states |

### Dark Mode
| Token | Hex | Usage |
|-------|-----|-------|
| `--bg` | `#141210` | Page background (deep warm black) |
| `--bg-surface` | `#1E1B18` | Card/surface backgrounds |
| `--bg-surface-hover` | `#282420` | Card hover state |
| `--text` | `#E8E4DD` | Primary text |
| `--text-muted` | `#9C9488` | Secondary text |
| `--accent` | `#2DD4BF` | Links, interactive (lighter teal for contrast) |
| `--accent-hover` | `#5EEAD4` | Accent hover |
| `--rule` | `#2E2A25` | Borders |
| `--rule-strong` | `#3D3830` | Emphasis borders |

### Verdict Palette
Muted, editorial tones. Stamped, not pill-shaped.

| Verdict | Light | Dark | Token |
|---------|-------|------|-------|
| Supported / Stuðlar | `#2E6A4F` | `#4ADE80` | `--v-supported` |
| Partial / Að hluta | `#8A6A1E` | `#FBBF24` | `--v-partial` |
| Unsupported / Óstuðlar | `#A63A2B` | `#F87171` | `--v-unsupported` |
| Misleading / Villandi | `#8B3D5E` | `#C084FC` | `--v-misleading` |
| Unverifiable / Ósannreynanlegt | `#6B6358` | `#9C9488` | `--v-unverifiable` |

### Semantic
| Purpose | Light | Dark | Token |
|---------|-------|------|-------|
| Success | `#2E6A4F` | `#4ADE80` | `--success` |
| Warning | `#8A6A1E` | `#FBBF24` | `--warning` |
| Error | `#A63A2B` | `#F87171` | `--error` |
| Info | `#0F766E` | `#2DD4BF` | `--info` |

### Dark Mode Strategy
Warm dark, not cold. Background has a brown warmth (#141210), not blue-grey slate. Reduce accent saturation slightly. Never invert into neon. Verdict colours shift to lighter, desaturated versions for legibility on dark surfaces.

## Spacing
- **Base unit:** 4px
- **Density:** Comfortable
- **Scale:** 2xs(2px) xs(4px) sm(8px) md(16px) lg(24px) xl(32px) 2xl(48px) 3xl(64px)

## Layout
- **Approach:** Grid-disciplined with editorial rhythm
- **Grid:** Single column for content (720px max), two-column with sidebar for homepage (1080px max)
- **Max content width:** 720px (reading), 1080px (wide/dashboard)
- **Border radius:** Hierarchical — sm: 3px, md: 6px, lg: 10px. No fully rounded elements (no pill shapes for primary UI).
- **Alignment:** Left-aligned primary. Reserve centring for rare ceremonial moments (e.g., referendum countdown).
- **Rules:** Use full-width horizontal rules and strong top borders for section breaks. Borders are structural, not decorative.
- **Evidence-first pattern:** Claims show the claim text and evidence before the verdict badge. Verdict is a conclusion drawn from evidence, not a label applied to a person.

## Motion
- **Approach:** Minimal-functional — sparse, directional, editorial
- **Easing:** enter(ease-out) exit(ease-in) move(ease-in-out)
- **Duration:** micro(50-100ms) short(150-200ms) medium(200-300ms)
- **Hover states:** Underline shifts, rule darkening, subtle panel tint. No bouncy microinteractions.
- **Page transitions:** Upward reveal for data updates, side-in for annotation panels.

## Design Principles
1. **Almanac, not app.** The site should feel like a well-edited civic publication with data instruments embedded inside it, not a SaaS dashboard.
2. **Evidence before verdict.** Show readers what the evidence says before telling them the conclusion. Curiosity over gotcha.
3. **Visible uncertainty.** Confidence levels are displayed prominently, not hidden. Intellectual honesty is a design feature.
4. **Typography carries the atmosphere.** The editorial serif stack (Fraunces + Source Serif 4) does the work that decorative elements would do elsewhere.
5. **Warm paper, not white canvas.** The cream background (#F5F0E8) is an intentional material choice — it signals "edited, considered" vs "generated, utilitarian."
6. **Colour is meaningful.** Every use of colour beyond the neutral palette communicates something specific (verdict, link, emphasis). No decorative colour.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-27 | Initial design system | Created by /design-consultation with Codex + Claude subagent voices. All three voices converged on warm editorial aesthetic. Research: Full Fact, PolitiFact, ProPublica, Zetland, The Pudding, current ESBvaktin. |
| 2026-03-27 | Fraunces for display | Distinctive wonky serif with optical sizing. Deliberately departs from sans-serif headings used by most civic/fact-checking sites. |
| 2026-03-27 | Deep teal accent (#0F766E) | Replaces generic blue (#2563eb). North Atlantic, not institutional. Distinct from all major Icelandic news outlets. |
| 2026-03-27 | Warm cream backgrounds (#F5F0E8) | Replaces pure white. Both Codex and subagent independently proposed paper-like warmth. Signals editorial care. |
| 2026-03-27 | Evidence-first claim layout | Verdict badge appears after evidence, not before. Structurally embodies "curiosity over gotcha" philosophy. |
| 2026-03-27 | Muted verdict colours | Forest green, amber, terracotta, plum, warm grey. Editorial stamps, not app pills. |