
import csv
import json

from pathlib import Path
from datetime import datetime, timezone

from solution.ingestion.validators import normalize_phone
from solution.security.crypto import phone_fingerprint
from solution.database.db import get_connection

from datetime import timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

DISPOSITIONS_PATH = Path(
    "assignment-a-data/schemas/dispositions.csv"
)

def load_dispositions():
    """Load valid disposition codes for each workflow."""

    catalogue = {}

    with open(DISPOSITIONS_PATH, "r", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            workflow_id = row["workflow_id"]
            code = row["code"]

            catalogue.setdefault(workflow_id, {})[code] = {
                "is_terminal": row["is_terminal"].lower() == "true",
                "is_success": row["is_success"].lower() == "true"
            }

    return catalogue

def normalize_timestamp(value):
    """
    Convert timestamps into UTC ISO format.

    Naive timestamps are interpreted as IST.
    """

    if not value:
        raise ValueError("missing_occurred_at")

    timestamp = value.strip()

    if timestamp.endswith("Z"):
        timestamp = timestamp[:-1] + "+00:00"

    parsed = datetime.fromisoformat(timestamp)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)

    return parsed.astimezone(timezone.utc).isoformat()

def get_event_phone_hmac(event):
    """Generate a phone fingerprint for events containing a phone."""

    phone = event.get("phone")

    if not phone:
        return None

    canonical_phone = normalize_phone(phone)

    return phone_fingerprint(canonical_phone)

def is_disposition_event(event_type):
    return event_type in (
        "disposition.set",
        "disposition.override"
    )

def validate_disposition(event, catalogue):
    """Check whether a disposition exists for the event workflow."""

    if not is_disposition_event(event.get("event_type")):
        return True

    payload = event.get("payload") or {}
    code = payload.get("disposition_code")

    workflow_id = event.get("workflow_id")

    return code in catalogue.get(workflow_id, {})


def create_event_quality():
    return {
        "events_total": 0,
        "malformed_events": 0,
        "duplicate_events_dropped": 0,
        "orphan_events": 0,
        "unknown_disposition_events": 0
    }


def reconcile_event_links(conn):
    """
    Link stored events to leads using workflow_id and phone_hmac.
    Also link disposition.override events through their call_id.
    """

    # Link normal events using their phone fingerprint.
    conn.execute("""
        INSERT OR IGNORE INTO event_links (event_id, lead_id)
        SELECT e.event_id, l.lead_id
        FROM interaction_events e
        JOIN leads l
          ON e.workflow_id = l.workflow_id
         AND e.phone_hmac = l.phone_hmac
        WHERE e.phone_hmac IS NOT NULL
          AND e.event_type != 'disposition.override'
    """)

    # Link override events through another event belonging to the same call.
    conn.execute("""
        INSERT OR IGNORE INTO event_links (event_id, lead_id)
        SELECT override_event.event_id, linked_event.lead_id
        FROM interaction_events override_event
        JOIN interaction_events related_event
          ON override_event.workflow_id = related_event.workflow_id
         AND override_event.call_id = related_event.call_id
         AND override_event.event_id != related_event.event_id
        JOIN event_links linked_event
          ON related_event.event_id = linked_event.event_id
        WHERE override_event.event_type = 'disposition.override'
    """)


def process_event_file(file_path, conn, quality):
    """
    Read one JSONL file and store valid, unique events.
    """

    with open(file_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            # Ignore empty lines.
            if not line:
                continue

            quality["events_total"] += 1

            # Parse JSON.
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                quality["malformed_events"] += 1
                continue

            # event_id is mandatory.
            event_id = event.get("event_id")

            if not event_id:
                quality["malformed_events"] += 1
                continue

            # Check duplicate event IDs across all drops.
            existing = conn.execute(
                "SELECT event_id FROM interaction_events WHERE event_id = ?",
                (event_id,)
            ).fetchone()

            if existing:
                quality["duplicate_events_dropped"] += 1
                continue

            workflow_id = event.get("workflow_id")
            event_type = event.get("event_type")
            call_id = event.get("call_id")
            payload = event.get("payload") or {}

            # Validate disposition codes.
            if event_type in ("disposition.set", "disposition.override"):
                dispositions = load_dispositions()
                disposition_code = payload.get("disposition_code")

                workflow_dispositions = dispositions.get(workflow_id, {})

                if disposition_code not in workflow_dispositions:
                    quality["unknown_disposition_events"] += 1
                    continue

            # Normalize timestamp.
            try:
                occurred_at = normalize_timestamp(event.get("occurred_at"))
            except (ValueError, TypeError):
                quality["malformed_events"] += 1
                continue

            # Store only the HMAC fingerprint, never the raw phone.
            phone_hmac = None

            if event.get("phone"):
                try:
                    phone_hmac = get_event_phone_hmac(event)
                except ValueError:
                    phone_hmac = None

            # Store event in append-only ledger.
            conn.execute("""
                INSERT INTO interaction_events (
                    event_id,
                    workflow_id,
                    call_id,
                    event_type,
                    occurred_at,
                    phone_hmac,
                    payload_json,
                    ingested_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_id,
                workflow_id,
                call_id,
                event_type,
                occurred_at,
                phone_hmac,
                json.dumps(payload),
                datetime.now(timezone.utc).isoformat()
            ))

    # Link events that can now be associated with existing leads.
    reconcile_event_links(conn)
