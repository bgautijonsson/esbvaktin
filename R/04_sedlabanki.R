# ==============================================================================
# 04_sedlabanki.R — Central Bank of Iceland (Sedlabanki) REST API
# ==============================================================================
# What: Fetches EUR/ISK exchange rates and key interest rates from the
#        Central Bank of Iceland's data portal API.
#
# Why it matters for the EU referendum debate:
#   - EUR/ISK exchange rate history shows the krona's volatility, especially
#     during the 2008 crash (ISK lost ~50% against EUR). Currency stability
#     is the strongest pro-EU/euro argument.
#   - Interest rate differentials between Iceland and the ECB illustrate the
#     cost of independent monetary policy — Iceland's rates are persistently
#     higher, meaning more expensive mortgages and business loans.
#   - Both datasets are essential for the "euro adoption" sub-debate: joining
#     the EU would eventually mean adopting the euro.
#
# API:    https://api.sedlabanki.is/dataportal/api
# Output: data/sedlabanki/
# ==============================================================================

library(httr2)
library(jsonlite)
library(dplyr)
library(readr)
library(lubridate)

OUT_DIR <- "data/sedlabanki"
dir.create(OUT_DIR, recursive = TRUE, showWarnings = FALSE)

API_BASE <- "https://api.sedlabanki.is/dataportal/api"

# ------------------------------------------------------------------------------
# Helper: fetch time series from Sedlabanki API
# ------------------------------------------------------------------------------
fetch_sedlabanki <- function(series_id, label, date_from = "2000-01-01",
                             date_to = format(Sys.Date(), "%Y-%m-%d")) {
  tryCatch({
    message("  Fetching: ", label, " (series: ", series_id, ") ...")

    url <- paste0(API_BASE, "/timeseries/", series_id)

    resp <- request(url) |>
      req_url_query(dateFrom = date_from, dateTo = date_to) |>
      req_headers(Accept = "application/json") |>
      req_timeout(60) |>
      req_perform()

    body <- resp_body_string(resp)
    data <- fromJSON(body)

    # The API returns data in various structures; handle flexibly
    if (is.data.frame(data)) {
      df <- data
    } else if (is.list(data) && "data" %in% names(data)) {
      df <- as.data.frame(data$data)
    } else if (is.list(data) && "values" %in% names(data)) {
      df <- as.data.frame(data$values)
    } else {
      # Try to coerce whatever we got
      df <- as.data.frame(data)
    }

    message("  OK — ", nrow(df), " rows")
    df
  }, error = function(e) {
    message("  FAILED: ", label, " — ", conditionMessage(e))
    NULL
  })
}

# ------------------------------------------------------------------------------
# Alternative approach: try the /data endpoint with query parameters
# ------------------------------------------------------------------------------
fetch_sedlabanki_v2 <- function(series_ids, label,
                                 date_from = "2000-01-01",
                                 date_to = format(Sys.Date(), "%Y-%m-%d")) {
  tryCatch({
    message("  Fetching (v2): ", label, " ...")

    # Try the bulk data endpoint
    url <- paste0(API_BASE, "/data")

    body <- list(
      seriesIds = as.list(series_ids),
      dateFrom = date_from,
      dateTo = date_to
    )

    resp <- request(url) |>
      req_body_json(body) |>
      req_headers(Accept = "application/json") |>
      req_timeout(60) |>
      req_perform()

    data <- resp_body_json(resp)

    # Parse the response into a data frame
    rows <- lapply(data, function(series) {
      if (is.list(series) && "values" %in% names(series)) {
        vals <- series$values
        data.frame(
          series_id = series$id %||% NA,
          date = sapply(vals, function(v) v$date %||% v$d %||% NA),
          value = sapply(vals, function(v) v$value %||% v$v %||% NA),
          stringsAsFactors = FALSE
        )
      } else {
        NULL
      }
    })

    df <- bind_rows(rows)
    message("  OK — ", nrow(df), " rows")
    df
  }, error = function(e) {
    message("  FAILED (v2): ", label, " — ", conditionMessage(e))
    NULL
  })
}

# ==============================================================================
# 1. EUR/ISK exchange rate
# ==============================================================================
# The central rate that drives the entire euro adoption debate.
message("\n=== 1. EUR/ISK exchange rate ===")

# Try several possible series IDs — the API documentation is sparse
eur_isk_series <- c("EUR", "EURISK", "EUR/ISK", "1", "IS01")

eur_df <- NULL
for (sid in eur_isk_series) {
  eur_df <- fetch_sedlabanki(sid, paste("EUR/ISK via series", sid))
  if (!is.null(eur_df) && nrow(eur_df) > 0) break
}

# If individual series didn't work, try the v2 endpoint
if (is.null(eur_df) || nrow(eur_df) == 0) {
  eur_df <- fetch_sedlabanki_v2(eur_isk_series[1:2], "EUR/ISK (v2)")
}

# Fallback: try the exchange rate endpoint directly
if (is.null(eur_df) || nrow(eur_df) == 0) {
  tryCatch({
    message("  Trying exchange rate endpoint directly...")

    # Some central bank APIs use /exchangerates or /market
    endpoints <- c(
      paste0(API_BASE, "/exchangerates?currency=EUR&dateFrom=2000-01-01"),
      paste0(API_BASE, "/currencies/EUR?dateFrom=2000-01-01"),
      paste0(API_BASE, "/market/exchangerate?dateFrom=2000-01-01")
    )

    for (ep in endpoints) {
      tryCatch({
        resp <- request(ep) |>
          req_headers(Accept = "application/json") |>
          req_timeout(30) |>
          req_perform()
        data <- fromJSON(resp_body_string(resp))
        if (is.data.frame(data) && nrow(data) > 0) {
          eur_df <- data
          message("  OK via: ", ep)
          break
        }
      }, error = function(e) NULL)
    }
  }, error = function(e) {
    message("  All EUR/ISK approaches failed: ", conditionMessage(e))
  })
}

if (!is.null(eur_df) && nrow(eur_df) > 0) {
  write_csv(eur_df, file.path(OUT_DIR, "eur_isk_exchange_rate.csv"))
  message("  Saved: eur_isk_exchange_rate.csv")
} else {
  message("  WARNING: Could not fetch EUR/ISK exchange rate.")
  message("  The API structure may have changed. Check:")
  message("  https://api.sedlabanki.is/dataportal/api/swagger")
}

# ==============================================================================
# 2. Key interest rates
# ==============================================================================
# Sedlabanki's policy rate — compare with ECB to show the cost of sovereignty.
message("\n=== 2. Key interest rates ===")

rate_series <- c("INTRATE", "POLICYRATE", "policy_rate", "2", "IS02")

rate_df <- NULL
for (sid in rate_series) {
  rate_df <- fetch_sedlabanki(sid, paste("Interest rate via series", sid))
  if (!is.null(rate_df) && nrow(rate_df) > 0) break
}

if (is.null(rate_df) || nrow(rate_df) == 0) {
  rate_df <- fetch_sedlabanki_v2(rate_series[1:2], "Interest rates (v2)")
}

if (!is.null(rate_df) && nrow(rate_df) > 0) {
  write_csv(rate_df, file.path(OUT_DIR, "key_interest_rates.csv"))
  message("  Saved: key_interest_rates.csv")
} else {
  message("  WARNING: Could not fetch interest rate data.")
}

# ==============================================================================
# 3. Try listing available series (for documentation / future use)
# ==============================================================================
message("\n=== Listing available series (for reference) ===")
tryCatch({
  list_endpoints <- c(
    paste0(API_BASE, "/timeseries"),
    paste0(API_BASE, "/series"),
    paste0(API_BASE, "/catalog")
  )

  for (ep in list_endpoints) {
    tryCatch({
      resp <- request(ep) |>
        req_headers(Accept = "application/json") |>
        req_timeout(15) |>
        req_perform()
      catalog <- fromJSON(resp_body_string(resp))

      if (is.data.frame(catalog)) {
        write_csv(catalog, file.path(OUT_DIR, "available_series.csv"))
        message("  Saved series catalog: available_series.csv")
        message("  Use this to find correct series IDs for future runs.")
        break
      }
    }, error = function(e) NULL)
  }
}, error = function(e) {
  message("  Could not list available series.")
})

# ==============================================================================
# Summary
# ==============================================================================
message("\n=== Sedlabanki fetch complete ===")
csvs <- list.files(OUT_DIR, pattern = "\\.csv$")
message("Files saved to ", OUT_DIR, "/: ", paste(csvs, collapse = ", "))
if (length(csvs) == 0) {
  message("NOTE: The Sedlabanki API may require exploring the Swagger docs at:")
  message("  https://api.sedlabanki.is/dataportal/api/swagger")
  message("to find the correct endpoints and series IDs.")
}
