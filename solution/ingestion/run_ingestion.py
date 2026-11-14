
from solution.database.db import initialize_database
from solution.ingestion.lead_ingestion import ingest_drop


if __name__ == "__main__":

    initialize_database()

    result = ingest_drop("data/drop_1")

    print("\nTotal rows:", result["lead_rows_total"])
    print("Rejected rows:", result["lead_rows_rejected"])
    print("Merged duplicates:", result["duplicate_lead_rows_merged"])
    print("Field warnings:", result["field_warnings"])
