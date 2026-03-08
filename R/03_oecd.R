# ==============================================================================
# 03_oecd.R — OECD data via the OECD package (GitHub version)
# ==============================================================================
# What: Fetches comparative price levels, CPI, and GDP per capita from OECD
#        for Iceland and Nordic comparison countries.
#
# Why it matters for the EU referendum debate:
#   - OECD comparative price levels show Iceland's cost of living vs peers,
#     independent of Eurostat framing. Iceland is consistently among the most
#     expensive OECD countries — EU membership's impact on prices is contested.
#   - CPI trends show inflation trajectories; the ISK's volatility vs euro
#     stability is a key pro-EU argument.
#   - GDP per capita in PPP terms contextualises living standards.
#
# IMPORTANT: The CRAN OECD package broke with the 2024 API changes.
#            Use: remotes::install_github("expersso/OECD")
#
# Countries: ISL, NOR, DNK, SWE, FIN
# Output:    data/oecd/
# ==============================================================================

library(dplyr)
library(readr)

OUT_DIR <- "data/oecd"
dir.create(OUT_DIR, recursive = TRUE, showWarnings = FALSE)

# Check that the OECD package is available
if (!requireNamespace("OECD", quietly = TRUE)) {
  message("ERROR: OECD package not installed.")
  message("Install from GitHub: remotes::install_github('expersso/OECD')")
  message("The CRAN version is broken since the 2024 OECD API changes.")
  stop("OECD package required. Run R/00_install_packages.R first.")
}

library(OECD)

COUNTRIES <- c("ISL", "NOR", "DNK", "SWE", "FIN")
COUNTRIES_FILTER <- paste(COUNTRIES, collapse = "+")

# ------------------------------------------------------------------------------
# Helper: safely fetch OECD dataset
# ------------------------------------------------------------------------------
safe_oecd_get <- function(dataset_id, filter_expr, label, ...) {
  tryCatch({
    message("  Fetching: ", label, " (", dataset_id, ") ...")
    df <- get_dataset(dataset_id, filter = filter_expr, ...)
    message("  OK — ", nrow(df), " rows")
    df
  }, error = function(e) {
    message("  FAILED: ", label, " — ", conditionMessage(e))
    # Try without filter as fallback
    tryCatch({
      message("  Retrying without filter...")
      df <- get_dataset(dataset_id)
      df_filtered <- df |> filter(
        if ("LOCATION" %in% names(df)) LOCATION %in% COUNTRIES
        else if ("COU" %in% names(df)) COU %in% COUNTRIES
        else TRUE
      )
      message("  OK (filtered client-side) — ", nrow(df_filtered), " rows")
      df_filtered
    }, error = function(e2) {
      message("  FAILED again: ", conditionMessage(e2))
      NULL
    })
  })
}

# ==============================================================================
# 1. Comparative Price Levels (CPL)
# ==============================================================================
# Price levels relative to OECD average = 100. Shows how expensive Iceland is.
message("\n=== 1. Comparative price levels ===")
cpl_df <- safe_oecd_get(
  "CPL",
  filter = list(COUNTRIES, c("FOOD", "TOTGD", "CD01", "HOUS")),
  label = "Comparative price levels"
)
if (!is.null(cpl_df)) {
  write_csv(cpl_df, file.path(OUT_DIR, "comparative_price_levels.csv"))
  message("  Saved: comparative_price_levels.csv")
}

# ==============================================================================
# 2. Consumer Price Index (CPI) — PRICES_CPI
# ==============================================================================
# CPI all items + food subcategory. Shows inflation history.
message("\n=== 2. Consumer Price Index ===")
cpi_df <- safe_oecd_get(
  "PRICES_CPI",
  filter = list(COUNTRIES, c("CPALTT01", "CPGRLE01")),
  label = "CPI"
)
if (!is.null(cpi_df)) {
  write_csv(cpi_df, file.path(OUT_DIR, "cpi.csv"))
  message("  Saved: cpi.csv")
}

# ==============================================================================
# 3. GDP per capita — SNA_TABLE1
# ==============================================================================
# GDP per head, current prices, current PPPs.
message("\n=== 3. GDP per capita ===")
gdp_df <- safe_oecd_get(
  "SNA_TABLE1",
  filter = list(COUNTRIES, c("GDPVD", "GDPPOP")),
  label = "GDP per capita"
)
if (!is.null(gdp_df)) {
  write_csv(gdp_df, file.path(OUT_DIR, "gdp_per_capita.csv"))
  message("  Saved: gdp_per_capita.csv")
}

# ==============================================================================
# Summary
# ==============================================================================
message("\n=== OECD fetch complete ===")
csvs <- list.files(OUT_DIR, pattern = "\\.csv$")
message("Files saved to ", OUT_DIR, "/: ", paste(csvs, collapse = ", "))
if (length(csvs) == 0) {
  message("NOTE: The OECD API can be unreliable. Try running again, or check")
  message("https://data-explorer.oecd.org/ for updated dataset IDs.")
}
