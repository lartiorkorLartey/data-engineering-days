from pathlib import Path
import pandas as pd
import logging
import xml.etree.ElementTree as ET

# setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)   

##### configuration #####
CONFIG = {
    "input_dir": Path("data/raw"),
    "output_dir": Path("data/processed")
}

for d in [CONFIG["input_dir"], CONFIG["output_dir"]]:
    d.mkdir(parents=True, exist_ok=True)

##### ingesting csv data #####
def ingest_globaltech_csv(filepath: Path) -> pd.DataFrame:
    """
    Ingests GlobalTech HRIS data from a CSV file.
    Includes source tagging and graceful error handling.

    Args:
    filepath: Path to the CSV file.

    Returns: 
    DataFrame containing the ingested HRIS data, or an empty DataFrame on error.
    """
    try:
        logging.info(f"Ingesting GlobalTech CSV data: {filepath}")    
    
        df  = pd.read_csv(
            filepath,
            dtype={"employee_id": str, "manager_id": str}, 
            parse_dates=["hire_date"],
            na_values=["", "N/A", "null", "NULL", "none", "NaN"],
        )

        df["source"] = "GlobalTech CSV"  # Add source column for traceability
        logging.info(f"Successfully ingested GlobalTech CSV: {filepath} with {len(df)} records")
        return df

    except FileNotFoundError:
        logging.error(f"File not found: {filepath}")
        return pd.DataFrame()  # Return empty DataFrame on error
    
    except Exception as e:
        logging.error(f"Error ingesting GlobalTech CSV: {e}")
        return pd.DataFrame()  # Return empty DataFrame on error

##### ingesting excel data #####
def ingest_payroll_data_excel(filepath: Path) -> pd.DataFrame:
    """
    Ingests payroll data from an Excel file.
    Includes source tagging and graceful error handling.

    Args:
    filepath: Path to the Excel file.

    Returns:
    DataFrame containing the ingested payroll data, or an empty DataFrame on error.
    """
    try:
        logging.info(f"Ingesting Payroll Excel: {filepath}")    
    
        df = pd.read_excel(
            filepath,
            dtype={"employee_id": str},
            parse_dates=["effective_date"],
            na_values=["", "N/A", "null", "NULL", "none", "NaN"],
        )

        df["source"] = "Payroll Excel"  # Add source column for traceability
        logging.info(f"Successfully ingested Payroll Excel: {filepath} with {len(df)} records")
        return df

    except FileNotFoundError:
        logging.error(f"File not found: {filepath}")
        return pd.DataFrame()  # Return empty DataFrame on error
    
    except Exception as e:
        logging.error(f"Error ingesting Payroll Excel: {e}")
        return pd.DataFrame()  # Return empty DataFrame on error

