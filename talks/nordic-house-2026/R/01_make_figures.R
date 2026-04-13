library(tidyverse)
library(showtext)

# ── ESBvaktin Design Tokens ──────────────────────────────────────────────────
bg <- "#F5F0E8"
text_c <- "#1C1A17"
accent <- "#0D6A63"
muted <- "#6B6358"
rule <- "#D5CFC5"

# Verdict colours
verdict_colours <- c(
  "Studd"           = "#0D6A63",
  "Að hluta studd"  = "#6BA8A2",
  "Villandi"        = "#C4553A",
  "Óstudd"          = "#8B3A2A",
  "Ósannreynanleg"  = "#B8B0A3"
)

# ── Fonts ────────────────────────────────────────────────────────────────────
font_add_google("Fraunces", "Fraunces")
font_add_google("Source Serif 4", "Source Serif 4")
font_add_google("DM Sans", "DM Sans")
showtext_auto()

fig_dir <- here::here("talks/nordic-house-2026/figures")
data_dir <- here::here("talks/nordic-house-2026/R/data")

# ── Data ─────────────────────────────────────────────────────────────────────
topics <- read_csv(file.path(data_dir, "topic_distribution.csv"),
  show_col_types = FALSE
)
verdicts <- read_csv(file.path(data_dir, "verdict_distribution.csv"),
  show_col_types = FALSE
)


# ═══════════════════════════════════════════════════════════════════════════════
# Figure 1: Topic Distribution — "Hvar er umræðan?"
# ═══════════════════════════════════════════════════════════════════════════════

highlight_topics <- c("Húsnæðismál", "Orka", "Vinnumarkaður")

p1 <- topics |>
  mutate(
    label_is = fct_reorder(label_is, sightings),
    fill = if_else(label_is %in% highlight_topics, "highlight", "normal")
  ) |>
  ggplot(aes(x = sightings, y = label_is)) +
  geom_col(aes(fill = fill), width = 0.6) +
  geom_text(
    aes(label = sightings, colour = fill),
    hjust = -0.3, size = 5, family = "DM Sans", fontface = "bold"
  ) +
  scale_fill_manual(values = c("highlight" = accent, "normal" = muted), guide = "none") +
  scale_colour_manual(values = c("highlight" = accent, "normal" = muted), guide = "none") +
  scale_x_continuous(expand = expansion(mult = c(0, 0.15))) +
  labs(x = NULL, y = NULL) +
  theme_minimal(base_family = "Source Serif 4", base_size = 18) +
  theme(
    plot.background = element_rect(fill = bg, colour = NA),
    panel.background = element_rect(fill = bg, colour = NA),
    panel.grid.major.y = element_blank(),
    panel.grid.minor = element_blank(),
    panel.grid.major.x = element_line(colour = rule, linewidth = 0.3),
    axis.text.y = element_text(colour = text_c, size = 16, family = "Source Serif 4"),
    axis.text.x = element_blank(),
    plot.margin = margin(10, 20, 10, 10)
  )

ggsave(file.path(fig_dir, "topic_distribution.svg"), p1,
  width = 10, height = 6, bg = bg
)
ggsave(file.path(fig_dir, "topic_distribution.png"), p1,
  width = 10, height = 6, dpi = 300, bg = bg
)


# ═══════════════════════════════════════════════════════════════════════════════
# Figure 2: Evidence Gap — "Hvað vantar?"
# Sightings per evidence entry (ratio)
# ═══════════════════════════════════════════════════════════════════════════════

gap_data <- topics |>
  filter(evidence > 0) |>
  mutate(
    label_is = fct_reorder(label_is, ratio),
    fill = if_else(label_is %in% highlight_topics, "highlight", "normal")
  )

p2 <- gap_data |>
  ggplot(aes(x = ratio, y = label_is)) +
  geom_segment(
    aes(x = 0, xend = ratio, y = label_is, yend = label_is, colour = fill),
    linewidth = 1.2
  ) +
  geom_point(aes(colour = fill), size = 5) +
  geom_text(
    aes(label = paste0(ratio, "×"), colour = fill),
    hjust = -0.4, size = 5, family = "DM Sans", fontface = "bold"
  ) +
  scale_colour_manual(values = c("highlight" = accent, "normal" = muted), guide = "none") +
  scale_x_continuous(expand = expansion(mult = c(0, 0.2))) +
  labs(
    x = NULL, y = NULL,
    caption = "Tilvísanir í umræðunni á hverja heimildafærslu"
  ) +
  theme_minimal(base_family = "Source Serif 4", base_size = 18) +
  theme(
    plot.background = element_rect(fill = bg, colour = NA),
    panel.background = element_rect(fill = bg, colour = NA),
    panel.grid.major.y = element_blank(),
    panel.grid.minor = element_blank(),
    panel.grid.major.x = element_line(colour = rule, linewidth = 0.3),
    axis.text.y = element_text(colour = text_c, size = 16, family = "Source Serif 4"),
    axis.text.x = element_blank(),
    plot.caption = element_text(
      colour = muted, size = 13, family = "Source Serif 4",
      hjust = 0, margin = margin(t = 10)
    ),
    plot.margin = margin(10, 20, 10, 10)
  )

ggsave(file.path(fig_dir, "evidence_gap.svg"), p2,
  width = 10, height = 6, bg = bg
)
ggsave(file.path(fig_dir, "evidence_gap.png"), p2,
  width = 10, height = 6, dpi = 300, bg = bg
)


# ═══════════════════════════════════════════════════════════════════════════════
# Figure 3: Verdict Quality — "Ófullkomin, ekki röng"
# Single stacked bar
# ═══════════════════════════════════════════════════════════════════════════════

verdict_order <- c("Studd", "Að hluta studd", "Villandi", "Óstudd", "Ósannreynanleg")

# Build cumulative positions for label placement
verdict_df <- verdicts |>
  mutate(
    label_is = factor(label_is, levels = verdict_order)
  ) |>
  arrange(label_is) |>
  mutate(
    xmax = cumsum(pct),
    xmin = xmax - pct,
    xmid = (xmin + xmax) / 2
  )

p3 <- verdict_df |>
  ggplot() +
  geom_rect(
    aes(xmin = xmin, xmax = xmax, ymin = 0, ymax = 1, fill = label_is),
    colour = bg, linewidth = 0.5
  ) +
  geom_text(
    data = verdict_df |> filter(pct >= 5),
    aes(
      x = xmid, y = 0.5,
      label = paste0(label_is, "\n", pct, "%")
    ),
    colour = "white", size = 7, family = "DM Sans", fontface = "bold",
    lineheight = 1.2
  ) +
  geom_text(
    data = verdict_df |> filter(pct < 5, pct >= 1),
    aes(x = xmid, y = 0.5, label = paste0(pct, "%")),
    colour = "white", size = 5, family = "DM Sans", fontface = "bold"
  ) +
  scale_fill_manual(
    values = verdict_colours,
    breaks = verdict_order,
    name = NULL
  ) +
  scale_x_continuous(expand = c(0, 0)) +
  scale_y_continuous(expand = c(0, 0)) +
  labs(x = NULL, y = NULL) +
  theme_void(base_family = "Source Serif 4", base_size = 18) +
  theme(
    plot.background = element_rect(fill = bg, colour = NA),
    panel.background = element_rect(fill = bg, colour = NA),
    legend.position = "bottom",
    legend.text = element_text(colour = text_c, size = 14, family = "Source Serif 4"),
    legend.key.size = unit(0.8, "cm"),
    legend.margin = margin(t = 20),
    plot.margin = margin(30, 20, 10, 20)
  ) +
  guides(fill = guide_legend(nrow = 1))

ggsave(file.path(fig_dir, "verdict_quality.svg"), p3,
  width = 12, height = 5, bg = bg
)
ggsave(file.path(fig_dir, "verdict_quality.png"), p3,
  width = 12, height = 5, dpi = 300, bg = bg
)

cat("All 3 figures generated in", fig_dir, "\n")
