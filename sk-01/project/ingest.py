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


##### schema mapping #####
SCHEMA_LOOKUP = {
    "employee_id": "employee_id",
    "employee_identifier": "employee_id",
    "first_name": "first_name",
    "name_first": "first_name",
    "last_name": "last_name",
    "name_last": "last_name",
    "name_full": "full_name",
    "email": "email",
    "contact_email": "email",
    "department": "department",
    "assignment_department": "department",
    "job_title": "job_title",
    "assignment_role": "job_title",
    "hire_date": "hire_date",
    "assignment_hire_timestamp": "hire_date",
    "effective_date": "salary_effective_date",
    "country": "country",
    "assignment_location": "country",
    "employment_type": "employment_type",
    "manager_id": "manager_id",
    "manager_employee_id": "manager_id",
    "source": "source",
    "base_salary": "salary",
    "currency": "currency",
    "pay_frequency": "pay_frequency",
    "plan_type": "plan_type",
    "coverage_level": "coverage_level",
    "enrollment_date": "enrollment_date",
    "premium_employee": "premium_employee",
    "premium_employer": "premium_employer",
    "employment_status": "employment_status",
    "bonus_target_pct": "bonus_target_pct"
}


##### shared schema alignment function #####
def align_schema(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """
    Renames a DataFrame's columns to the standard schema using SCHEMA_LOOKUP,
    and logs a warning for any columns that don't map to a standard name.

    Args:
        df: DataFrame with raw, source-specific column names.
        source_name: Identifier for the source (used in the log message).

    Returns:
        DataFrame with columns renamed to standard names where a mapping exists.
    """ 
    df = df.rename(columns=SCHEMA_LOOKUP)  # Standardize column names
    
    unmapped_columns = [col for col in df.columns if col not in SCHEMA_LOOKUP.values()]
    if unmapped_columns:
        logging.warning(
            f"Unmapped columns detected in {source_name}: {unmapped_columns}. "
            f"Update SCHEMA_LOOKUP to include these."
        )
    return df


##### shared dead-letter writer #####
def write_dead_letter_records(records: list, source_name: str) -> None:
    """
    Writes a list of malformed/rejected records to a dead-letter file
    for manual review, and logs a summary warning.

    Args:
        records: List of dicts, each representing one bad record.
                 Each dict should include enough context to explain
                 why it was rejected (e.g. "reason", "page"/"row").
        source_name: Identifier for the source file (used in the
                     output filename and log message), e.g. "acquiredco_json".

    Returns:
        None. Writes a JSON file to CONFIG["output_dir"] if records is non-empty.
    """
    if not records:
        return

    dead_letter_path = CONFIG["output_dir"] / f"{source_name}_dead_letter.json"
    dead_letter_path.write_text(json.dumps(records, indent=2, default=str))

    logging.warning(
        f"{len(records)} malformed records from {source_name} written to "
        f"{dead_letter_path} for manual review."
    )


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

        df = align_schema(df, "GlobalTech CSV")

        # Identify and quarantine malformed records (missing employee_id)
        bad_mask = df["employee_id"].isna() | (df["employee_id"].astype(str).str.strip() == "")
        if bad_mask.any():
            bad_records = df[bad_mask].to_dict(orient="records")
            write_dead_letter_records(bad_records, "globaltech_csv")
            df = df[~bad_mask].copy()

        df["data_source"] = "GlobalTech CSV"  # Add source column for traceability

        logging.info(f"Successfully ingested GlobalTech CSV: {filepath} with {len(df)} records")
        return df

    except FileNotFoundError:
        logging.error(f"File not found: {filepath}")
        return pd.DataFrame()  # Return empty DataFrame on error
    
    except Exception as e:
        logging.error(f"Error ingesting GlobalTech CSV: {e}")
        return pd.DataFrame()  # Return empty DataFrame on error


##### ingesting excel data #####
def ingest_payroll_excel(filepath: Path) -> pd.DataFrame:
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

        df = align_schema(df, "Payroll Excel")

        # Identify and quarantine malformed records (missing employee_id)
        bad_mask = df["employee_id"].isna() | (df["employee_id"].astype(str).str.strip() == "")
        if bad_mask.any():
            bad_records = df[bad_mask].to_dict(orient="records")
            write_dead_letter_records(bad_records, "payroll_excel")
            df = df[~bad_mask].copy()

        df["data_source"] = "Payroll Excel"  # Add source column for traceability

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
    Validates each record per page; malformed records are sent to the
    shared dead-letter writer for manual review.

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
        dead_letter_records = []
        page = 1
        start_idx = 0
        page_size = 1000
        total_records = len(employees)

        while start_idx < total_records:
            end_idx = start_idx + page_size
            page_data = employees[start_idx:end_idx]

            if not page_data:
                break

            # Validate each record in this page individually
            for record in page_data:
                if not isinstance(record, dict):
                    dead_letter_records.append({
                        "reason": "Record is not a valid object",
                        "raw_record": record,
                        "page": page,
                    })
                    continue

                if not record.get("employee_identifier"):
                    dead_letter_records.append({
                        "reason": "Missing employee_identifier",
                        "raw_record": record,
                        "page": page,
                    })
                    continue

                extracted_employees.append(record)

            logging.info(f"Validated page {page}: rows up to index {end_idx}")
            start_idx += page_size
            page += 1

        write_dead_letter_records(dead_letter_records, "acquiredco_json")

        df = pd.json_normalize(extracted_employees, sep="_")

        df = align_schema(df, "AcquiredCo JSON")

        df["data_source"] = "AcquiredCo JSON"  # Add source column for traceability

        logging.info(f"Successfully ingested AcquiredCo JSON: {filepath} with {len(df)} records")
        return df

    except FileNotFoundError:
        logging.error(f"File not found: {filepath}")
        return pd.DataFrame()  # Return empty DataFrame on error
    except Exception as e:
        logging.error(f"Error ingesting AcquiredCo JSON: {e}")
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
        dead_letter_records = []

        for employee in root.findall("enrollment"):
            employee_id = employee.findtext("employee_id")

            # Validate while employee_id is still real None/empty, before str conversion
            if employee_id is None or employee_id.strip() == "":
                dead_letter_records.append({
                    "reason": "Missing employee_id",
                    "raw_record": {
                        "employee_id": employee_id,
                        "plan_type": employee.findtext("plan_type"),
                        "coverage_level": employee.findtext("coverage_level"),
                        "enrollment_date": employee.findtext("enrollment_date"),
                        "premium_employee": employee.findtext("premium_employee"),
                        "premium_employer": employee.findtext("premium_employer"),
                    },
                })
                continue

            record = {
                "employee_id": employee_id,
                "plan_type": employee.findtext("plan_type"),
                "coverage_level": employee.findtext("coverage_level"),
                "enrollment_date": employee.findtext("enrollment_date"),
                "premium_employee": employee.findtext("premium_employee"),
                "premium_employer": employee.findtext("premium_employer"),
                "data_source": "Benefits XML"  # Add source for traceability
            }
            records.append(record)

        write_dead_letter_records(dead_letter_records, "benefits_xml")

        df = pd.DataFrame(records)
        df["enrollment_date"] = pd.to_datetime(df["enrollment_date"], errors="coerce")
        df["employee_id"] = df["employee_id"].astype(str)
        df["plan_type"] = df["plan_type"].astype(str)
        df["premium_employee"] = pd.to_numeric(df["premium_employee"], errors="coerce")
        df["premium_employer"] = pd.to_numeric(df["premium_employer"], errors="coerce")

        df = align_schema(df, "Benefits XML")

        logging.info(f"Successfully ingested Benefits XML: {filepath} with {len(df)} records")
        return df

    except FileNotFoundError:
        logging.error(f"File not found: {filepath}")
        return pd.DataFrame()  # Return empty DataFrame on error        
    except Exception as e:
        logging.error(f"Error ingesting Benefits XML: {e}")
        return pd.DataFrame()  # Return empty DataFrame on error
    