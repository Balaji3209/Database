"""Central configuration and logging. Values can be overridden through a .env file."""
from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is optional
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if load_dotenv:
    load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data" / "synthetic"
DB_PATH = Path(os.getenv("DBOPTIMA_DB_PATH", PROJECT_ROOT / "data" / "dboptima.db"))
LOG_DIR = PROJECT_ROOT / "logs"
SCHEMA_PATH = PROJECT_ROOT / "dboptima" / "schema.sql"


def _parse_date(value: str | None) -> date:
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            logging.getLogger(__name__).warning("Invalid DBOPTIMA_ASSESSMENT_DATE '%s' - using today", value)
    return date.today()


# Fixed assessment date keeps lifecycle results reproducible for the demo.
ASSESSMENT_DATE: date = _parse_date(os.getenv("DBOPTIMA_ASSESSMENT_DATE", "2026-11-13"))

CURRENCY = "£"
SYNTHETIC_LABEL = "SYNTHETIC DEMO DATA - illustrative only, no real client data"

# Business-rule thresholds (deterministic, reviewable).
EOS_WARNING_MONTHS = 18
CONSOLIDATION_CPU_P95_MAX = 25.0
CONSOLIDATION_MEM_MAX = 55.0
RETIRE_IDLE_DAYS = 90
RIGHTSIZE_TARGET_UTILISATION = 0.70
PG_REPLATFORM_MAX_PLSQL_OBJECTS = 800
AZURE_PCI_LANDING_ZONE_APPROVED = os.getenv("AZURE_PCI_LANDING_ZONE_APPROVED", "false").lower() == "true"

# Azure OpenAI (optional - the app falls back to rules-based explanations).
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")


def azure_openai_configured() -> bool:
    return bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT)


def get_logger(name: str) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("dboptima")
    if not root.handlers:
        root.setLevel(os.getenv("DBOPTIMA_LOG_LEVEL", "INFO"))
        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        fh = logging.FileHandler(LOG_DIR / "dboptima.log", encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(fh)
        root.addHandler(sh)
    return logging.getLogger(f"dboptima.{name}")
