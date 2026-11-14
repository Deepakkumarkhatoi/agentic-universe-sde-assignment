
import sqlite3
from pathlib import Path

def get_connection(db_path="data/interaction_ledger.db"):
    """Create a database connection and enable foreign-key checks."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection

def initialize_database(db_path="data/interaction_ledger.db"):
    """Create all tables required by Assignment A."""

    connection = get_connection(db_path)

    connection.executescript("""
        CREATE TABLE IF NOT EXISTS leads (
            lead_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            phone_hmac TEXT NOT NULL,
            phone_encrypted BLOB NOT NULL,
            customer_name_encrypted BLOB NOT NULL,
            reference_value TEXT NOT NULL,
            attributes_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,

            UNIQUE(workflow_id, phone_hmac)
        );

        CREATE TABLE IF NOT EXISTS interaction_events (
            event_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            call_id TEXT,
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            phone_hmac TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            ingested_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS event_links (
            event_id TEXT PRIMARY KEY,
            lead_id INTEGER NOT NULL,
            FOREIGN KEY(event_id)
                REFERENCES interaction_events(event_id),
            FOREIGN KEY(lead_id)
                REFERENCES leads(lead_id)
        );

        CREATE TABLE IF NOT EXISTS rejections (
            rejection_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            row_number INTEGER NOT NULL,
            reason TEXT NOT NULL,
            UNIQUE(workflow_id, batch_id, row_number)
        );

        CREATE TABLE IF NOT EXISTS ingestion_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            drop_path TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            quality_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(drop_path)
        );

        CREATE INDEX IF NOT EXISTS idx_leads_workflow
            ON leads(workflow_id);

        CREATE INDEX IF NOT EXISTS idx_events_call
            ON interaction_events(workflow_id, call_id);

        CREATE INDEX IF NOT EXISTS idx_events_phone
            ON interaction_events(workflow_id, phone_hmac);

        CREATE INDEX IF NOT EXISTS idx_events_type
            ON interaction_events(event_type);

        CREATE INDEX IF NOT EXISTS idx_event_links_lead
            ON event_links(lead_id);
    """)

    connection.commit()
    connection.close()

if __name__ == "__main__":
    initialize_database()
    print("Database initialized successfully!")