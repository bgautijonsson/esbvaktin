# ==============================================================================
# 01_hagstofa.R — Statistics Iceland (Hagstofa Islands) via pxweb
# ==============================================================================
# What: Fetches fisheries catch data, trade flows by country/commodity,
#        and food/consumer price indices from Statistics Iceland's PX-Web API.
#
# Why it matters for the EU referendum debate:
#   - Fisheries are Iceland's most EU-sensitive sector. Catch data shows the
#     scale of what's at stake — the common fisheries policy is the single
#     biggest concern in accession negotiations.
#   - Trade flows reveal Iceland's actual trading partners and commodity
#     dependence. The EU is already Iceland's largest trade partner via the
#     EEA; full membership would change tariff structures.
#   - Price indices matter because EU opponents argue membership would raise
#     food prices (via CAP alignment), while proponents argue it would lower
#     them (via tariff removal on imports).
#
# API base: https://px.hagstofa.is/pxen/api/v1/en
# Output:   data/hagstofa/
# ==============================================================================

library(pxweb)
library(dplyr)
library(readr)

OUT_DIR <- "data/hagstofa"
dir.create(OUT_DIR, recursive = TRUE, showWarnings = FALSE)

API_BASE <- "https://px.hagstofa.is/pxen/api/v1/en"

# ------------------------------------------------------------------------------
# Helper: safely fetch a pxweb table
# ------------------------------------------------------------------------------
safe_pxweb_get <- function(url, query, label) {
  tryCatch({
    message("  Fetching: ", label, " ...")
    result <- pxweb_get(url = url, query = query)
    df <- as.data.frame(result, column.name.type = "text", variable.value.type = "text")
    message("  OK — ", nrow(df), " rows")
    df
  }, error = function(e) {
    message("  FAILED: ", label, " — ", conditionMessage(e))
    NULL
  })
}

# ==============================================================================
# 1. Fisheries — Total catch by species
# ==============================================================================
# Table path: Atvinnuvegir/sjavarutvegur/aflagreidslur/UTA02001.px
# This table contains total catch of Icelandic vessels by species and year.
# If this exact path fails, we try alternatives.
message("\n=== Fisheries catch data ===")

fisheries_paths <- c(

  # Total catch by species
  paste0(API_BASE, "/Atvinnuvegir/sjavarutvegur/aflagreidslur/UTA02001.px"),
  # Catch by fishing area
  paste0(API_BASE, "/Atvinnuvegir/sjavarutvegur/afli/UTA01000.px"),
  # Catch value
  paste0(API_BASE, "/Atvinnuvegir/sjavarutvegur/aflaverðmæti/UTA03101.px")
)

# For the first table, request all years and species with a broad query
fisheries_query <- list(
  "Species" = c("*"),
  "Year" = c("*")
)

fisheries_df <- NULL
for (path in fisheries_paths) {
  # First try to get metadata to understand the table structure
  tryCatch({
    message("  Trying: ", basename(path))
    meta <- pxweb_get(url = path)

    # Build query from metadata — request all values for all variables
    query <- setNames(
      lapply(meta$variables, function(v) v$values),
      sapply(meta$variables, function(v) v$code)
    )

    fisheries_df <- safe_pxweb_get(path, query, paste("fisheries from", basename(path)))
    if (!is.null(fisheries_df)) break
  }, error = function(e) {
    message("  Could not access: ", basename(path), " — ", conditionMessage(e))
  })
}

if (!is.null(fisheries_df)) {
  write_csv(fisheries_df, file.path(OUT_DIR, "fisheries_catch.csv"))
  message("  Saved: fisheries_catch.csv")
} else {
  message("  WARNING: Could not fetch any fisheries table.")
}

# ==============================================================================
# 2. Trade flows — Exports and imports by country and commodity
# ==============================================================================
# Tables under Efnahagur/utanrikisverslun/
message("\n=== Trade flow data ===")

trade_paths <- c(
  # Trade by country
  paste0(API_BASE, "/Efnahagur/utanrikisverslun/1_voruvidskipti/UTA06200.px"),
  # Trade by commodity (SITC)
  paste0(API_BASE, "/Efnahagur/utanrikisverslun/1_voruvidskipti/UTA06100.px"),
  # External trade overview
  paste0(API_BASE, "/Efnahagur/utanrikisverslun/UTA06001.px")
)

trade_df <- NULL
for (path in trade_paths) {
  tryCatch({
    message("  Trying: ", basename(path))
    meta <- pxweb_get(url = path)

    query <- setNames(
      lapply(meta$variables, function(v) v$values),
      sapply(meta$variables, function(v) v$code)
    )

    trade_df <- safe_pxweb_get(path, query, paste("trade from", basename(path)))
    if (!is.null(trade_df)) break
  }, error = function(e) {
    message("  Could not access: ", basename(path), " — ", conditionMessage(e))
  })
}

if (!is.null(trade_df)) {
  write_csv(trade_df, file.path(OUT_DIR, "trade_flows.csv"))
  message("  Saved: trade_flows.csv")
} else {
  message("  WARNING: Could not fetch any trade table.")
}

# ==============================================================================
# 3. Price indices — Consumer prices / food prices
# ==============================================================================
# Tables under Verdlag/
message("\n=== Price index data ===")

price_paths <- c(
  # Consumer price index
  paste0(API_BASE, "/Verdlag/neysluverd/1_neysluverd/VIS01000.px"),
  # CPI by category
  paste0(API_BASE, "/Verdlag/neysluverd/1_neysluverd/VIS01001.px"),
  # Food price index
  paste0(API_BASE, "/Verdlag/neysluverd/VIS01100.px")
)

price_df <- NULL
for (path in price_paths) {
  tryCatch({
    message("  Trying: ", basename(path))
    meta <- pxweb_get(url = path)

    query <- setNames(
      lapply(meta$variables, function(v) v$values),
      sapply(meta$variables, function(v) v$code)
    )

    price_df <- safe_pxweb_get(path, query, paste("prices from", basename(path)))
    if (!is.null(price_df)) break
  }, error = function(e) {
    message("  Could not access: ", basename(path), " — ", conditionMessage(e))
  })
}

if (!is.null(price_df)) {
  write_csv(price_df, file.path(OUT_DIR, "price_indices.csv"))
  message("  Saved: price_indices.csv")
} else {
  message("  WARNING: Could not fetch any price table.")
}

# ==============================================================================
# Summary
# ==============================================================================
message("\n=== Hagstofa fetch complete ===")
csvs <- list.files(OUT_DIR, pattern = "\\.csv$")
message("Files saved to ", OUT_DIR, "/: ", paste(csvs, collapse = ", "))
if (length(csvs) == 0) {
  message("NOTE: No CSVs were produced. The Hagstofa API table paths may have")
  message("changed. Use pxweb_interactive() to browse the API and update paths.")
}
