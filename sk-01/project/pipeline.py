from pathlib import Path
import pandas as pd
import logging
import xml.etree.ElementTree as ET
import json

##### setup logging #####
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

##### ingesting json data #####
def ingest_acquiredco_json(filepath: Path) -> pd.DataFrame:
    """
    Ingests AcquiredCo data from a JSON file.

    Args:
    filepath: Path to the JSON file.

    Returns:
    DataFrame containing the ingested data, or an empty DataFrame on error.
    """
    try:
        logging.info(f"Ingesting AcquiredCo JSON: {filepath}")  
         
        raw_data = json.loads(filepath.read_text())
        extracted_employees = []
        page = 1
        start_idx = 0
        page_size = 1000
        total_records = len(raw_data)

        while start_idx < total_records:
            end_idx = start_idx + page_size
            page_data = raw_data[start_idx:end_idx]

            if not page_data:
                break   

            for record in page_data:
                if "employees" in record:
                    extracted_employees.append(record["employees"])
               
            logging.info(f"Unpacked data up to row index {end_idx}")
            start_idx += page_size
            page += 1

        df = pd.json_normalize(extracted_employees, sep="_")
        df["source"] = "AcquiredCo JSON"  # Add source column for traceability

        logging.info(f"Successfully ingested AcquiredCo JSON: {filepath} with {len(df)} records")
        return df

    except FileNotFoundError:
        logging.error(f"File not found: {filepath}")
        return pd.DataFrame()  # Return empty DataFrame on error        
    except Exception as e:
        logging.error(f"Error ingesting JSON data: {e}")
        return pd.DataFrame()  # Return empty DataFrame on error
    
