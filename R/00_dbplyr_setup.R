# ── ESBvaktin Database — dbplyr Setup ────────────────────────────────────────
#
# Example script for querying the ESBvaktin PostgreSQL database from R.
# See also: Metill vault → ESB/Knowledge/Data/ESBvaktin Database Guide.md
#
# Prerequisites:
#   install.packages(c("DBI", "RPostgres", "dbplyr", "tidyverse"))

library(tidyverse)
library(dbplyr)
library(DBI)
library(RPostgres)

# ── Connection ───────────────────────────────────────────────────────────────
# Parse credentials from the project .env file

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

# ── Lazy Tables ──────────────────────────────────────────────────────────────
# These don't load data — they create SQL references for dplyr chains.

claims <- tbl(con, "claims")
sightings <- tbl(con, "claim_sightings")
evidence <- tbl(con, "evidence")
entities <- tbl(con, "entities")
observations <- tbl(con, "entity_observations")

# ── Analytical Views ─────────────────────────────────────────────────────────
# Pre-built aggregations in the database. Use directly — no joins needed.

balance <- tbl(con, "balance_audit") # verdict × speaker_stance
weekly <- tbl(con, "verdict_weekly_trend") # weekly new claims by verdict + cumulative
velocity <- tbl(con, "claim_velocity") # weekly new claims by topic
frequency <- tbl(con, "claim_frequency") # claims ranked by sighting count
outlets <- tbl(con, "outlet_verdicts") # verdict × source_domain
utilisation <- tbl(con, "evidence_utilisation") # evidence citation counts
stale <- tbl(con, "stale_evidence") # evidence not verified in 90+ days


# ═══════════════════════════════════════════════════════════════════════════════
# EXAMPLE QUERIES
# ═══════════════════════════════════════════════════════════════════════════════

# ── Topic distribution (sightings per topic) ─────────────────────────────────

topic_sightings <- claims |>
  inner_join(sightings, by = c("id" = "claim_id")) |>
  filter(published == TRUE) |>
  count(category, sort = TRUE) |>
  collect()


# ── Verdict distribution ─────────────────────────────────────────────────────

verdict_dist <- claims |>
  filter(published == TRUE) |>
  count(verdict) |>
  mutate(pct = n / sum(n, na.rm = TRUE) * 100) |>
  collect()


# ── Evidence gap — sightings per evidence entry, by topic ────────────────────

sighting_counts <- claims |>
  inner_join(sightings, by = c("id" = "claim_id")) |>
  filter(published == TRUE) |>
  count(category, name = "sightings") |>
  collect()

evidence_counts <- evidence |>
  count(topic, name = "evidence_n") |>
  collect()

evidence_gap <- sighting_counts |>
  inner_join(evidence_counts, by = c("category" = "topic")) |>
  mutate(ratio = round(sightings / evidence_n, 1)) |>
  arrange(desc(ratio))


# ── Weekly claim volume by topic ─────────────────────────────────────────────
# Uses the pre-built claim_velocity view — no joins needed.

weekly_topics <- velocity |> collect()


# ── Balance audit — verdicts by speaker stance ───────────────────────────────

balance_data <- balance |> collect()


# ── Verdicts by outlet ───────────────────────────────────────────────────────

outlet_data <- outlets |> collect()


# ── Most-observed entities ───────────────────────────────────────────────────

top_entities <- observations |>
  filter(dismissed == FALSE) |>
  count(entity_id, sort = TRUE) |>
  left_join(
    entities |> select(id, canonical_name, entity_type, stance),
    by = c("entity_id" = "id")
  ) |>
  collect()


# ── Most-repeated claims ────────────────────────────────────────────────────

top_claims <- frequency |>
  filter(published == TRUE) |>
  head(20) |>
  collect()


# ── Topic diversity score (Shannon entropy, normalised) ──────────────────────
# This one needs R-side computation after collect().

diversity <- claims |>
  inner_join(sightings, by = c("id" = "claim_id")) |>
  filter(published == TRUE, !is.na(source_date)) |>
  mutate(week = floor_date(source_date, "week")) |>
  count(week, category) |>
  collect() |>
  group_by(week) |>
  mutate(p = n / sum(n)) |>
  summarise(
    entropy = -sum(p * log(p)),
    diversity = entropy / log(n_distinct(category)),
    .groups = "drop"
  )


# ═══════════════════════════════════════════════════════════════════════════════
# THEME, PALETTES, SCALES, AND LABELS — see R/theme_esb.R
# ═══════════════════════════════════════════════════════════════════════════════

source(file.path(
  dirname(sys.frame(1)$ofile %||% "R/00_dbplyr_setup.R"),
  "theme_esb.R"
))

# ── Cleanup ──────────────────────────────────────────────────────────────────

# dbDisconnect(con)
