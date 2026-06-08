from pathlib import Path
import pandas as pd
import logging

# ── Configuration ──────────────────────────────────────────────────────────────
CONFIG = {
    "input_dir": Path("data/raw"),
    "output_dir": Path("data/processed"),
    # "crm_api_url": "https://api.shopstream.example.com/v2/customers",
    # "crm_api_key": "sk-xxxx",          # Use environment variable in production
    # "valid_regions": ["US", "EU", "APAC"],
    # "email_regex": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
    # "quality_threshold": 0.95,         # 95% of records must pass each check
    # "source_priority": {"crm": 1, "website": 2, "erp": 3, "marketing": 4},
}

for d in [CONFIG["input_dir"], CONFIG["output_dir"]]:
    d.mkdir(parents=True, exist_ok=True)

##injgesting csv data
def injest_globaltech_csv(filepath: Path) -> pd.DataFrame:
    df = pd.read_csv(
        filepath,
        encoding="iso-8859-1", 
        dtype={"Phone": str}, 
        parse_dates=["Registration Date"],
        na_values=["", "N/A", "null", "NULL", "none", "NaN"],
    )
    return df

