# ==============================================================================
# 02_eurostat.R — Eurostat data via the eurostat package
# ==============================================================================
# What: Fetches fisheries catch, price levels, trade, agriculture, and GDP
#        data from Eurostat for Iceland and comparison countries.
#
# Why it matters for the EU referendum debate:
#   - Eurostat provides harmonised data across all EU/EEA countries, enabling
#     direct comparison of Iceland with EU members and fellow non-members.
#   - Price level comparisons (PPP) show whether EU membership correlates with
#     higher or lower consumer prices — a central campaign argument.
#   - Trade data reveals how Iceland's EEA-only arrangement compares with full
#     membership in terms of trade volumes and patterns.
#   - Agriculture/GDP data contextualises Iceland's economy relative to peers.
#
# Countries: IS, NO, DK, SE, FI, EU27_2020
# Output:    data/eurostat/
# ==============================================================================

library(eurostat)
library(dplyr)
library(readr)

OUT_DIR <- "data/eurostat"
dir.create(OUT_DIR, recursive = TRUE, showWarnings = FALSE)

COUNTRIES <- c("IS", "NO", "DK", "SE", "FI", "EU27_2020")

# ------------------------------------------------------------------------------
# Helper: safely fetch a Eurostat table and filter for our countries
# ------------------------------------------------------------------------------
fetch_eurostat_table <- function(table_id, label, geo_filter = COUNTRIES) {
  tryCatch({
    message("  Fetching: ", label, " (", table_id, ") ...")
    df <- get_eurostat(table_id, time_format = "num")
    df_filtered <- df |> filter(geo %in% geo_filter)
    message("  OK — ", nrow(df_filtered), " rows (from ", nrow(df), " total)")
    df_filtered
  }, error = function(e) {
    message("  FAILED: ", label, " — ", conditionMessage(e))
    NULL
  })
}

# ==============================================================================
# 1. Fisheries catch — fish_ca_main
# ==============================================================================
# Total fisheries catch by species, country, and year.
# Core to the debate: how does Iceland's catch compare, and what would the
# Common Fisheries Policy mean for access rights?
message("\n=== 1. Fisheries catch ===")
fish_df <- fetch_eurostat_table("fish_ca_main", "Fisheries catch")
if (!is.null(fish_df)) {
  write_csv(fish_df, file.path(OUT_DIR, "fisheries_catch.csv"))
  message("  Saved: fisheries_catch.csv")
}

# ==============================================================================
# 2. Comparative price levels — prc_ppp_ind
# ==============================================================================
# Price level indices (EU27=100) for various product groups.
# Directly addresses: "Would prices go up or down with EU membership?"
message("\n=== 2. Price levels (PPP) ===")
price_df <- fetch_eurostat_table("prc_ppp_ind", "Comparative price levels")
if (!is.null(price_df)) {
  write_csv(price_df, file.path(OUT_DIR, "price_levels_ppp.csv"))
  message("  Saved: price_levels_ppp.csv")
}

# ==============================================================================
# 3. International trade — ext_lt_maineu
# ==============================================================================
# Trade in goods with main partners — shows EU trade share.
message("\n=== 3. Trade data ===")
trade_df <- fetch_eurostat_table("ext_lt_maineu", "Trade with main partners")
if (!is.null(trade_df)) {
  write_csv(trade_df, file.path(OUT_DIR, "trade_main.csv"))
  message("  Saved: trade_main.csv")
}

# ==============================================================================
# 4. Agriculture — aact_eaa01
# ==============================================================================
# Economic accounts for agriculture — output, input, value added.
# Relevant because EU's Common Agricultural Policy would reshape Icelandic
# farming subsidies and market access.
message("\n=== 4. Agriculture accounts ===")
agri_df <- fetch_eurostat_table("aact_eaa01", "Agriculture economic accounts")
if (!is.null(agri_df)) {
  write_csv(agri_df, file.path(OUT_DIR, "agriculture_accounts.csv"))
  message("  Saved: agriculture_accounts.csv")
}

# ==============================================================================
# 5. GDP — nama_10_gdp
# ==============================================================================
# GDP and main components — current prices, chain-linked volumes, per capita.
# Contextualises Iceland's economic weight and growth trajectory.
message("\n=== 5. GDP ===")
gdp_df <- fetch_eurostat_table("nama_10_gdp", "GDP and main components")
if (!is.null(gdp_df)) {
  write_csv(gdp_df, file.path(OUT_DIR, "gdp.csv"))
  message("  Saved: gdp.csv")
}

# ==============================================================================
# Summary
# ==============================================================================
message("\n=== Eurostat fetch complete ===")
csvs <- list.files(OUT_DIR, pattern = "\\.csv$")
message("Files saved to ", OUT_DIR, "/: ", paste(csvs, collapse = ", "))
