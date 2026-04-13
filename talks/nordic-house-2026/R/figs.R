library(tidyverse)
library(dbplyr)
library(DBI)
library(RPostgres)
library(scales)
library(ggtext)

source("R/theme_esb.R")

# NOTE: Run this script inside Positron, not from CLI.
# showtext needs an IDE graphics device for correct Icelandic glyph rendering.

db_url <- readLines("~/esbvaktin/.env") |>
  grep("^DATABASE_URL", x = _, value = TRUE) |>
  sub("DATABASE_URL=", "", x = _)

parsed <- regmatches(
  db_url,
  regexec("://(.+?):(.+?)@(.+?):(\\d+)/(.+)", db_url)
)[[1]]
db_user <- parsed[2]
db_pass <- parsed[3]
db_host <- parsed[4]
db_port <- as.integer(parsed[5])
db_name <- parsed[6]


con <- dbConnect(
  Postgres(),
  dbname = db_name,
  host = db_host,
  port = db_port,
  user = db_user,
  password = db_pass
)

claims <- tbl(con, "claims")
sightings <- tbl(con, "claim_sightings")
evidence <- tbl(con, "evidence")
entities <- tbl(con, "entities")
observations <- tbl(con, "entity_observations")


claims |>
  count(category) |>
  collect() |>
  rename(claims = n) |>
  inner_join(
    evidence |>
      count(topic) |>
      collect() |>
      rename(category = topic, evidence = n)
  ) |>
  pivot_longer(c(claims, evidence), names_to = "type", values_to = "n") |>
  mutate(
    p = n / sum(n),
    .by = type
  ) |>
  select(-n) |>
  pivot_wider(
    names_from = type,
    values_from = p
  ) |>
  filter(
    !category %in%
      c(
        "party_positions",
        "polling",
        "org_positions"
      )
  ) |>
  mutate(
    category = case_match(
      category,
      "eea_eu_law" ~ "EES/ESB löggjöf",
      "sovereignty" ~ "Fullveldi",
      "fisheries" ~ "Sjávarútvegur",
      "precedents" ~ "Fordæmi",
      "trade" ~ "Viðskipti og tollar",
      "currency" ~ "Gjaldmiðill",
      "agriculture" ~ "Landbúnaður",
      "energy" ~ "Orkumál",
      "labour" ~ "Vinnumarkaður",
      "housing" ~ "Húsnæðismál",
      .default = category
    )
  ) |>
  mutate(
    diff = evidence - claims,
    category = fct_reorder(category, claims)
  ) |>
  arrange(category, claims) -> plot_dat

plot_dat |>
  ggplot(aes(
    x = claims,
    xend = 0,
    y = category
  )) +
  geom_segment(
    alpha = 0.5,
    linewidth = 0.2,
    aes(color = category)
  ) +
  geom_point(
    aes(x = claims, color = category),
    size = 3
  ) +
  geom_text(
    data = ~ filter(.x, row_number() %in% c(1:3, 8:10)),
    aes(label = percent(claims, accuracy = 1)),
    hjust = -0.5,
    vjust = 0.5,
    size = 4.5
  ) +
  scale_x_continuous(
    expand = expansion(mult = c(0, 0.1)),
    labels = label_percent(),
    guide = guide_axis(cap = "both")
  ) +
  scale_y_discrete(
    guide = guide_axis(cap = "both")
  ) +
  scale_colour_manual(
    values = esb_highlight(
      c(
        "Húsnæðismál",
        "Vinnumarkaður",
        "Orkumál",
        "EES/ESB löggjöf",
        "Fullveldi",
        "Sjávarútvegur"
      ),
      levels(plot_dat$category)
    )
  ) +
  theme_esb(
    base_size = 18,
    grid_alpha = 0.4,
    grid = "none"
  ) +
  theme(
    axis.line.y = element_blank(),
    legend.position = "none",
    axis.text.y = element_text(family = "Source Serif 4")
  ) +
  labs(
    title = "Nokkur málefni fá langmesta athygli en önnur sitja hjá",
    subtitle = "Skipting fullyrðinga úr umræðunni í málefnaflokka",
    x = "Hlutfall af öllum fullyrðingum",
    y = NULL,
    caption = "Gögn frá esbvaktin.is byggð á 2,101 fullyrðingu úr 333 greinum"
  )

ggsave(
  filename = "talks/nordic-house-2026/figures/topics.pdf",
  width = 8,
  height = 0.5 * 8,
  scale = 1.5,
  dpi = "retina",
  device = cairo_pdf
)

ggsave(
  filename = "talks/nordic-house-2026/figures/topics.svg",
  width = 16,
  height = 9,
  device = svglite::svglite
)

ggsave(
  filename = "talks/nordic-house-2026/figures/topics.png",
  width = 16,
  height = 9,
  dpi = 300,
)


plot_dat <- claims |>
  filter(published == TRUE) |>
  count(category, verdict) |>
  collect() |>
  mutate(
    p = n / sum(n),
    .by = category
  )

plot_dat <- plot_dat |>
  bind_rows(
    plot_dat |>
      summarise(n = sum(n), .by = verdict) |>
      mutate(category = "total", p = n / sum(n))
  ) |>
  filter(
    !category %in% c("party_positions", "polling", "org_positions", "other")
  ) |>
  mutate(
    category = case_match(
      category,
      "eea_eu_law" ~ "EES/ESB löggjöf",
      "sovereignty" ~ "Fullveldi",
      "fisheries" ~ "Sjávarútvegur",
      "precedents" ~ "Fordæmi",
      "trade" ~ "Viðskipti og tollar",
      "currency" ~ "Gjaldmiðill",
      "agriculture" ~ "Landbúnaður",
      "energy" ~ "Orkumál",
      "labour" ~ "Vinnumarkaður",
      "housing" ~ "Húsnæðismál",
      "total" ~ "Samtals",
      .default = category
    ),
    category = fct_reorder(category, (verdict == "supported") * p),
    category = fct_relevel(category, "Samtals", after = Inf),
    verdict = fct_relevel(
      verdict,
      "misleading",
      "unsupported",
      "unverifiable",
      "partially_supported",
      "supported"
    )
  )

# Fade middle verdicts to neutral, keep signal verdicts vivid
vp <- verdict_palette
vp[c("partially_supported", "unverifiable")] <- adjustcolor(
  esb$rule,
  alpha.f = 0.3
)

# Direct labels: % supported inside the green segment
label_dat <- plot_dat |>
  filter(verdict == "supported") |>
  mutate(
    x_pos = p / 2,
    label = percent(p, accuracy = 1)
  )

plot_dat |>
  ggplot(aes(x = p, y = category, fill = verdict)) +
  geom_col(
    colour = esb$bg,
    linewidth = 0.3
  ) +
  geom_text(
    data = label_dat,
    aes(x = x_pos, y = category, label = label),
    inherit.aes = FALSE,
    colour = "white",
    fontface = "bold",
    family = "DM Sans",
    size = 3.5
  ) +
  scale_x_continuous(
    expand = expansion(),
    labels = NULL,
    breaks = NULL
  ) +
  scale_fill_manual(
    values = vp,
    labels = verdict_labels_is,
    guide = guide_legend(reverse = TRUE)
  ) +
  theme_esb(
    base_size = 18,
    grid = "none"
  ) +
  theme(
    legend.position = "top",
    axis.line = element_blank(),
    axis.text.y = element_text(
      family = "Source Serif 4",
      face = ifelse(
        levels(plot_dat$category) == "Samtals",
        "bold",
        "plain"
      )
    )
  ) +
  labs(
    title = "Mjög fáar fullyrðingar eru taldar óstuddar eða úr samhengi",
    subtitle = "Hlutfall fullyrðinga eftir mati, sundurliðað eftir málefnaflokki",
    x = NULL,
    y = NULL,
    fill = NULL,
    caption = "Gögn frá esbvaktin.is byggð á 2.101 fullyrðingu úr 333 greinum"
  )

ggsave(
  filename = "talks/nordic-house-2026/figures/verdicts.pdf",
  width = 8,
  height = 0.5 * 8,
  scale = 1.6,
  device = cairo_pdf
)

ggsave(
  "talks/nordic-house-2026/figures/verdicts.svg",
  width = 16,
  height = 9,
  device = svglite::svglite
)

ggsave(
  "talks/nordic-house-2026/figures/verdicts.png",
  width = 16,
  height = 9,
  scale = 0.6,
  dpi = 300
)
