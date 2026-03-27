# Design System Implementation — ESB Vaktin

**Date:** 2026-03-27
**Design source:** `/DESIGN.md`
**Target repo:** `~/esbvaktin-site`
**Approach:** Token values + variable rename (Approach B)

## Summary

Apply the design system defined in DESIGN.md to the live esbvaktin.is site. This involves updating CSS custom property values (colours, fonts, spacing), renaming variables to match DESIGN.md token names, and adding Google Fonts loading. All work is in the `esbvaktin-site` repo.

## Scope

**In scope:**
- Update CSS custom properties (values + names) in `style.css`
- Propagate variable renames across all 16 CSS files
- Add Google Fonts preconnect + stylesheet link to `base.njk`
- Update dark mode variables (keep `prefers-color-scheme` approach)
- Update verdict colour tokens
- Add new spacing and typography tokens

**Out of scope:**
- Layout restructuring (evidence-first claim presentation is a separate feature)
- Dark mode toggle (manual override deferred)
- CSS file reorganisation
- New components or page layouts
- Navigation redesign

## Variable Mapping

### Renamed Variables

| Old Name | New Name | Old Value (light) | New Value (light) |
|----------|----------|-------------------|-------------------|
| `--bg` | `--bg` | `#ffffff` | `#F5F0E8` |
| `--bg-alt` | _(remove)_ | `#f8fafc` | _(merged into --bg-surface)_ |
| `--bg-card` | `--bg-surface` | `#f8fafc` | `#EDE8DD` |
| `--bg-card-hover` | `--bg-surface-hover` | `#f0f4f8` | `#E5DFD3` |
| `--text` | `--text` | `#1a1a2e` | `#1C1A17` |
| `--text-secondary` | `--text-muted` | `#555` | `#6B6358` |
| `--border` | `--rule` | `#e0e0e0` | `#D5CFC5` |
| `--accent` | `--accent` | `#2563eb` | `#0F766E` |
| `--accent-hover` | `--accent-hover` | `#1d4ed8` | `#0D6560` |
| `--accent-muted` | `--accent-muted` | `rgba(37,99,235,0.08)` | `rgba(15,118,110,0.08)` |
| `--accent-muted-border` | `--accent-muted-border` | `rgba(37,99,235,0.15)` | `rgba(15,118,110,0.2)` |
| `--green` | `--v-supported` | `#16a34a` | `#2E6A4F` |
| `--yellow` | `--v-partial` | `#ca8a04` | `#8A6A1E` |
| `--orange` | `--v-unsupported` | `#c2410c` | `#A63A2B` |
| `--red` | _(remove, use --error)_ | `#e11d48` | `#A63A2B` |
| `--grey` | `--v-unverifiable` | `#6b7280` | `#6B6358` |
| `--verdict-supported` | _(inline to --v-supported)_ | `var(--green)` | `#2E6A4F` |
| `--verdict-partial` | _(inline to --v-partial)_ | `var(--yellow)` | `#8A6A1E` |
| `--verdict-unsupported` | _(inline to --v-unsupported)_ | `var(--orange)` | `#A63A2B` |
| `--verdict-misleading` | `--v-misleading` | `#7c3aed` | `#8B3D5E` |
| `--verdict-unverifiable` | _(inline to --v-unverifiable)_ | `var(--grey)` | `#6B6358` |
| `--font` | `--font-body` | Charter stack | `'Source Serif 4', 'Charter', Georgia, serif` |
| `--font-heading` | `--font-display` | system-ui stack | `'Fraunces', serif` |
| `--font-mono` | `--font-mono` | SF Mono stack | `'JetBrains Mono', 'SF Mono', monospace` |
| _(new)_ | `--font-ui` | — | `'Source Sans 3', system-ui, sans-serif` |
| _(new)_ | `--font-data` | — | `'DM Sans', 'Source Sans 3', sans-serif` |
| `--surface` | `--bg-surface` | `var(--bg-card)` | `#EDE8DD` |
| `--surface-raised` | _(remove)_ | `#f8f9fa` | _(unused)_ |
| `--text-primary` | _(remove, use --text)_ | `var(--text)` | _(redundant)_ |
| `--text-muted` | `--text-muted` | `var(--text-secondary)` | `#6B6358` |
| `--bg-nav` | _(remove, use --bg-surface)_ | `#f8fafc` | _(use --bg-surface)_ |
| `--shadow-nav` | _(remove, use --shadow)_ | special | _(simplify)_ |

### New Variables

| Name | Light Value | Purpose |
|------|-------------|---------|
| `--rule-strong` | `#B8B0A3` | Emphasis borders, active states |
| `--shadow-card` | `0 1px 2px rgba(28,26,23,0.04), 0 2px 6px rgba(28,26,23,0.06)` | Card elevation |
| `--success` | `#2E6A4F` | Semantic success |
| `--warning` | `#8A6A1E` | Semantic warning |
| `--error` | `#A63A2B` | Semantic error |
| `--info` | `#0F766E` | Semantic info |
| `--font-ui` | `'Source Sans 3', system-ui, sans-serif` | Navigation, labels, metadata |
| `--font-data` | `'DM Sans', 'Source Sans 3', sans-serif` | Statistics, tables |
| `--sp-2xs` through `--sp-3xl` | 2px to 64px | Spacing scale |
| `--radius-sm` | `3px` | Small radius |
| `--radius-md` | `6px` | Medium radius |
| `--radius-lg` | `10px` | Large radius |

### Dark Mode Variables

Same rename mapping as light mode, with these values:

| Token | Dark Value |
|-------|-----------|
| `--bg` | `#141210` |
| `--bg-surface` | `#1E1B18` |
| `--bg-surface-hover` | `#282420` |
| `--text` | `#E8E4DD` |
| `--text-muted` | `#9C9488` |
| `--accent` | `#2DD4BF` |
| `--accent-hover` | `#5EEAD4` |
| `--rule` | `#2E2A25` |
| `--rule-strong` | `#3D3830` |
| `--v-supported` | `#4ADE80` |
| `--v-partial` | `#FBBF24` |
| `--v-unsupported` | `#F87171` |
| `--v-misleading` | `#C084FC` |
| `--v-unverifiable` | `#9C9488` |

## Files to Modify

### 1. `_includes/base.njk` — Add Google Fonts

Add before the `style.css` link:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..900;1,9..144,300..900&family=Source+Serif+4:ital,opsz,wght@0,8..60,300..900;1,8..60,300..900&family=Source+Sans+3:ital,wght@0,300..900;1,300..900&family=DM+Sans:ital,opsz,wght@0,9..40,100..1000;1,9..40,100..1000&family=JetBrains+Mono:ital,wght@0,400;0,500;0,600;1,400&display=swap" rel="stylesheet">
```

### 2. `assets/css/style.css` — Root variable definitions

Replace the entire `:root` block and `@media (prefers-color-scheme: dark)` block with DESIGN.md tokens. Update all references to renamed variables within this file.

### 3. All 15 other CSS files — Variable rename propagation

Find-and-replace across all files:

| Find | Replace |
|------|---------|
| `--bg-card` | `--bg-surface` |
| `--bg-card-hover` | `--bg-surface-hover` |
| `--bg-alt` | `--bg-surface` |
| `--text-secondary` | `--text-muted` |
| `--border` | `--rule` |
| `--verdict-supported` | `--v-supported` |
| `--verdict-partial` | `--v-partial` |
| `--verdict-unsupported` | `--v-unsupported` |
| `--verdict-misleading` | `--v-misleading` |
| `--verdict-unverifiable` | `--v-unverifiable` |
| `--font)` or `--font;` | `--font-body)` or `--font-body;` |
| `--font-heading` | `--font-display` |
| `--bg-nav` | `--bg-surface` |
| `--surface)` | `--bg-surface)` |
| `--surface-raised` | `--bg-surface` |
| `--text-primary` | `--text` |
| `--radius)` | `--radius-md)` |

**Caution with `--font`:** Must use word-boundary matching. `--font-heading` should not be caught by a `--font` replacement. Replace `var(--font)` specifically, not bare `--font`.

### Files with their own dark mode overrides (need updating):
- `overview-detail.css`
- `entity-tracker.css`
- `entity-detail.css`
- `comparison.css`
- `evidence-tracker.css`
- `evidence-detail.css`

These files have `@media (prefers-color-scheme: dark)` blocks with local overrides. Update variable names and colour values in those blocks too.

## Font Loading Strategy

- Load all 5 font families via a single Google Fonts `<link>` tag
- Use `display=swap` for FOUT over FOIT (text visible immediately, fonts swap in)
- Preconnect to both `fonts.googleapis.com` and `fonts.gstatic.com`
- Fallback chain in each `--font-*` variable ensures the site renders with system fonts if Google Fonts fails

## Testing Plan

1. **Visual diff:** Screenshot every page type before and after (homepage, claim tracker, evidence, topic, entity, overview, debate, comparison)
2. **Dark mode:** Check all pages in dark mode
3. **Font loading:** Verify fonts load (DevTools Network tab) and fallbacks render correctly when offline
4. **Verdict badges:** Check all 5 verdict states render with new colours
5. **Responsive:** Check at 375px, 768px, 1280px widths
6. **Contrast:** Verify text contrast meets WCAG AA (4.5:1 for body, 3:1 for large text)

## Risk Assessment

- **Low risk:** Colour/font value changes are purely cosmetic. If anything breaks, revert the commit.
- **Medium risk:** Variable renames could miss an occurrence, leaving `var(--old-name)` references that resolve to the CSS initial value (usually transparent or inherit). Mitigate with grep verification after rename.
- **No data risk:** CSS-only changes. No database, pipeline, or content changes.

## Rollback

Single `git revert` on the implementation commit. All changes are in the site repo, not the main esbvaktin repo.