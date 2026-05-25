"""
ShopStream Customer Data Quality Pipeline
==========================================
Ingests customer data from 4 sources, cleans, deduplicates, validates,
and produces a golden customer record dataset.

Author: Jessica Lartey
Run: python pipeline.py
"""

import pandas as pd
import numpy as np
import re
import json
import requests
from datetime import datetime
from pathlib import Path
import logging
import hashlib

# ── Configure logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("pipeline.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
CONFIG = {
    "input_dir": Path("data/raw"),
    "output_dir": Path("data/processed"),
    "crm_api_url": "https://api.shopstream.example.com/v2/customers",
    "crm_api_key": "sk-xxxx",          # Use environment variable in production
    "valid_regions": ["US", "EU", "APAC"],
    "email_regex": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
    "quality_threshold": 0.95,         # 95% of records must pass each check
    "source_priority": {"crm": 1, "website": 2, "erp": 3, "marketing": 4},
}

for d in [CONFIG["input_dir"], CONFIG["output_dir"]]:
    d.mkdir(parents=True, exist_ok=True)

# ── Synthetic Data Generation ───────────────────────────────────────────────
def generate_synthetic_data():
    """
    Generate 4 source datasets with realistic data quality problems.
    Run this once to create your test data files.
    """
    np.random.seed(42)
    n = 1000  # Smaller for the lab; in production this would be 200K+

    # Shared pool of customers (duplicates will appear across sources)
    emails_pool = [f"customer{i}@{'gmail' if i % 3 == 0 else 'yahoo' if i % 3 == 1 else 'company'}.com"
                   for i in range(800)]
    # Add intentional bad emails
    emails_pool += ["not-an-email", "missing@", "@nodomain.com", "", "double@@sign.com"]

    first_names = ["Maria", "José", "André", "Léa", "François", "Müller", "O'Brien",
                   "John", "Jane", "Mike", "Sarah", "Alex", "Chris", "Pat", "Sam"] * 70
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
                  "Martínez", "Díaz", "López", "González", "Wang", "Kim"] * 84

    regions_messy = (
        ["US", "us", "USA", "united states", "North America"] * 150 +
        ["EU", "eu", "Europe", "EMEA", "europe"] * 150 +
        ["APAC", "apac", "Asia Pacific", "Asia", "AP"] * 100 +
        [None, "", "N/A"] * 80        # 8% null/missing
    )
    np.random.shuffle(regions_messy)

    phones_messy = (
        ["+1 (555) 123-4567", "555.123.4567", "5551234567",
         "+44 20 7946 0958", "020 7946 0958",
         "+81-3-1234-5678", "invalid-phone", None] * 125
    )
    np.random.shuffle(phones_messy)

    # --- SOURCE 1: Website CSV (ISO-8859-1 encoded) ---
    website_df = pd.DataFrame({
        "CustomerEmail": np.random.choice(emails_pool, n),
        "First Name": [first_names[i] for i in np.random.randint(0, len(first_names), n)],
        "Last Name": [last_names[i] for i in np.random.randint(0, len(last_names), n)],
        "Phone": [phones_messy[i % len(phones_messy)] for i in range(n)],
        "Region": [regions_messy[i % len(regions_messy)] for i in range(n)],
        "Registration Date": pd.date_range("2020-01-01", periods=n, freq="4H").strftime("%Y-%m-%d"),
        "OptOut": np.random.choice([0, 1], n, p=[0.85, 0.15]),
    })
    # Add test accounts (should be removed)
    test_accounts = pd.DataFrame({
        "CustomerEmail": [f"test{i}@test.shopstream.com" for i in range(20)],
        "First Name": ["Test"] * 20,
        "Last Name": ["Account"] * 20,
        "Phone": [None] * 20,
        "Region": ["US"] * 20,
        "Registration Date": ["2023-01-01"] * 20,
        "OptOut": [0] * 20,
    })
    website_df = pd.concat([website_df, test_accounts], ignore_index=True)
    website_df.to_csv(CONFIG["input_dir"] / "website_customers.csv",
                      index=False, encoding="iso-8859-1")
    logger.info(f"Generated website CSV: {len(website_df)} records")

    # --- SOURCE 2: CRM Export (JSON Lines format, simulating API response) ---
    crm_records = []
    for i in range(n // 2):  # CRM has a subset — some are duplicates of website
        crm_records.append({
            "id": f"CRM-{i:06d}",
            "email": np.random.choice(emails_pool),
            "profile": {
                "first_name": first_names[np.random.randint(0, len(first_names))],
                "last_name": last_names[np.random.randint(0, len(last_names))],
            },
            "phone": phones_messy[i % len(phones_messy)],
            "region": regions_messy[i % len(regions_messy)],
            "registration_date": f"202{np.random.randint(0,4)}-{np.random.randint(1,13):02d}-01",
            "opt_out": bool(np.random.choice([0, 1], p=[0.85, 0.15])),
            "lifetime_value": round(np.random.uniform(50, 5000), 2),
        })
    crm_path = CONFIG["input_dir"] / "crm_export.json"
    crm_path.write_text(json.dumps({"customers": crm_records}))
    logger.info(f"Generated CRM JSON: {len(crm_records)} records")

    # --- SOURCE 3: ERP Fixed-Width ---
    erp_lines = []
    for i in range(n // 4):
        email = np.random.choice(emails_pool)
        name = f"{first_names[i % len(first_names)]} {last_names[i % len(last_names)]}"
        phone = str(phones_messy[i % len(phones_messy)] or "")
        region = str(regions_messy[i % len(regions_messy)] or "")
        date = f"2019-{np.random.randint(1,13):02d}-01"
        status = np.random.choice(["ACTIV", "INACT"])
        # Fixed-width: pad/truncate each field to exact width
        line = (
            f"{str(i):>10}"
            f"{name:<50}"
            f"{email:<60}"
            f"{phone:<20}"
            f"{region:<5}"
            f"{date:<10}"
            f"{status:<5}"
        )
        erp_lines.append(line)
    (CONFIG["input_dir"] / "erp_customers.txt").write_text("\n".join(erp_lines))
    logger.info(f"Generated ERP fixed-width: {len(erp_lines)} records")

    logger.info("Synthetic data generation complete.")

# Uncomment to generate data:
generate_synthetic_data()

# ingest dummy data and clean it up to a standard format for merging later
def ingest_website_csv(filepath: Path) -> pd.DataFrame:
    """
    Ingest the website registration CSV export.

    Args:
        filepath: Path to the CSV file.

    Returns:
        Cleaned DataFrame with source tag and standardized column names.
    """
    logger.info(f"Ingesting website CSV: {filepath}")

    df = pd.read_csv(
        filepath,
        encoding="iso-8859-1",                          # Handle accented characters
        dtype={"Phone": str},                            # Prevent numeric coercion
        parse_dates=["Registration Date"],
        na_values=["", "N/A", "null", "NULL", "none", "NaN"],
    )

    # Standardize column names to snake_case
    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace(r"[^\w]", "_", regex=True)
        .str.replace(r"_+", "_", regex=True)
        .str.strip("_")
    )

    # Rename to standard schema
    df = df.rename(columns={
        "customeremail": "email",
        "first_name": "first_name",
        "last_name": "last_name",
        "registration_date": "registration_date",
        "optout": "opt_out",
    })

    # Remove test accounts
    test_mask = df["email"].str.contains(r"@test\.shopstream\.com$", na=False, case=False)
    removed = test_mask.sum()
    df = df[~test_mask].copy()
    logger.info(f"  Removed {removed} test accounts")

    df["source"] = "website"
    logger.info(f"  Ingested {len(df)} records from website CSV")
    return df

# ingest the CRM JSON export, which simulates the API response.
def ingest_crm_json(filepath: Path) -> pd.DataFrame:
    """
    Ingest customer data from the CRM JSON export.
    In production, this would call the paginated REST API.

    Args:
        filepath: Path to the JSON export file.

    Returns:
        Flattened DataFrame with source tag.
    """
    logger.info(f"Ingesting CRM JSON: {filepath}")

    raw = json.loads(filepath.read_text())
    df = pd.json_normalize(
        raw["customers"],
        sep="_",            # Flatten nested keys with underscore separator
    )

    # pd.json_normalize turns "profile.first_name" -> "profile_first_name"
    df = df.rename(columns={
        "profile_first_name": "first_name",
        "profile_last_name": "last_name",
        "registration_date": "registration_date",
    })

    df["registration_date"] = pd.to_datetime(df["registration_date"], errors="coerce")
    df["source"] = "crm"

    logger.info(f"  Ingested {len(df)} records from CRM JSON")
    return df

# production version of the CRM ingestion that handles pagination and API calls
def ingest_crm_api(api_url: str, api_key: str) -> pd.DataFrame:
    """
    Ingest customer data from the CRM REST API with pagination.
    Use this in production instead of ingest_crm_json().

    Args:
        api_url: Base URL of the CRM API.
        api_key: Bearer token for authentication.

    Returns:
        Flattened DataFrame with source tag.
    """
    logger.info("Ingesting CRM API (paginated)...")
    all_records = []
    page = 1

    while True:
        response = requests.get(
            api_url,
            headers={"Authorization": f"Bearer {api_key}"},
            params={"page": page, "per_page": 500},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if not data.get("customers"):
            break

        all_records.extend(data["customers"])
        logger.info(f"  Fetched page {page} ({len(data['customers'])} records)")
        page += 1

        if page > data.get("total_pages", 1):
            break

    df = pd.json_normalize(all_records, sep="_")
    df["source"] = "crm"
    logger.info(f"  Ingested {len(df)} records from CRM API")
    return df

# ingest the legacy ERP fixed-width text file
def ingest_erp_fixed_width(filepath: Path) -> pd.DataFrame:
    """
    Ingest the legacy ERP fixed-width text file.
    Column positions defined by ERP system specification v3.2.

    Field layout:
        [0:10]   customer_id
        [10:60]  full_name
        [60:120] email
        [120:140] phone
        [140:145] region_code
        [145:155] registration_date (YYYY-MM-DD)
        [155:160] status

    Args:
        filepath: Path to the fixed-width text file.

    Returns:
        Parsed DataFrame with source tag.
    """
    logger.info(f"Ingesting ERP fixed-width: {filepath}")

    colspecs = [
        (0, 10),     # customer_id
        (10, 60),    # full_name
        (60, 120),   # email
        (120, 140),  # phone
        (140, 145),  # region_code
        (145, 155),  # registration_date
        (155, 160),  # status
    ]
    col_names = ["customer_id", "full_name", "email", "phone",
                 "region_code", "registration_date", "status"]

    df = pd.read_fwf(
        filepath,
        colspecs=colspecs,
        names=col_names,
        dtype=str,                # Read everything as string first
        encoding="utf-8",
    )

    # Strip whitespace from all string columns
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()

    # Split full_name into first/last
    name_split = df["full_name"].str.split(n=1, expand=True)
    df["first_name"] = name_split[0] if 0 in name_split.columns else np.nan
    df["last_name"] = name_split[1] if 1 in name_split.columns else np.nan

    df["registration_date"] = pd.to_datetime(df["registration_date"], errors="coerce")
    df["region"] = df["region_code"]   # Rename for schema alignment
    df["source"] = "erp"

    logger.info(f"  Ingested {len(df)} records from ERP")
    return df

# conbining all sources into a single DataFrame
STANDARD_SCHEMA = [
    "email", "first_name", "last_name", "phone", "region",
    "registration_date", "opt_out", "source"
]

def align_schema(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """
    Align a source DataFrame to the standard schema.
    Missing columns are added as NaN. Extra columns are dropped.
    """
    for col in STANDARD_SCHEMA:
        if col not in df.columns:
            df[col] = np.nan
    return df[STANDARD_SCHEMA].copy()


def ingest_all_sources() -> pd.DataFrame:
    """Ingest all 4 sources and combine into a single raw DataFrame."""
    logger.info("=" * 60)
    logger.info("STEP 1: Data Ingestion")

    frames = []

    website_df = ingest_website_csv(CONFIG["input_dir"] / "website_customers.csv")
    frames.append(align_schema(website_df, "website"))

    crm_df = ingest_crm_json(CONFIG["input_dir"] / "crm_export.json")
    frames.append(align_schema(crm_df, "crm"))

    erp_df = ingest_erp_fixed_width(CONFIG["input_dir"] / "erp_customers.txt")
    frames.append(align_schema(erp_df, "erp"))

    combined = pd.concat(frames, ignore_index=True)
    logger.info(f"Total records combined: {len(combined)}")
    for source in combined["source"].unique():
        count = (combined["source"] == source).sum()
        logger.info(f"  {source}: {count} records")

    return combined

# standardize emails
def standardize_emails(series: pd.Series) -> pd.Series:
    return (
        series
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace(r"\s+", "", regex=True)  # Remove internal spaces
        .replace({"nan": np.nan, "none": np.nan, "": np.nan})
    )

def validate_emails(series: pd.Series) -> pd.Series:
    """Returns a boolean Series: True = valid email format."""
    return series.str.match(CONFIG["email_regex"], na=False)

# phone standardization
def standardize_phone_numbers(series: pd.Series) -> pd.Series:
    """
    Normalize phone numbers: remove formatting, preserve + prefix.

    Examples:
        +1 (555) 123-4567  →  +15551234567
        555.123.4567       →  5551234567
        +44 20 7946 0958   →  +442079460958
        invalid-phone      →  NaN
    """
    def clean_phone(phone):
        if pd.isna(phone) or str(phone).strip() in ("", "nan", "None"):
            return np.nan
        phone = str(phone).strip()
        has_plus = phone.startswith("+")
        digits = re.sub(r"[^\d]", "", phone)
        if len(digits) < 7:         # Too short to be a real phone number
            return np.nan
        return f"+{digits}" if has_plus else digits

    return series.apply(clean_phone)

# name, region and date standardization
REGION_MAP = {
    "us": "US", "usa": "US", "united states": "US", "north america": "US",
    "na": "US", "amer": "US", "america": "US",
    "eu": "EU", "europe": "EU", "emea": "EU", "eur": "EU", "european union": "EU",
    "apac": "APAC", "asia": "APAC", "asia pacific": "APAC",
    "ap": "APAC", "asia-pacific": "APAC",
}

def standardize_names(series: pd.Series) -> pd.Series:
    return (
        series
        .astype(str)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
        .str.title()
        .replace({"Nan": np.nan, "None": np.nan, "": np.nan})
    )

def standardize_regions(series: pd.Series) -> pd.Series:
    return (
        series
        .astype(str)
        .str.strip()
        .str.lower()
        .map(REGION_MAP)             # Unmapped values become NaN
    )

def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all cleaning transformations to the unified DataFrame."""
    logger.info("STEP 2: Cleaning & Standardization")
    df = df.copy()

    df["email_raw"] = df["email"].copy()
    df["email"] = standardize_emails(df["email"])
    df["email_valid"] = validate_emails(df["email"])

    df["first_name"] = standardize_names(df["first_name"])
    df["last_name"] = standardize_names(df["last_name"])
    df["phone"] = standardize_phone_numbers(df["phone"])
    df["region"] = standardize_regions(df["region"])
    df["registration_date"] = pd.to_datetime(df["registration_date"], errors="coerce")

    invalid_emails = (~df["email_valid"]).sum()
    null_regions = df["region"].isna().sum()
    logger.info(f"  Invalid emails: {invalid_emails}")
    logger.info(f"  Null regions after standardization: {null_regions}")
    logger.info(f"  Records after cleaning: {len(df)}")
    return df

