
from solution.database.db import initialize_database
from solution.ingestion.lead_ingestion import ingest_drop

initialize_database()

print("\n========== DROP 1 ==========")
ingest_drop("data/drop_1")

print("\n========== DROP 1 AGAIN ==========")
ingest_drop("data/drop_1")

print("\n========== DROP 2 ==========")
ingest_drop("data/drop_2")
