# ==============================================================================
# 00_install_packages.R — Install all required packages for ESBvaktin data fetch
# ==============================================================================
# Run this script once before running any of the data-fetching scripts.
# It installs packages from CRAN and one from GitHub (OECD).
# ==============================================================================

# Helper: install if not already installed
install_if_missing <- function(pkg, ...) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    message("Installing ", pkg, "...")
    install.packages(pkg, ...)
  } else {
    message(pkg, " already installed.")
  }
}

# CRAN packages
cran_packages <- c(
  # Data fetching
  "pxweb",        # Statistics Iceland (Hagstofa) and other Nordic stats offices
  "eurostat",     # Eurostat data
  "WDI",          # World Bank Development Indicators
  "eurlex",       # EU legislation via SPARQL
  "fishstat",     # FAO fisheries statistics


  # HTTP / API

  "httr2",        # Modern HTTP client (Sedlabanki API)
  "jsonlite",     # JSON parsing

  # Data wrangling & I/O
  "dplyr",
  "tidyr",
  "readr",
  "stringr",
  "lubridate",

  # For installing GitHub packages
  "remotes"
)

message("=== Installing CRAN packages ===")
for (pkg in cran_packages) {
  install_if_missing(pkg)
}

# GitHub packages
message("\n=== Installing GitHub packages ===")
if (!requireNamespace("OECD", quietly = TRUE)) {
  message("Installing OECD from GitHub (expersso/OECD)...")
  remotes::install_github("expersso/OECD")
} else {
  message("OECD already installed.")
}

message("\n=== All packages installed ===")
