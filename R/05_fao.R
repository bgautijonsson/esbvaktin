# ==============================================================================
# 05_fao.R — FAO fisheries data via the fishstat package
# ==============================================================================
# What: Fetches capture production data from FAO FishStat for Iceland and
#        key comparison countries (Norway, Denmark, UK, EU aggregate).
#
# Why it matters for the EU referendum debate:
#   - Iceland is one of the world's most fisheries-dependent nations. FAO data
#     provides the international context that Hagstofa/Eurostat cannot: how
#     Iceland's catch compares globally, not just within Europe.
#   - Norway is the critical comparator — also outside the EU, also a major
#     fishing nation, also in the EEA. Their fisheries arrangements show what's
#     possible outside the Common Fisheries Policy.
#   - Denmark (including Greenland/Faroes historically) shows the EU member
#     experience with fisheries management.
#   - The UK post-Brexit fisheries outcome is directly relevant: did leaving
#     the CFP deliver the promised benefits?
#
# Countries: Iceland, Norway, Denmark, United Kingdom, EU aggregate
# Output:    data/fao/
# ==============================================================================

library(dplyr)
library(readr)

OUT_DIR <- "data/fao"
dir.create(OUT_DIR, recursive = TRUE, showWarnings = FALSE)

# Check fishstat is available
if (!requireNamespace("fishstat", quietly = TRUE)) {
  message("ERROR: fishstat package not installed.")
  message("Install with: install.packages('fishstat')")
  stop("fishstat package required. Run R/00_install_packages.R first.")
}

library(fishstat)

COUNTRIES <- c("Iceland", "Norway", "Denmark", "United Kingdom",
               "Faroe Islands")

# ==============================================================================
# 1. Capture production — the core fisheries dataset
# ==============================================================================
message("\n=== 1. FAO capture production ===")

capture_df <- tryCatch({
  message("  Fetching capture production data...")
  message("  (This may take a while — FAO datasets are large)")

  # fishstat::capture_production() fetches the FAO Global Capture Production
  # database. The function downloads and caches the full dataset.
  df <- capture_production()

  message("  Full dataset: ", nrow(df), " rows")

  # Filter for our countries of interest
  # Column names vary by fishstat version; try common patterns
  country_col <- intersect(
    names(df),
    c("country", "Country", "COUNTRY", "country_name",
      "country_name_en", "reporting_country")
  )

  if (length(country_col) > 0) {
    col <- country_col[1]
    message("  Using country column: ", col)

    df_filtered <- df |>
      filter(.data[[col]] %in% COUNTRIES |
               grepl("Iceland|Norway|Denmark|United Kingdom|Faroe", .data[[col]],
                     ignore.case = TRUE))

    message("  Filtered: ", nrow(df_filtered), " rows for target countries")
    df_filtered
  } else {
    message("  WARNING: Could not identify country column. Saving full dataset.")
    message("  Columns: ", paste(names(df), collapse = ", "))
    df
  }
}, error = function(e) {
  message("  FAILED: ", conditionMessage(e))

  # Fallback: try alternative fishstat functions
  tryCatch({
    message("  Trying alternative fishstat functions...")

    # Some versions use different function names
    if (exists("fs_capture", where = asNamespace("fishstat"))) {
      message("  Trying fs_capture()...")
      df <- fishstat::fs_capture()
      return(df)
    }

    # Try listing available datasets
    if (exists("fishstat_datasets", where = asNamespace("fishstat"))) {
      datasets <- fishstat::fishstat_datasets()
      message("  Available datasets: ", paste(datasets, collapse = ", "))
    }

    NULL
  }, error = function(e2) {
    message("  Fallback also failed: ", conditionMessage(e2))
    NULL
  })
})

if (!is.null(capture_df) && nrow(capture_df) > 0) {
  write_csv(capture_df, file.path(OUT_DIR, "fao_capture_production.csv"))
  message("  Saved: fao_capture_production.csv")
} else {
  message("  WARNING: Could not fetch FAO capture production data.")
}

# ==============================================================================
# 2. Aquaculture production (if available)
# ==============================================================================
# Relevant because Norway's aquaculture (salmon farming) is a major industry
# that operates outside the CFP — a model Iceland could follow.
message("\n=== 2. FAO aquaculture production ===")

aqua_df <- tryCatch({
  message("  Fetching aquaculture production data...")

  # Try the aquaculture function
  if (exists("aquaculture_production", where = asNamespace("fishstat"))) {
    df <- aquaculture_production()
  } else if (exists("fs_aquaculture", where = asNamespace("fishstat"))) {
    df <- fishstat::fs_aquaculture()
  } else {
    message("  No aquaculture function found in fishstat.")
    NULL
  }
}, error = function(e) {
  message("  FAILED: ", conditionMessage(e))
  NULL
})

if (!is.null(aqua_df)) {
  # Try to filter for our countries
  country_col <- intersect(
    names(aqua_df),
    c("country", "Country", "COUNTRY", "country_name",
      "country_name_en", "reporting_country")
  )

  if (length(country_col) > 0) {
    col <- country_col[1]
    aqua_filtered <- aqua_df |>
      filter(grepl("Iceland|Norway|Denmark|United Kingdom|Faroe",
                   .data[[col]], ignore.case = TRUE))
    message("  Filtered: ", nrow(aqua_filtered), " rows")
    write_csv(aqua_filtered, file.path(OUT_DIR, "fao_aquaculture_production.csv"))
  } else {
    write_csv(aqua_df, file.path(OUT_DIR, "fao_aquaculture_production.csv"))
  }
  message("  Saved: fao_aquaculture_production.csv")
}

# ==============================================================================
# Summary
# ==============================================================================
message("\n=== FAO fetch complete ===")
csvs <- list.files(OUT_DIR, pattern = "\\.csv$")
message("Files saved to ", OUT_DIR, "/: ", paste(csvs, collapse = ", "))
if (length(csvs) == 0) {
  message("NOTE: The fishstat package may need updating or the FAO API may")
  message("be temporarily unavailable. Check: https://www.fao.org/fishery/en")
}
