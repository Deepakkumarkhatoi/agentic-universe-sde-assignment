
from pathlib import Path

from solution.database.db import initialize_database, get_connection
from solution.ingestion.event_ingestion import (
    process_event_file,
    create_event_quality
)

initialize_database()

conn = get_connection()
quality = create_event_quality()

event_files = sorted(Path("data/drop_1/events").glob("*.jsonl"))

for event_file in event_files:
    process_event_file(event_file, conn, quality)

conn.commit()

# Count events that currently have no linked lead.
orphan_count = conn.execute("""
    SELECT COUNT(*)
    FROM interaction_events e
    LEFT JOIN event_links el ON e.event_id = el.event_id
    WHERE el.event_id IS NULL
""").fetchone()[0]

quality["orphan_events"] = orphan_count

print("Event ingestion completed!")
print(quality)

conn.close()
