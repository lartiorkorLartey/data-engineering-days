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
        employees = raw_data["employees"]
        extracted_employees = []
        page = 1
        start_idx = 0
        page_size = 1000
        total_records = len(employees)

        while start_idx < total_records:
            end_idx = start_idx + page_size
            page_data = employees[start_idx:end_idx]

            if not page_data:
                break

            extracted_employees.extend(page_data)

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

##### ingesting xml data #####
def ingest_benefits_xml(filepath: Path) -> pd.DataFrame:
    """
    Ingests benefits enrollment data from an XML file.

    Args:
    filepath: Path to the XML file.

    Returns:
    DataFrame containing the ingested data, or an empty DataFrame on error.
    """
    try:
        logging.info(f"Ingesting Benefits XML: {filepath}")  
        
        tree = ET.parse(filepath)
        root = tree.getroot()
        records = []

        for employee in root.findall("enrollment"):
            record = {
                "employee_id": employee.findtext("employee_id"),
                "plan_type": employee.findtext("plan_type"),
                "coverage_level": employee.findtext("coverage_level"),
                "enrollment_date": employee.findtext("enrollment_date"),
                "premium_employee": employee.findtext("premium_employee"),
                "premium_employer": employee.findtext("premium_employer"),
                "source": "Benefits XML"  # Add source for traceability
            }
            records.append(record)

        df = pd.DataFrame(records)
        df["enrollment_date"] = pd.to_datetime(df["enrollment_date"], errors="coerce")
        df["employee_id"] = df["employee_id"].astype(str)
        df["plan_type"] = df["plan_type"].astype(str)
        df["premium_employee"] = pd.to_numeric(df["premium_employee"], errors="coerce")
        df["premium_employer"] = pd.to_numeric(df["premium_employer"], errors="coerce")

        logging.info(f"Successfully ingested Benefits XML: {filepath} with {len(df)} records")
        return df

    except FileNotFoundError:
        logging.error(f"File not found: {filepath}")
        return pd.DataFrame()  # Return empty DataFrame on error        
    except Exception as e:
        logging.error(f"Error ingesting XML data: {e}")
        return pd.DataFrame()  # Return empty DataFrame on error
    