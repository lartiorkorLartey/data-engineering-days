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

# Deduplication and merging logic
def deduplicate_customers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Deduplicate customer records across sources.

    Strategy:
        1. Sort by source priority (CRM is most trusted)
        2. Group by standardized email (primary key)
        3. Within each group, merge fields: take first non-null value
           from the highest-priority source
        4. GDPR compliance: if ANY source has opt_out=True, mark as opted out

    Args:
        df: Cleaned DataFrame with 'email', 'email_valid', 'source' columns.

    Returns:
        Deduplicated DataFrame with provenance tracking.
    """
    logger.info("STEP 3: Deduplication")
    initial_count = len(df)

    df["source_priority"] = df["source"].map(CONFIG["source_priority"]).fillna(99)
    df = df.sort_values("source_priority")

    def merge_group(group: pd.DataFrame) -> pd.Series:
        """Merge duplicate records, preferring higher-priority sources."""
        best = group.iloc[0].copy()

        # For key fields, take the first non-null value from priority-sorted group
        for col in ["phone", "region", "first_name", "last_name", "registration_date"]:
            if col in group.columns and pd.isna(best.get(col)):
                non_null = group[col].dropna()
                if len(non_null) > 0:
                    best[col] = non_null.iloc[0]

        # GDPR: opt-out from any source is final
        if "opt_out" in group.columns:
            best["opt_out"] = group["opt_out"].fillna(0).astype(bool).any()

        # Provenance tracking
        best["sources"] = ",".join(group["source"].unique())
        best["source_count"] = len(group["source"].unique())

        return best

    # Deduplicate valid-email records on email key
    valid_mask = df["email_valid"] == True
    valid_df = df[valid_mask]
    invalid_df = df[~valid_mask]

    deduped = (
        valid_df
        .groupby("email", sort=False)
        .apply(merge_group, include_groups=False)
        .reset_index(drop=True)
    )

    # Append invalid-email records (cannot be deduplicated by email)
    result = pd.concat([deduped, invalid_df], ignore_index=True)

    removed = initial_count - len(result)
    logger.info(f"  Records before deduplication: {initial_count}")
    logger.info(f"  Duplicate records removed: {removed}")
    logger.info(f"  Records after deduplication: {len(result)}")
    return result

# validate data quality
class DataQualityValidator:
    """
    Runs configurable quality checks and produces a pass/fail report.
    Designed to be reusable across projects — just swap the checks.
    """

    def __init__(self, df: pd.DataFrame, threshold: float = 0.95):
        self.df = df
        self.threshold = threshold
        self.results = []
        self.n = len(df)

    def _record(self, check: str, description: str, failed: int, total: int) -> dict:
        pass_rate = 1 - (failed / total) if total > 0 else 1.0
        result = {
            "check": check,
            "description": description,
            "total": total,
            "passed": total - failed,
            "failed": failed,
            "pass_rate": round(pass_rate, 4),
            "status": "PASS" if pass_rate >= self.threshold else "FAIL",
        }
        self.results.append(result)
        return result

    def check_not_null(self, column: str, description: str) -> dict:
        failed = int(self.df[column].isna().sum())
        return self._record(f"NOT NULL: {column}", description, failed, self.n)

    def check_unique(self, column: str, description: str) -> dict:
        non_null = self.df[column].dropna()
        failed = int(non_null.duplicated().sum())
        return self._record(f"UNIQUE: {column}", description, failed, len(non_null))

    def check_regex(self, column: str, pattern: str, description: str) -> dict:
        non_null = self.df[column].dropna()
        failed = int((~non_null.str.match(pattern, na=False)).sum())
        return self._record(f"REGEX: {column}", description, failed, len(non_null))

    def check_values_in_set(self, column: str, valid_values: list, description: str) -> dict:
        non_null = self.df[column].dropna()
        failed = int((~non_null.isin(valid_values)).sum())
        return self._record(f"VALUES IN SET: {column}", description, failed, len(non_null))

    def check_date_range(self, column: str, min_date: str, max_date: str, description: str) -> dict:
        non_null = self.df[column].dropna()
        in_range = non_null.between(pd.Timestamp(min_date), pd.Timestamp(max_date))
        failed = int((~in_range).sum())
        return self._record(f"DATE RANGE: {column}", description, failed, len(non_null))

    def generate_report(self) -> pd.DataFrame:
        report = pd.DataFrame(self.results)
        logger.info("=" * 60)
        logger.info("DATA QUALITY REPORT")
        logger.info("=" * 60)
        for r in self.results:
            icon = "✓" if r["status"] == "PASS" else "✗"
            logger.info(
                f"  [{icon}] {r['check']}: {r['pass_rate']:.1%} "
                f"({r['failed']} failed of {r['total']})"
            )
        overall = (report["status"] == "PASS").all()
        logger.info("=" * 60)
        logger.info(f"  OVERALL: {'ALL CHECKS PASSED ✓' if overall else 'SOME CHECKS FAILED ✗'}")
        logger.info("=" * 60)
        return report


def run_quality_checks(df: pd.DataFrame) -> pd.DataFrame:
    v = DataQualityValidator(df, threshold=CONFIG["quality_threshold"])
    v.check_not_null("email", "Every customer must have an email address")
    v.check_not_null("first_name", "Every customer must have a first name")
    v.check_not_null("region", "Every customer must be assigned to a region for campaign segmentation")
    v.check_unique("email", "Emails must be unique after deduplication")
    v.check_regex("email", CONFIG["email_regex"], "Emails must be in valid format")
    v.check_values_in_set("region", CONFIG["valid_regions"], "Region must be US, EU, or APAC")
    v.check_date_range(
        "registration_date", "2010-01-01", datetime.now().strftime("%Y-%m-%d"),
        "Registration dates must be between 2010 and today"
    )
    return v.generate_report()

# include AI-based inference to fill in missing regions using Claude LLM
import anthropic  # pip install anthropic

def infer_region_with_llm(df: pd.DataFrame) -> pd.DataFrame:
    """
    Use Claude to infer missing region values from available context.
    Only processes records with null region — never overwrites existing values.

    Args:
        df: DataFrame with 'region', 'email', 'first_name', 'last_name' columns.

    Returns:
        DataFrame with inferred regions filled in and a 'region_inferred' flag.
    """
    client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var
    null_region_mask = df["region"].isna()
    null_count = null_region_mask.sum()

    if null_count == 0:
        logger.info("No null regions to infer.")
        df["region_inferred"] = False
        return df

    logger.info(f"Inferring region for {null_count} records using LLM...")
    df = df.copy()
    df["region_inferred"] = False

    null_records = df[null_region_mask].copy()

    # Batch records to reduce API calls (10 records per call)
    batch_size = 10
    inferred_regions = {}

    for i in range(0, len(null_records), batch_size):
        batch = null_records.iloc[i:i + batch_size]
        records_text = "\n".join([
            f"  - Index {idx}: email={row.get('email', 'unknown')}, "
            f"name={row.get('first_name', '')} {row.get('last_name', '')}"
            for idx, row in batch.iterrows()
        ])

        prompt = f"""You are a data engineer. Based on the following customer records, 
infer the most likely geographic region for each. The only valid regions are:
- US (United States and Canada)
- EU (Europe, Middle East, Africa)  
- APAC (Asia Pacific, Australia, New Zealand)

Use email domains, name patterns, and any other available signals.
If you truly cannot infer, respond with UNKNOWN.

Records:
{records_text}

Respond ONLY in JSON format like:
{{"results": [{{"index": <index>, "region": "<US|EU|APAC|UNKNOWN>", "confidence": "<high|medium|low>", "reason": "<brief reason>"}}]}}"""

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            result = json.loads(response.content[0].text)
            for item in result["results"]:
                idx = item["index"]
                region = item["region"]
                if region in CONFIG["valid_regions"]:
                    inferred_regions[idx] = region
                    logger.info(
                        f"  Inferred region for index {idx}: {region} "
                        f"(confidence: {item['confidence']}, reason: {item['reason']})"
                    )
        except Exception as e:
            logger.warning(f"  LLM inference failed for batch {i}-{i+batch_size}: {e}")

    # Apply inferred regions
    for idx, region in inferred_regions.items():
        df.at[idx, "region"] = region
        df.at[idx, "region_inferred"] = True

    inferred_count = df["region_inferred"].sum()
    still_null = df["region"].isna().sum()
    logger.info(f"  Regions inferred by LLM: {inferred_count}")
    logger.info(f"  Regions still null (UNKNOWN or inference failed): {still_null}")
    return df


import matplotlib.pyplot as plt
import seaborn as sns

def generate_eda_report(df: pd.DataFrame, output_dir: Path):
    """Generate a professional 6-chart EDA and quality visualization."""
    logger.info("STEP 5: Generating EDA visualization...")

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle("ShopStream Customer Data Quality Report", fontsize=16, fontweight="bold")
    colors = ["#2196F3", "#4CAF50", "#FF9800", "#F44336", "#9C27B0", "#00BCD4"]

    # 1. Customer Count by Region
    region_counts = df["region"].value_counts()
    axes[0, 0].bar(region_counts.index, region_counts.values, color=colors[:len(region_counts)])
    axes[0, 0].set_title("Customers by Region")
    axes[0, 0].set_ylabel("Count")
    for i, (r, c) in enumerate(region_counts.items()):
        axes[0, 0].text(i, c + 50, f"{c:,}", ha="center", fontweight="bold", fontsize=9)

    # 2. Registration Trend
    monthly = df.dropna(subset=["registration_date"]).set_index("registration_date").resample("ME").size()
    axes[0, 1].plot(monthly.index, monthly.values, color=colors[0], linewidth=2)
    axes[0, 1].fill_between(monthly.index, monthly.values, alpha=0.2, color=colors[0])
    axes[0, 1].set_title("Monthly Registration Trend")
    axes[0, 1].set_ylabel("New Customers")
    axes[0, 1].tick_params(axis="x", rotation=45)

    # 3. Source Contribution
    if "sources" in df.columns:
        source_counts = df["sources"].str.split(",").explode().value_counts()
    else:
        source_counts = df["source"].value_counts()
    axes[0, 2].pie(source_counts.values, labels=source_counts.index,
                   autopct="%1.1f%%", colors=colors[:len(source_counts)], startangle=90)
    axes[0, 2].set_title("Records by Source System")

    # 4. Field Completeness
    fields = ["email", "first_name", "last_name", "phone", "region"]
    completeness = df[fields].notna().mean().sort_values()
    bar_colors = ["#F44336" if v < 0.9 else "#4CAF50" for v in completeness.values]
    axes[1, 0].barh(completeness.index, completeness.values, color=bar_colors)
    axes[1, 0].set_xlim(0, 1.1)
    axes[1, 0].axvline(x=CONFIG["quality_threshold"], color="red",
                       linestyle="--", label=f"{CONFIG['quality_threshold']:.0%} threshold")
    axes[1, 0].set_title("Field Completeness Rate")
    axes[1, 0].legend(fontsize=8)
    for i, v in enumerate(completeness.values):
        axes[1, 0].text(v + 0.01, i, f"{v:.1%}", va="center", fontsize=9)

    # 5. Email Validity Breakdown
    if "email_valid" in df.columns:
        valid_counts = df["email_valid"].value_counts()
        labels = ["Valid", "Invalid"]
        values = [valid_counts.get(True, 0), valid_counts.get(False, 0)]
        wedge_colors = [colors[1], colors[3]]
        axes[1, 1].pie(values, labels=labels, autopct="%1.1f%%",
                       colors=wedge_colors, startangle=90)
        axes[1, 1].set_title("Email Validity")

    # 6. Opt-Out Rate by Region
    if "opt_out" in df.columns:
        opt_out_rate = df.groupby("region")["opt_out"].mean().sort_values()
        axes[1, 2].bar(opt_out_rate.index, opt_out_rate.values,
                       color=[colors[3] if v > 0.2 else colors[1] for v in opt_out_rate.values])
        axes[1, 2].set_title("Opt-Out Rate by Region")
        axes[1, 2].set_ylabel("Opt-Out Rate")
        axes[1, 2].axhline(y=0.2, color="red", linestyle="--", label="20% threshold")
        for i, (region, rate) in enumerate(opt_out_rate.items()):
            axes[1, 2].text(i, rate + 0.005, f"{rate:.1%}", ha="center", fontsize=9)

    plt.tight_layout()
    output_path = output_dir / "customer_quality_report.png"
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"  EDA report saved: {output_path}")

# add pipeline execution function
def run_pipeline():
    """
    Main pipeline entry point.
    Orchestrates: Ingest -> Clean -> Deduplicate -> Validate -> Visualize -> Export
    """
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info("SHOPSTREAM CUSTOMER DATA QUALITY PIPELINE")
    logger.info(f"Run started: {start_time.isoformat()}")
    logger.info("=" * 60)

    # Step 1: Ingest
    combined = ingest_all_sources()
    input_count = len(combined)

    # Step 2: Clean
    cleaned = clean_dataframe(combined)

    # Step 3: Deduplicate
    deduped = deduplicate_customers(cleaned)

    # Step 4: AI Region Inference (optional — comment out if no API key)
    # deduped = infer_region_with_llm(deduped)

    # Step 5: Quality Validation
    logger.info("STEP 4: Quality Validation")
    quality_report = run_quality_checks(deduped)

    # Step 6: Visualize
    generate_eda_report(deduped, CONFIG["output_dir"])

    # Step 7: Export
    logger.info("STEP 6: Exporting Results")

    parquet_path = CONFIG["output_dir"] / "golden_customers.parquet"
    deduped.to_parquet(parquet_path, index=False, engine="pyarrow", compression="gzip")
    logger.info(f"  Parquet export: {parquet_path} ({parquet_path.stat().st_size / 1024:.1f} KB)")

    csv_path = CONFIG["output_dir"] / "golden_customers.csv"
    deduped.to_csv(csv_path, index=False, encoding="utf-8-sig")   # BOM for Excel compatibility
    logger.info(f"  CSV export: {csv_path}")

    report_path = CONFIG["output_dir"] / "quality_report.csv"
    quality_report.to_csv(report_path, index=False)
    logger.info(f"  Quality report: {report_path}")

    # Summary
    duration = (datetime.now() - start_time).total_seconds()
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"  Input records:          {input_count:,}")
    logger.info(f"  Output (golden) records:{len(deduped):,}")
    logger.info(f"  Duplicates removed:     {input_count - len(deduped):,}")
    logger.info(f"  Quality checks passed:  {(quality_report['status'] == 'PASS').sum()}/{len(quality_report)}")
    logger.info(f"  Duration:               {duration:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    run_pipeline()
    