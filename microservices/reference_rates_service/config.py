import os
from pathlib import Path

# Base directory for storing SQLite ledger database
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Database connection URL (SQLite journal ledger)
DATABASE_URL = os.getenv("REFERENCE_RATES_DB_URL", f"sqlite:///{DATA_DIR / 'reference_rates_ledger.db'}")

# Official Central Bank API Endpoints
# 1. SOFR: New York Fed REST API
# Using last/50.json as primary high-yield endpoint with search.json fallback
NY_FED_SOFR_PRIMARY_URL = "https://markets.newyorkfed.org/api/rates/secured/sofr/last/50.json"
NY_FED_SOFR_SEARCH_URL = "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json"

# 2. EURIBOR: European Central Bank (ECB) SDMX REST API
# Primary target requested: FM.D.U2.EUR.RT.MM.EURIBOR3M.HSTA with fallback to monthly average series
ECB_SDMX_EURIBOR_PRIMARY_URL = "https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.RT.MM.EURIBOR3M.HSTA"
ECB_SDMX_EURIBOR_FALLBACK_URL = "https://data-api.ecb.europa.eu/service/data/FM/M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA"

# Microservice Server Settings
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5006
