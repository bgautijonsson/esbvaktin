# Design System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the DESIGN.md design system to the live esbvaktin.is site — new colours, fonts, and variable naming.

**Architecture:** All changes are in `~/esbvaktin-site`. The CSS custom property system in `style.css` is the single source of truth — all 16 CSS files inherit from it. We update the root definitions, rename variables across all files, add Google Fonts loading, and update hardcoded colour values. No layout or JS changes.

**Tech Stack:** CSS custom properties, Google Fonts, 11ty/Nunjucks templates

**Spec:** `~/esbvaktin/docs/superpowers/specs/2026-03-27-design-system-implementation.md`
**Design:** `~/esbvaktin/DESIGN.md`

---

### Task 1: Baseline screenshots (before state)

Capture visual state of every page type before any changes so we can diff after.

**Files:**
- None modified

- [ ] **Step 1: Screenshot all page types**

```bash
cd ~/esbvaktin-site
B=~/.claude/skills/gstack/browse/dist/browse
mkdir -p /tmp/design-before

for url in \
  "https://esbvaktin.is/" \
  "https://esbvaktin.is/fullyrðingar/" \
  "https://esbvaktin.is/heimildir/" \
  "https://esbvaktin.is/raddirnar/" \
  "https://esbvaktin.is/malefni/" \
  "https://esbvaktin.is/vikuyfirlit/" \
  "https://esbvaktin.is/thingraedur/" \
  "https://esbvaktin.is/um-okkur/"; do
  slug=$(echo "$url" | sed 's|https://esbvaktin.is/||;s|/||g;s|$|.png|')
  [ -z "$slug" ] && slug="homepage.png"
  $B goto "$url" 2>/dev/null
  $B screenshot "/tmp/design-before/$slug" 2>/dev/null
  echo "Captured: $slug"
done
```

Expected: 8 screenshots in `/tmp/design-before/`

---

### Task 2: Add Google Fonts to base template

**Files:**
- Modify: `~/esbvaktin-site/_includes/base.njk:9-26`

- [ ] **Step 1: Add font preconnect and stylesheet links**

In `_includes/base.njk`, insert these 3 lines after line 10 (the favicon link) and before line 12 (Open Graph):

```html
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..900;1,9..144,300..900&family=Source+Serif+4:ital,opsz,wght@0,8..60,300..900;1,8..60,300..900&family=Source+Sans+3:ital,wght@0,300..900;1,300..900&family=DM+Sans:ital,opsz,wght@0,9..40,100..1000;1,9..40,100..1000&family=JetBrains+Mono:ital,wght@0,400;0,500;0,600;1,400&display=swap" rel="stylesheet">
```

- [ ] **Step 2: Update Buy Me a Coffee widget colour**

In `_includes/base.njk`, change line 100:

```
data-color="#2563eb"
```
to:
```
data-color="#0F766E"
```

- [ ] **Step 3: Build and verify template renders**

```bash
cd ~/esbvaktin-site && npm run build 2>&1 | tail -5
```

Expected: Build completes with no errors.

- [ ] **Step 4: Commit**

```bash
cd ~/esbvaktin-site
git add _includes/base.njk
git commit -m "feat: add Google Fonts (Fraunces, Source Serif 4, Source Sans 3, DM Sans, JetBrains Mono)

Preconnect + stylesheet link for 5 font families. Update BMAC widget
accent to deep teal (#0F766E) from DESIGN.md."
```

---

### Task 3: Replace root CSS custom properties in style.css

This is the core change. Replace both the light `:root` and dark `@media (prefers-color-scheme: dark)` blocks with DESIGN.md tokens.

**Files:**
- Modify: `~/esbvaktin-site/assets/css/style.css:1-81`

- [ ] **Step 1: Replace the file header and :root block (lines 1-47)**

Replace lines 1-47 with:

```css
/* ESBvaktin — Site-wide styles
 *
 * Design system: DESIGN.md (editorial/civic almanac)
 * Dark mode via prefers-color-scheme.
 */

:root {
  /* ── Colour ──────────────────────────────────────────────── */
  --bg: #F5F0E8;
  --bg-surface: #EDE8DD;
  --bg-surface-hover: #E5DFD3;
  --text: #1C1A17;
  --text-muted: #6B6358;
  --accent: #0F766E;
  --accent-hover: #0D6560;
  --accent-muted: rgba(15, 118, 110, 0.08);
  --accent-muted-border: rgba(15, 118, 110, 0.2);
  --rule: #D5CFC5;
  --rule-strong: #B8B0A3;

  /* Verdict */
  --v-supported: #2E6A4F;
  --v-partial: #8A6A1E;
  --v-unsupported: #A63A2B;
  --v-misleading: #8B3D5E;
  --v-unverifiable: #6B6358;

  /* Semantic */
  --success: #2E6A4F;
  --warning: #8A6A1E;
  --error: #A63A2B;
  --info: #0F766E;

  /* ── Layout ──────────────────────────────────────────────── */
  --radius-sm: 3px;
  --radius-md: 6px;
  --radius-lg: 10px;
  --shadow: 0 1px 3px rgba(28, 26, 23, 0.06);
  --shadow-card: 0 1px 2px rgba(28, 26, 23, 0.04), 0 2px 6px rgba(28, 26, 23, 0.06);
  --max-width: 720px;
  --max-width-wide: 1080px;
  --transition: 0.15s ease;
  --focus-ring: 0 0 0 2px rgba(15, 118, 110, 0.3);

  /* ── Typography ──────────────────────────────────────────── */
  --font-body: 'Source Serif 4', 'Charter', 'Bitstream Charter', Georgia, serif;
  --font-display: 'Fraunces', serif;
  --font-ui: 'Source Sans 3', system-ui, -apple-system, sans-serif;
  --font-data: 'DM Sans', 'Source Sans 3', sans-serif;
  --font-mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace;

  /* ── Spacing ─────────────────────────────────────────────── */
  --sp-2xs: 2px;
  --sp-xs: 4px;
  --sp-sm: 8px;
  --sp-md: 16px;
  --sp-lg: 24px;
  --sp-xl: 32px;
  --sp-2xl: 48px;
  --sp-3xl: 64px;
}
```

- [ ] **Step 2: Replace the dark mode block (lines 49-81)**

Replace the `@media (prefers-color-scheme: dark) { :root { ... } }` block with:

```css
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #141210;
    --bg-surface: #1E1B18;
    --bg-surface-hover: #282420;
    --text: #E8E4DD;
    --text-muted: #9C9488;
    --accent: #2DD4BF;
    --accent-hover: #5EEAD4;
    --accent-muted: rgba(45, 212, 191, 0.08);
    --accent-muted-border: rgba(45, 212, 191, 0.2);
    --rule: #2E2A25;
    --rule-strong: #3D3830;
    --shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
    --shadow-card: 0 1px 2px rgba(0, 0, 0, 0.2), 0 2px 6px rgba(0, 0, 0, 0.25);

    --v-supported: #4ADE80;
    --v-partial: #FBBF24;
    --v-unsupported: #F87171;
    --v-misleading: #C084FC;
    --v-unverifiable: #9C9488;

    --success: #4ADE80;
    --warning: #FBBF24;
    --error: #F87171;
    --info: #2DD4BF;
  }
}
```

- [ ] **Step 3: Update body and heading font references in style.css**

In `style.css`, update the selectors that reference old font variable names:

Line ~97: `font-family: var(--font);` → `font-family: var(--font-body);`
Line ~106: `font-family: var(--font-heading);` → `font-family: var(--font-display);`

And update all other occurrences within `style.css`:
- `var(--font)` → `var(--font-body)` (3 occurrences beyond the root block)
- `var(--font-heading)` → `var(--font-display)` (21 occurrences)
- `var(--border)` → `var(--rule)` (27 occurrences)
- `var(--bg-card)` → `var(--bg-surface)` (5 occurrences)
- `var(--bg-alt)` → `var(--bg-surface)` (6 occurrences)
- `var(--bg-nav)` → `var(--bg-surface)` (1 occurrence)
- `var(--text-secondary)` → `var(--text-muted)` (44 occurrences)
- `var(--text-primary)` → `var(--text)` (1 occurrence)
- `var(--surface)` → `var(--bg-surface)` (1 occurrence beyond root)
- `var(--shadow-nav)` → `var(--shadow)` (1 occurrence)
- `var(--radius)` → `var(--radius-md)` (9 occurrences)
- `var(--verdict-supported)` → `var(--v-supported)` (all)
- `var(--verdict-partial)` → `var(--v-partial)` (all)
- `var(--verdict-unsupported)` → `var(--v-unsupported)` (all)
- `var(--verdict-misleading)` → `var(--v-misleading)` (all)
- `var(--verdict-unverifiable)` → `var(--v-unverifiable)` (all)
- `var(--green)` → `var(--v-supported)` (all in style.css)
- `var(--yellow)` → `var(--v-partial)` (all in style.css)
- `var(--orange)` → `var(--v-unsupported)` (all in style.css)
- `var(--red)` → `var(--error)` (all in style.css)
- `var(--grey)` → `var(--v-unverifiable)` (all in style.css)

- [ ] **Step 4: Verify no old variable names remain in style.css**

```bash
cd ~/esbvaktin-site
grep -cE 'var\(--(bg-card|bg-alt|bg-nav|text-secondary|text-primary|border|font-heading|surface-raised|shadow-nav|verdict-supported|verdict-partial|verdict-unsupported|verdict-misleading|verdict-unverifiable)\)' assets/css/style.css
```

Expected: `0`

```bash
grep -cE 'var\(--font\)' assets/css/style.css
```

Expected: `0`

- [ ] **Step 5: Build and verify**

```bash
npm run build 2>&1 | tail -5
```

Expected: Build completes with no errors.

- [ ] **Step 6: Commit**

```bash
cd ~/esbvaktin-site
git add assets/css/style.css
git commit -m "feat: replace CSS tokens with DESIGN.md values

Warm cream backgrounds, deep teal accent, Fraunces/Source Serif 4
typography, editorial verdict colours. Rename all variables to match
DESIGN.md naming (--bg-card→--bg-surface, --border→--rule, etc.)."
```

---

### Task 4: Propagate variable renames to tracker-base.css

**Files:**
- Modify: `~/esbvaktin-site/assets/css/tracker-base.css`

- [ ] **Step 1: Rename variables**

Apply these find-and-replace operations across the entire file:

| Find | Replace |
|------|---------|
| `var(--bg-card)` | `var(--bg-surface)` |
| `var(--bg-alt)` | `var(--bg-surface)` |
| `var(--text-secondary)` | `var(--text-muted)` |
| `var(--border)` | `var(--rule)` |
| `var(--font-heading)` | `var(--font-display)` |
| `var(--font)` | `var(--font-body)` |
| `var(--radius)` | `var(--radius-md)` |
| `var(--verdict-supported)` | `var(--v-supported)` |
| `var(--verdict-partial)` | `var(--v-partial)` |
| `var(--verdict-unsupported)` | `var(--v-unsupported)` |
| `var(--verdict-misleading)` | `var(--v-misleading)` |
| `var(--verdict-unverifiable)` | `var(--v-unverifiable)` |

Also replace the hardcoded blue on line 281:
`color: #2563eb;` → `color: var(--accent);`

**Caution:** When replacing `var(--font)`, match the exact string `var(--font)` not `var(--font-heading)` or `var(--font-mono)`. Use word-boundary-aware replacement.

- [ ] **Step 2: Verify no old names remain**

```bash
grep -cE 'var\(--(bg-card|bg-alt|text-secondary|border|font-heading|verdict-supported|verdict-partial|verdict-unsupported|verdict-misleading|verdict-unverifiable)\)' assets/css/tracker-base.css
```

Expected: `0`

- [ ] **Step 3: Commit**

```bash
git add assets/css/tracker-base.css
git commit -m "refactor: rename CSS variables in tracker-base.css to match DESIGN.md"
```

---

### Task 5: Propagate variable renames to claim-tracker.css and discourse-tracker.css

**Files:**
- Modify: `~/esbvaktin-site/assets/css/claim-tracker.css`
- Modify: `~/esbvaktin-site/assets/css/discourse-tracker.css`

- [ ] **Step 1: Rename variables in claim-tracker.css**

Same find-and-replace table as Task 4. Key counts:
- `var(--text-secondary)` — 7 occurrences
- `var(--border)` — 5 occurrences
- `var(--verdict-*)` — 5 occurrences
- `var(--bg-alt)` — 1 occurrence
- `var(--radius)` — 1 occurrence
- `var(--font)` — 1 occurrence

- [ ] **Step 2: Rename variables in discourse-tracker.css**

Key counts:
- `var(--text-secondary)` — 4 occurrences
- `var(--font)` — 1 occurrence
- `var(--green)` — 1 occurrence → `var(--v-supported)`

- [ ] **Step 3: Verify**

```bash
grep -cE 'var\(--(bg-card|bg-alt|text-secondary|border|font-heading|verdict-|--green\)|--yellow\)|--orange\)|--red\)|--grey\))\b' assets/css/claim-tracker.css assets/css/discourse-tracker.css
```

Expected: `0` for both files.

- [ ] **Step 4: Commit**

```bash
git add assets/css/claim-tracker.css assets/css/discourse-tracker.css
git commit -m "refactor: rename CSS variables in claim + discourse trackers"
```

---

### Task 6: Propagate to entity-detail.css and entity-tracker.css

These files have their own dark mode overrides.

**Files:**
- Modify: `~/esbvaktin-site/assets/css/entity-detail.css`
- Modify: `~/esbvaktin-site/assets/css/entity-tracker.css`

- [ ] **Step 1: Rename variables in entity-detail.css**

Key counts:
- `var(--text-secondary)` — 15 occurrences
- `var(--border)` — 9 occurrences
- `var(--bg-card)` — 5 occurrences
- `var(--bg-alt)` — 1 occurrence
- `var(--radius)` — 4 occurrences
- `var(--green)` — 5, `var(--yellow)` — 3, `var(--red)` — 2, `var(--grey)` — 1
- Hardcoded `#3b82f6` in gradient (line 30) → `var(--accent)`

Also update the `@media (prefers-color-scheme: dark)` block:
- Rename any old variable definitions within it (e.g., `--bg-card` → `--bg-surface`)

- [ ] **Step 2: Rename variables in entity-tracker.css**

Key counts:
- `var(--text-secondary)` — 7 occurrences
- `var(--border)` — 5 occurrences
- `var(--bg-card)` — 3 occurrences
- `var(--bg-alt)` — 2 occurrences
- `var(--radius)` — 2 occurrences
- `var(--font-heading)` — 0 (check), `var(--font)` — 1
- `var(--green)` — 2

Also update its `@media (prefers-color-scheme: dark)` block.

- [ ] **Step 3: Verify**

```bash
grep -cE 'var\(--(bg-card|bg-alt|text-secondary|border)\)' assets/css/entity-detail.css assets/css/entity-tracker.css
```

Expected: `0` for both files.

- [ ] **Step 4: Commit**

```bash
git add assets/css/entity-detail.css assets/css/entity-tracker.css
git commit -m "refactor: rename CSS variables in entity detail + tracker"
```

---

### Task 7: Propagate to evidence-detail.css, evidence-tracker.css, evidence-badges.css

**Files:**
- Modify: `~/esbvaktin-site/assets/css/evidence-detail.css`
- Modify: `~/esbvaktin-site/assets/css/evidence-tracker.css`
- Modify: `~/esbvaktin-site/assets/css/evidence-badges.css`

- [ ] **Step 1: Rename variables in evidence-detail.css**

Key counts:
- `var(--text-secondary)` — 10
- `var(--border)` — 6
- `var(--bg-card)` — 6
- `var(--radius)` — 4
- `var(--green)` — 4, `var(--yellow)` — 2, `var(--red)` — 1

Also update its dark mode override block.

- [ ] **Step 2: Rename variables in evidence-tracker.css**

Key counts:
- `var(--text-secondary)` — 4
- `var(--border)` — 1
- `var(--radius)` — 1

Also update its dark mode override block.

- [ ] **Step 3: Rename variables in evidence-badges.css**

Key counts:
- `var(--green)` — 1, `var(--yellow)` — 1, `var(--grey)` — 1
- `var(--text-secondary)` — 1
- Hardcoded `#3b82f6` (line 13) → `var(--accent)`

- [ ] **Step 4: Verify**

```bash
grep -cE 'var\(--(bg-card|text-secondary|border)\)|#3b82f6' assets/css/evidence-detail.css assets/css/evidence-tracker.css assets/css/evidence-badges.css
```

Expected: `0` for all three files.

- [ ] **Step 5: Commit**

```bash
git add assets/css/evidence-detail.css assets/css/evidence-tracker.css assets/css/evidence-badges.css
git commit -m "refactor: rename CSS variables in evidence detail + tracker + badges"
```

---

### Task 8: Propagate to overview-detail.css and overview-tracker.css

**Files:**
- Modify: `~/esbvaktin-site/assets/css/overview-detail.css`
- Modify: `~/esbvaktin-site/assets/css/overview-tracker.css`

- [ ] **Step 1: Rename variables in overview-detail.css**

Key counts:
- `var(--text-secondary)` — 8
- `var(--border)` — 14
- `var(--bg-alt)` — 1
- `var(--radius)` — 1
- `var(--font-heading)` — 1
- `var(--font)` — 1
- `var(--verdict-*)` — 2
- `var(--surface)` — 4

Also update its dark mode override block.

- [ ] **Step 2: Rename variables in overview-tracker.css**

Key counts:
- `var(--border)` — 2
- `var(--surface)` — 2

- [ ] **Step 3: Verify and commit**

```bash
grep -cE 'var\(--(bg-card|bg-alt|text-secondary|border|font-heading|surface\)|verdict-)' assets/css/overview-detail.css assets/css/overview-tracker.css
```

Expected: `0` for both.

```bash
git add assets/css/overview-detail.css assets/css/overview-tracker.css
git commit -m "refactor: rename CSS variables in overview detail + tracker"
```

---

### Task 9: Propagate to remaining CSS files

**Files:**
- Modify: `~/esbvaktin-site/assets/css/speeches-tracker.css`
- Modify: `~/esbvaktin-site/assets/css/debate-detail.css`
- Modify: `~/esbvaktin-site/assets/css/topic-detail.css`
- Modify: `~/esbvaktin-site/assets/css/topic-tracker.css`
- Modify: `~/esbvaktin-site/assets/css/comparison.css`

- [ ] **Step 1: Rename variables in speeches-tracker.css**

Key counts:
- `var(--text-secondary)` — 5, `var(--border)` — 3, `var(--bg-card)` — 2
- `var(--bg-alt)` — 4, `var(--radius)` — 4
- `var(--font-heading)` — 1, `var(--font)` — 1

- [ ] **Step 2: Rename variables in debate-detail.css**

Key counts:
- `var(--text-secondary)` — 7, `var(--border)` — 8, `var(--bg-card)` — 2
- `var(--radius)` — 3, `var(--font-heading)` — 3

- [ ] **Step 3: Rename variables in topic-detail.css**

Key counts:
- `var(--border)` — 4, `var(--surface)` — 3

- [ ] **Step 4: Rename variables in topic-tracker.css**

Key counts:
- `var(--border)` — 4, `var(--surface)` — 4

- [ ] **Step 5: Rename variables in comparison.css**

Key counts:
- `var(--text-secondary)` — 7, `var(--border)` — 2, `var(--bg-card)` — 1
- `var(--green)` — 1, `var(--yellow)` — 1, `var(--red)` — 1
- Hardcoded `#3b82f6` in gradient (line 29) → `var(--accent)`

Also update its dark mode override block.

- [ ] **Step 6: Verify all remaining files**

```bash
grep -rlE 'var\(--(bg-card|bg-alt|bg-nav|text-secondary|text-primary|border|font-heading|surface-raised|shadow-nav|verdict-supported|verdict-partial|verdict-unsupported|verdict-misleading|verdict-unverifiable)\)' assets/css/
```

Expected: No matches (empty output).

```bash
grep -rlE 'var\(--font\)' assets/css/
```

Expected: No matches.

```bash
grep -rl '#2563eb\|#1d4ed8\|#3b82f6' assets/css/
```

Expected: No matches.

- [ ] **Step 7: Commit**

```bash
git add assets/css/speeches-tracker.css assets/css/debate-detail.css assets/css/topic-detail.css assets/css/topic-tracker.css assets/css/comparison.css
git commit -m "refactor: rename CSS variables in speeches, debate, topic, comparison CSS"
```

---

### Task 10: Update favicon

**Files:**
- Modify: `~/esbvaktin-site/assets/img/favicon.svg`

- [ ] **Step 1: Replace blue with teal in favicon**

Replace all 3 instances of `#2563eb` with `#0F766E`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <circle cx="14" cy="14" r="10" fill="none" stroke="#0F766E" stroke-width="3"/>
  <line x1="21" y1="21" x2="29" y2="29" stroke="#0F766E" stroke-width="3" stroke-linecap="round"/>
  <path d="M10 14l3 3 5-6" fill="none" stroke="#0F766E" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
```

- [ ] **Step 2: Commit**

```bash
git add assets/img/favicon.svg
git commit -m "chore: update favicon accent to deep teal (#0F766E)"
```

---

### Task 11: Build, verify, and capture after screenshots

**Files:**
- None modified

- [ ] **Step 1: Full build**

```bash
cd ~/esbvaktin-site && npm run build 2>&1 | tail -5
```

Expected: Build completes with no errors.

- [ ] **Step 2: Serve locally and screenshot**

```bash
npx @11ty/eleventy --serve --port 8081 &
sleep 3

B=~/.claude/skills/gstack/browse/dist/browse
mkdir -p /tmp/design-after

for url in \
  "http://localhost:8081/" \
  "http://localhost:8081/fullyrðingar/" \
  "http://localhost:8081/heimildir/" \
  "http://localhost:8081/raddirnar/" \
  "http://localhost:8081/malefni/" \
  "http://localhost:8081/vikuyfirlit/" \
  "http://localhost:8081/thingraedur/" \
  "http://localhost:8081/um-okkur/"; do
  slug=$(echo "$url" | sed 's|http://localhost:8081/||;s|/||g;s|$|.png|')
  [ -z "$slug" ] && slug="homepage.png"
  $B goto "$url" 2>/dev/null
  $B screenshot "/tmp/design-after/$slug" 2>/dev/null
  echo "Captured: $slug"
done

kill %1 2>/dev/null
```

- [ ] **Step 3: Visual comparison**

Open before/after screenshots side by side. Verify:
- Warm cream background (#F5F0E8) visible on all pages
- Deep teal accent (#0F766E) on links, logo, buttons
- Serif body text (Source Serif 4) rendering
- Display headings (Fraunces) rendering
- Verdict badges showing new muted editorial colours
- Dark mode: set OS to dark, re-screenshot homepage, verify warm dark tones

- [ ] **Step 4: Grep for any remaining old variable references**

```bash
cd ~/esbvaktin-site
echo "=== Old variable names ==="
grep -rlE 'var\(--(bg-card|bg-alt|bg-nav|text-secondary|text-primary|border|font-heading|surface-raised|shadow-nav|verdict-supported|verdict-partial|verdict-unsupported|verdict-misleading|verdict-unverifiable)\)' assets/css/ _includes/ || echo "CLEAN"

echo "=== Bare --font ==="
grep -rlE 'var\(--font\)[^-]' assets/css/ || echo "CLEAN"

echo "=== Old blue hex ==="
grep -rl '#2563eb\|#1d4ed8' assets/ _includes/ || echo "CLEAN"
```

Expected: All three checks print `CLEAN`.
