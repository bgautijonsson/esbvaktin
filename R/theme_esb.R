# ── ESBvaktin ggplot2 Theme ──────────────────────────────────────────────────
#
# Matches the esbvaktin.is design system (see DESIGN.md).
# Source this file before plotting: source("R/theme_esb.R")
#
# Fonts: Fraunces (display), Source Serif 4 (body/subtitle), DM Sans (data)
# Palette: warm cream bg, teal accent, muted editorial verdict colours

library(ggplot2)
library(showtext)

# ── Fonts ────────────────────────────────────────────────────────────────────

font_add_google("Fraunces", "Fraunces")
font_add_google("Source Serif 4", "Source Serif 4")
font_add_google("Source Sans 3", "Source Sans 3")
font_add_google("DM Sans", "DM Sans")
showtext_auto()


# ═══════════════════════════════════════════════════════════════════════════════
# COLOUR PALETTES
# ═══════════════════════════════════════════════════════════════════════════════

# ── Core colours ─────────────────────────────────────────────────────────────

esb <- list(
  bg = "#F5F0E8",
  bg_surface = "#E8E2D5",
  text = "#1C1A17",
  text_muted = "#6B6358",
  accent = "#0D6A63",
  rule = "#D5CFC5",
  rule_strong = "#B8B0A3"
)

# Backward compat with 00_dbplyr_setup.R
esb_colours <- esb

# ── Verdict palette ──────────────────────────────────────────────────────────

verdict_palette <- c(
  supported = "#2E6A4F",
  partially_supported = "#8A6A1E",
  unsupported = "#A63A2B",
  misleading = "#8B3D5E",
  unverifiable = "#6B6358"
)

# ── Evidence source type palette ─────────────────────────────────────────────

evidence_palette <- c(
  official_statistics = "#06B6D4",
  legal_text = "#8B5CF6",
  academic_paper = "#10B981",
  expert_analysis = "#F59E0B",
  international_org = "#06B6D4",
  parliamentary_record = "#F97316"
)

# ── Political party palette ──────────────────────────────────────────────────

party_palette <- c(
  XD = "#003897",
  S = "#E30613",
  B = "#007A33",
  M = "#003459",
  C = "#FF8C00",
  V = "#00843D",
  P = "#660099",
  F = "#C5A800",
  HR = "#009FE3",
  other = "#6B7280"
)

# ── General categorical palette ──────────────────────────────────────────────

esb_categorical <- c(
  "#0D6A63",
  "#2E6A4F",
  "#8A6A1E",
  "#A63A2B",
  "#8B3D5E",
  "#06B6D4",
  "#8B5CF6",
  "#F59E0B",
  "#F97316",
  "#6B6358"
)


# ═══════════════════════════════════════════════════════════════════════════════
# ICELANDIC LABELS
# ═══════════════════════════════════════════════════════════════════════════════

verdict_labels_is <- c(
  supported = "Studd",
  partially_supported = "Studd a\u00f0 hluta",
  unsupported = "\u00d3studd",
  misleading = "\u00dearfnast samhengis",
  unverifiable = "\u00d3sannreynanleg"
)

topic_labels_is <- c(
  agriculture = "Landb\u00fana\u00f0ur",
  currency = "Gjaldmi\u00f0ill",
  eea_eu_law = "EES-r\u00e9ttur",
  energy = "Orka",
  fisheries = "Sj\u00e1var\u00fatvegur",
  housing = "H\u00fasn\u00e6\u00f0ism\u00e1l",
  labour = "Vinnumarka\u00f0ur",
  org_positions = "Samt\u00f6k",
  other = "Anna\u00f0",
  party_positions = "Flokksm\u00e1l",
  polling = "Kannanir",
  precedents = "Ford\u00e6mi",
  sovereignty = "Fullveldi",
  trade = "Vi\u00f0skipti"
)


# ═══════════════════════════════════════════════════════════════════════════════
# THEME
# ═══════════════════════════════════════════════════════════════════════════════

#' ESBvaktin ggplot2 theme
#'
#' Matches the esbvaktin.is design system: warm cream background, Fraunces
#' display headings, DM Sans data labels, light grid.
#'
#' @param base_size Base font size in points (default 14)
#' @param grid Which grid lines to show: "xy" (default), "x", "y", or "none"
#' @param grid_alpha Grid line opacity, 0 (invisible) to 1 (full). Default 0.5.
theme_esb <- function(base_size = 14, grid = "xy", grid_alpha = 0.5) {
  title <- esb$text
  subtitle <- esb$text_muted
  caption <- esb$text_muted
  axis_text <- esb$text
  axis_line_col <- esb$rule_strong
  strip_bg <- esb$bg_surface
  strip_text <- esb$text
  background <- esb$bg

  header_font <- "Fraunces"
  ui_font <- "Source Sans 3"
  body_font <- "DM Sans"

  half_line <- base_size / 2

  grid_col <- adjustcolor(esb$rule, alpha.f = grid_alpha)
  grid_line <- element_line(colour = grid_col, linewidth = 0.3)

  grid_x <- if (grid %in% c("xy", "x")) grid_line else element_blank()
  grid_y <- if (grid %in% c("xy", "y")) grid_line else element_blank()

  theme_classic() %+replace%
    theme(
      text = element_text(
        family = body_font,
        size = base_size
      ),
      plot.title = element_text(
        face = "bold",
        family = header_font,
        colour = title,
        size = rel(1.4),
        hjust = 0,
        margin = margin(t = half_line, r = 0, b = half_line, l = 0)
      ),
      plot.subtitle = element_text(
        family = "Source Serif 4",
        colour = subtitle,
        size = rel(1.0),
        hjust = 0,
        margin = margin(t = 0, r = 0, b = half_line, l = 0)
      ),
      plot.caption = element_text(
        family = ui_font,
        colour = caption,
        hjust = 1,
        size = rel(0.6),
        margin = margin(t = half_line, r = 0, b = 0, l = 0)
      ),
      plot.caption.position = "panel",
      panel.background = element_rect(
        fill = background,
        colour = NA
      ),
      plot.background = element_rect(
        fill = background,
        colour = NA
      ),
      panel.grid = element_blank(),
      panel.grid.major.x = grid_x,
      panel.grid.major.y = grid_y,
      axis.title = element_text(
        family = ui_font,
        colour = caption,
        size = rel(0.8),
        margin = margin(t = half_line / 2, r = half_line / 2, b = 0, l = 0)
      ),
      axis.text = element_text(
        size = rel(0.7),
        colour = axis_text
      ),
      axis.line = element_line(
        colour = axis_line_col
      ),
      axis.ticks = element_blank(),
      strip.background = element_rect(
        fill = strip_bg,
        colour = axis_line_col,
        linewidth = 0.8
      ),
      strip.text = element_text(
        size = rel(0.7),
        margin = margin(
          t = half_line / 4,
          r = half_line / 4,
          b = half_line / 4,
          l = half_line / 4
        ),
        colour = strip_text
      ),
      plot.margin = margin(
        t = half_line,
        r = half_line,
        b = half_line,
        l = half_line
      ),
      legend.background = element_rect(
        fill = background,
        colour = NA
      )
    )
}


# ═══════════════════════════════════════════════════════════════════════════════
# SCALE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

#' Verdict colour/fill scales
#' @param lang "is" for Icelandic labels, "en" for English
#' @param ... passed to scale_*_manual
scale_colour_verdict <- function(lang = "is", ...) {
  labels <- if (lang == "is") verdict_labels_is else waiver()
  scale_colour_manual(values = verdict_palette, labels = labels, ...)
}

scale_fill_verdict <- function(lang = "is", ...) {
  labels <- if (lang == "is") verdict_labels_is else waiver()
  scale_fill_manual(values = verdict_palette, labels = labels, ...)
}

#' Political party colour/fill scales
scale_colour_party <- function(...) {
  scale_colour_manual(values = party_palette, ...)
}

scale_fill_party <- function(...) {
  scale_fill_manual(values = party_palette, ...)
}

#' Evidence source type colour/fill scales
scale_colour_evidence <- function(...) {
  scale_colour_manual(values = evidence_palette, ...)
}

scale_fill_evidence <- function(...) {
  scale_fill_manual(values = evidence_palette, ...)
}

#' General categorical colour/fill scales (up to 10 values)
scale_colour_esb <- function(...) {
  scale_colour_manual(values = esb_categorical, ...)
}

scale_fill_esb <- function(...) {
  scale_fill_manual(values = esb_categorical, ...)
}

#' Sequential teal ramp for continuous data
scale_colour_esb_seq <- function(...) {
  scale_colour_gradient(low = "#D5CFC5", high = "#0D6A63", ...)
}

scale_fill_esb_seq <- function(...) {
  scale_fill_gradient(low = "#D5CFC5", high = "#0D6A63", ...)
}

#' Diverging scale: unsupported red <- neutral -> supported green
scale_colour_esb_div <- function(midpoint = 0, ...) {
  scale_colour_gradient2(
    low = "#A63A2B",
    mid = "#D5CFC5",
    high = "#2E6A4F",
    midpoint = midpoint,
    ...
  )
}

scale_fill_esb_div <- function(midpoint = 0, ...) {
  scale_fill_gradient2(
    low = "#A63A2B",
    mid = "#D5CFC5",
    high = "#2E6A4F",
    midpoint = midpoint,
    ...
  )
}


# ═══════════════════════════════════════════════════════════════════════════════
# HIGHLIGHT UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

#' Build a highlight palette: one value gets the accent colour, everything else
#' gets a muted grey. This is the single most effective data viz technique
#' (Knaflic, Burn-Murdoch, Healy all converge on it).
#'
#' @param highlight Value(s) to highlight (character vector)
#' @param levels All possible values in the variable
#' @param accent Highlight colour (default: ESBvaktin teal)
#' @param grey Muted colour for non-highlighted values (default: rule colour)
#' @return Named character vector suitable for scale_*_manual(values = ...)
#'
#' @examples
#' ggplot(d, aes(x, y, colour = category)) +
#'   geom_line(linewidth = c(0.5, 1.2)[1 + (d$category == "fisheries")]) +
#'   scale_colour_manual(values = esb_highlight("fisheries", unique(d$category)))
esb_highlight <- function(
  highlight,
  levels,
  accent = esb$accent,
  grey = esb$rule
) {
  cols <- setNames(rep(grey, length(levels)), levels)
  cols[highlight] <- accent
  cols
}
