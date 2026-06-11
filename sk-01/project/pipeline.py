import logging
from pathlib import Path

from ingest import (
    ingest_payroll_excel, 
    ingest_acquiredco_json, 
    ingest_globaltech_csv,
    ingest_benefits_xml
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    logging.info("Starting HRIS data ingestion pipeline...")

    # Ingest GlobalTech CSV data
    globaltech_df = ingest_globaltech_csv(Path("data/raw/globaltech_hris.csv"))
    
    # Ingest AcquiredCo JSON data
    acquiredco_df = ingest_acquiredco_json(Path("data/raw/acquiredco_hris.json"))
    
    # Ingest Payroll Excel data
    payroll_df = ingest_payroll_excel(Path("data/raw/payroll_data.xlsx"))
    
    # Ingest Benefits XML data
    benefits_df = ingest_benefits_xml(Path("data/raw/benefits_data.xml"))

    logging.info("Data ingestion pipeline complete.")

if __name__ == "__main__":
    main()  
