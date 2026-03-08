# ==============================================================================
# 07_eurlex.R — EU legislation data via the eurlex package
# ==============================================================================
# What: Queries EUR-Lex (the EU's legal database) via SPARQL to count
#        EU regulations and directives in force, and EEA-relevant acts.
#
# Why it matters for the EU referendum debate:
#   - Iceland already implements ~75% of EU legislation via the EEA Agreement,
#     but has no vote on it. Quantifying the legislative acquis shows voters
#     the actual volume of law they'd be voting on (or are already subject to).
#   - Comparing total EU acts vs EEA-incorporated acts makes the "sovereignty
#     cost" concrete rather than abstract.
#   - Tracking the growth of EU legislation over time illustrates the
#     ever-expanding scope of what EEA membership entails.
#   - Directives vs regulations distinction matters: regulations apply directly,
#     directives require transposition. Full membership means both apply; EEA
#     requires transposition of both into national law.
#
# Note: EUR-Lex SPARQL endpoint can be slow. Be patient.
# Output: data/eurlex/
# ==============================================================================

library(dplyr)
library(readr)

OUT_DIR <- "data/eurlex"
dir.create(OUT_DIR, recursive = TRUE, showWarnings = FALSE)

# Check eurlex is available
if (!requireNamespace("eurlex", quietly = TRUE)) {
  message("ERROR: eurlex package not installed.")
  message("Install with: install.packages('eurlex')")
  stop("eurlex package required. Run R/00_install_packages.R first.")
}

library(eurlex)

# ==============================================================================
# 1. Count of regulations and directives currently in force
# ==============================================================================
message("\n=== 1. EU regulations in force ===")

regulations_df <- tryCatch({
  message("  Querying EUR-Lex for regulations in force...")
  message("  (SPARQL queries can be slow — may take 1-2 minutes)")

  # elx_make_query builds SPARQL queries for EUR-Lex
  # resource_type: "regulation" = regulations, "directive" = directives
  # include_force: TRUE to check if in force
  regs <- elx_make_query(
    resource_type = "regulation",
    include_date = TRUE,
    include_force = TRUE
  ) |>
    elx_run_query()

  message("  OK — ", nrow(regs), " regulations found")
  regs
}, error = function(e) {
  message("  FAILED: ", conditionMessage(e))
  NULL
})

if (!is.null(regulations_df) && nrow(regulations_df) > 0) {
  write_csv(regulations_df, file.path(OUT_DIR, "eu_regulations.csv"))
  message("  Saved: eu_regulations.csv")

  # Summary stats
  if ("force" %in% names(regulations_df)) {
    in_force <- sum(regulations_df$force == TRUE | regulations_df$force == "true",
                    na.rm = TRUE)
    message("  In force: ", in_force, " / ", nrow(regulations_df))
  }
}

# ==============================================================================
# 2. Directives in force
# ==============================================================================
message("\n=== 2. EU directives in force ===")

directives_df <- tryCatch({
  message("  Querying EUR-Lex for directives...")

  dirs <- elx_make_query(
    resource_type = "directive",
    include_date = TRUE,
    include_force = TRUE
  ) |>
    elx_run_query()

  message("  OK — ", nrow(dirs), " directives found")
  dirs
}, error = function(e) {
  message("  FAILED: ", conditionMessage(e))
  NULL
})

if (!is.null(directives_df) && nrow(directives_df) > 0) {
  write_csv(directives_df, file.path(OUT_DIR, "eu_directives.csv"))
  message("  Saved: eu_directives.csv")

  if ("force" %in% names(directives_df)) {
    in_force <- sum(directives_df$force == TRUE | directives_df$force == "true",
                    na.rm = TRUE)
    message("  In force: ", in_force, " / ", nrow(directives_df))
  }
}

# ==============================================================================
# 3. EEA-relevant acts
# ==============================================================================
# These are the acts that Iceland must implement under the EEA Agreement.
# The EEA relevance marker in EUR-Lex identifies these.
message("\n=== 3. EEA-relevant acts ===")

eea_df <- tryCatch({
  message("  Querying EUR-Lex for EEA-relevant acts...")

  # Try querying with EEA relevance filter
  # elx_make_query supports include_eea parameter in some versions
  eea <- elx_make_query(
    resource_type = "any",
    include_date = TRUE,
    include_force = TRUE,
    include_eea = TRUE
  ) |>
    elx_run_query()

  # Filter for EEA-relevant ones
  if ("eea_relevant" %in% names(eea)) {
    eea <- eea |> filter(eea_relevant == TRUE | eea_relevant == "true")
  }

  message("  OK — ", nrow(eea), " EEA-relevant acts found")
  eea
}, error = function(e) {
  message("  FAILED: ", conditionMessage(e))

  # Fallback: try a custom SPARQL query for EEA-relevant acts
  tryCatch({
    message("  Trying custom SPARQL query for EEA-relevant acts...")

    sparql_query <- '
    PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
    PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

    SELECT DISTINCT ?work ?date ?title WHERE {
      ?work cdm:resource_legal_is_about_concept_directory-code ?subject .
      ?subject skos:prefLabel ?subjectLabel .
      ?work cdm:resource_legal_date_document ?date .
      OPTIONAL { ?work cdm:expression_title ?title }
      FILTER(CONTAINS(STR(?subjectLabel), "EEA"))
    }
    ORDER BY DESC(?date)
    LIMIT 5000
    '

    eea <- elx_run_query(sparql_query)
    message("  OK (custom query) — ", nrow(eea), " rows")
    eea
  }, error = function(e2) {
    message("  Custom query also failed: ", conditionMessage(e2))
    NULL
  })
})

if (!is.null(eea_df) && nrow(eea_df) > 0) {
  write_csv(eea_df, file.path(OUT_DIR, "eea_relevant_acts.csv"))
  message("  Saved: eea_relevant_acts.csv")
}

# ==============================================================================
# 4. Summary: legislation counts by year and type
# ==============================================================================
message("\n=== 4. Building summary statistics ===")

summary_rows <- list()

if (!is.null(regulations_df) && nrow(regulations_df) > 0) {
  # Count by year if date column exists
  date_col <- intersect(names(regulations_df), c("date", "date_document"))
  if (length(date_col) > 0) {
    reg_by_year <- regulations_df |>
      mutate(year = as.integer(substr(.data[[date_col[1]]], 1, 4))) |>
      filter(!is.na(year)) |>
      group_by(year) |>
      summarise(n_regulations = n(), .groups = "drop")
    summary_rows[["regulations"]] <- reg_by_year
  }
}

if (!is.null(directives_df) && nrow(directives_df) > 0) {
  date_col <- intersect(names(directives_df), c("date", "date_document"))
  if (length(date_col) > 0) {
    dir_by_year <- directives_df |>
      mutate(year = as.integer(substr(.data[[date_col[1]]], 1, 4))) |>
      filter(!is.na(year)) |>
      group_by(year) |>
      summarise(n_directives = n(), .groups = "drop")
    summary_rows[["directives"]] <- dir_by_year
  }
}

if (length(summary_rows) > 0) {
  summary_df <- Reduce(
    function(x, y) full_join(x, y, by = "year"),
    summary_rows
  ) |>
    arrange(year)

  write_csv(summary_df, file.path(OUT_DIR, "legislation_by_year.csv"))
  message("  Saved: legislation_by_year.csv")
}

# ==============================================================================
# Summary
# ==============================================================================
message("\n=== EUR-Lex fetch complete ===")
csvs <- list.files(OUT_DIR, pattern = "\\.csv$")
message("Files saved to ", OUT_DIR, "/: ", paste(csvs, collapse = ", "))
if (length(csvs) == 0) {
  message("NOTE: The EUR-Lex SPARQL endpoint may be down or rate-limiting.")
  message("Try again later, or check: https://eur-lex.europa.eu/content/help/data-reuse/sparql-endpoint.html")
}
