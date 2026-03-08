# ==============================================================================
# 06_worldbank.R — World Bank data via the WDI package
# ==============================================================================
# What: Fetches key economic indicators from the World Bank's World Development
#        Indicators for Iceland and Nordic comparison countries.
#
# Why it matters for the EU referendum debate:
#   - GDP per capita (PPP) shows living standards — Iceland consistently ranks
#     among the highest globally. Would EU membership help or hurt this?
#   - Trade as % of GDP quantifies openness; Iceland is very trade-dependent,
#     making trade policy (EEA vs full EU) materially important.
#   - FDI inflows show investor confidence and integration into global capital
#     markets — relevant to the "EU membership attracts investment" argument.
#   - Inflation and unemployment are quality-of-life indicators that voters
#     care about; comparing Iceland's volatile record with eurozone stability
#     is a recurring campaign theme.
#   - GDP growth trends show whether EEA-only status has been economically
#     advantageous compared with full EU members.
#
# Countries: IS, NO, DK, SE, FI
# Years:     2000–2025
# Output:    data/worldbank/
# ==============================================================================

library(WDI)
library(dplyr)
library(readr)

OUT_DIR <- "data/worldbank"
dir.create(OUT_DIR, recursive = TRUE, showWarnings = FALSE)

COUNTRIES <- c("IS", "NO", "DK", "SE", "FI")
START_YEAR <- 2000
END_YEAR <- 2025

# Define indicators to fetch
INDICATORS <- c(
  gdp_per_capita_ppp  = "NY.GDP.PCAP.PP.CD",   # GDP per capita, PPP (current intl $)
  trade_pct_gdp       = "NE.TRD.GNFS.ZS",      # Trade (% of GDP)
  fdi_net_inflows     = "BX.KLT.DINV.CD.WD",    # FDI, net inflows (BoP, current US$)
  inflation_cpi       = "FP.CPI.TOTL.ZG",       # Inflation, consumer prices (annual %)
  unemployment        = "SL.UEM.TOTL.ZS",       # Unemployment, total (% of labour force)
  gdp_growth          = "NY.GDP.MKTP.KD.ZG"     # GDP growth (annual %)
)

# ==============================================================================
# Fetch all indicators in one call
# ==============================================================================
message("\n=== Fetching World Bank indicators ===")
message("  Countries: ", paste(COUNTRIES, collapse = ", "))
message("  Years: ", START_YEAR, "–", END_YEAR)
message("  Indicators: ", length(INDICATORS))

all_df <- tryCatch({
  message("  Downloading...")
  df <- WDI(
    country   = COUNTRIES,
    indicator = INDICATORS,
    start     = START_YEAR,
    end       = END_YEAR,
    extra     = TRUE   # Include region, income group, etc.
  )
  message("  OK — ", nrow(df), " rows")
  df
}, error = function(e) {
  message("  FAILED bulk download: ", conditionMessage(e))
  message("  Trying indicators individually...")
  NULL
})

# If bulk download failed, try one by one
if (is.null(all_df)) {
  individual_dfs <- list()

  for (i in seq_along(INDICATORS)) {
    indicator_name <- names(INDICATORS)[i]
    indicator_code <- INDICATORS[i]

    tryCatch({
      message("  Fetching: ", indicator_name, " (", indicator_code, ") ...")
      df <- WDI(
        country   = COUNTRIES,
        indicator = indicator_code,
        start     = START_YEAR,
        end       = END_YEAR
      )
      # Rename the indicator column to a consistent name
      names(df)[names(df) == indicator_code] <- indicator_name
      individual_dfs[[indicator_name]] <- df
      message("    OK — ", nrow(df), " rows")
    }, error = function(e) {
      message("    FAILED: ", conditionMessage(e))
    })
  }

  # Merge all individual results
  if (length(individual_dfs) > 0) {
    all_df <- individual_dfs[[1]]
    if (length(individual_dfs) > 1) {
      for (i in 2:length(individual_dfs)) {
        join_cols <- intersect(names(all_df), c("iso2c", "country", "year"))
        all_df <- full_join(all_df, individual_dfs[[i]], by = join_cols)
      }
    }
    message("  Merged: ", nrow(all_df), " rows, ", ncol(all_df), " columns")
  }
}

# ==============================================================================
# Save combined dataset
# ==============================================================================
if (!is.null(all_df) && nrow(all_df) > 0) {
  write_csv(all_df, file.path(OUT_DIR, "wdi_indicators.csv"))
  message("\n  Saved: wdi_indicators.csv")

  # Also save a summary showing data coverage
  coverage <- all_df |>
    group_by(country) |>
    summarise(
      year_min = min(year, na.rm = TRUE),
      year_max = max(year, na.rm = TRUE),
      n_years  = n_distinct(year),
      .groups  = "drop"
    )
  message("\n  Data coverage:")
  print(coverage)
} else {
  message("\n  WARNING: No World Bank data was fetched.")
}

# ==============================================================================
# Also save individual indicator CSVs for convenience
# ==============================================================================
if (!is.null(all_df) && nrow(all_df) > 0) {
  message("\n=== Saving individual indicator files ===")

  for (i in seq_along(INDICATORS)) {
    indicator_name <- names(INDICATORS)[i]

    # Check if this column exists in the data
    if (indicator_name %in% names(all_df)) {
      ind_df <- all_df |>
        select(any_of(c("iso2c", "country", "year", indicator_name))) |>
        filter(!is.na(.data[[indicator_name]]))

      if (nrow(ind_df) > 0) {
        fname <- paste0(indicator_name, ".csv")
        write_csv(ind_df, file.path(OUT_DIR, fname))
        message("  Saved: ", fname, " (", nrow(ind_df), " rows)")
      }
    }
  }
}

# ==============================================================================
# Summary
# ==============================================================================
message("\n=== World Bank fetch complete ===")
csvs <- list.files(OUT_DIR, pattern = "\\.csv$")
message("Files saved to ", OUT_DIR, "/: ", paste(csvs, collapse = ", "))
