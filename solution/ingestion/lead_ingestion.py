import csv
import json

from pathlib import Path
from datetime import datetime, timezone

from solution.database.db import get_connection
from solution.security.crypto import encrypt_text, phone_fingerprint

from solution.ingestion.validators import (
    normalize_header,
    normalize_phone,
    parse_date,
    parse_decimal,
    parse_enum,
    validate_string
)

from solution.ingestion.event_ingestion import (
    process_event_file,
    reconcile_event_links
)

SCHEMA_DIR = Path("assignment-a-data/schemas")

# ==================================================
# 1. LOAD WORKFLOW SCHEMA
# ==================================================

def load_schema(workflow_id):
    """Load the JSON schema for a workflow."""

    schema_path = SCHEMA_DIR / f"{workflow_id}.json"

    if not schema_path.exists():
        raise FileNotFoundError(
            f"Schema not found: {schema_path}"
        )

    with open(schema_path, "r", encoding="utf-8") as file:
        return json.load(file)

def get_schema_fields(schema):
    """Support both list and dictionary schema formats."""

    fields = schema["fields"]

    if isinstance(fields, dict):
        return [
            {"name": name, **config}
            for name, config in fields.items()
        ]

    return fields

# ==================================================
# 2. CSV HEADER MAPPING
# ==================================================

def map_csv_headers(csv_headers, schema):
    """Map CSV headers to canonical schema field names."""

    mapping = {}

    for field_config in get_schema_fields(schema):

        field_name = field_config["name"]

        accepted_names = (
            [field_name] + field_config.get("aliases", [])
        )

        normalized_names = {
            normalize_header(name)
            for name in accepted_names
        }

        for index, header in enumerate(csv_headers):

            if normalize_header(header) in normalized_names:
                mapping[field_name] = index
                break

    return mapping

def is_blank_row(row):
    """Check whether every cell in a row is empty."""

    return all(
        not str(value or "").strip()
        for value in row
    )

def get_field_value(row, mapping, field_name):
    """Extract a field value using its mapped CSV index."""

    index = mapping.get(field_name)

    if index is None or index >= len(row):
        return None

    value = str(row[index]).strip()

    return value if value else None

# ==================================================
# 3. FIELD VALIDATION
# ==================================================

def validate_field(value, field_config):
    """Validate a field according to its schema type."""

    if value is None:
        return None

    field_type = field_config["type"]

    if field_type == "string":
        return validate_string(value)

    elif field_type == "phone":
        return normalize_phone(value)

    elif field_type == "date":
        return parse_date(value)

    elif field_type == "decimal":
        return parse_decimal(value)

    elif field_type == "enum":
        return parse_enum(
            value,
            field_config["values"]
        )

    raise ValueError(
        f"unsupported_field_type:{field_type}"
    )

def prepare_lead_row(row, mapping, schema):
    """
    Validate one CSV row.

    Returns:
        validated_data, rejection_reason, warning_count
    """

    validated_data = {}
    warning_count = 0

    # Process fields in schema order.
    for field_config in get_schema_fields(schema):

        field_name = field_config["name"]

        value = get_field_value(
            row,
            mapping,
            field_name
        )

        # Required field validation.
        if value is None:

            if field_config.get("required", False):
                return (
                    None,
                    f"missing_required:{field_name}",
                    0
                )

            validated_data[field_name] = None
            continue

        try:

            validated_data[field_name] = validate_field(
                value,
                field_config
            )

        except ValueError as error:

            # Reject invalid required fields.
            if field_config.get("required", False):
                return None, str(error), 0

            # Optional invalid fields become NULL.
            validated_data[field_name] = None
            warning_count += 1

    return validated_data, None, warning_count

# ==================================================
# 4. IDENTIFY PII AND REFERENCE FIELDS
# ==================================================

def is_pii_field(field_config):
    """Identify personally identifiable information."""

    return (
        field_config.get("pii", False)
        or field_config.get("classification") == "pii"
        or field_config.get("sensitivity") == "pii"
        or field_config["name"] in ("customer_name", "phone")
    )

def get_reference_field(schema):
    """Find the non-PII reference field."""

    fields = get_schema_fields(schema)

    for field_config in fields:

        if (
            field_config.get("reference", False)
            or field_config.get("classification") == "reference"
            or field_config.get("sensitivity") == "reference"
        ):
            return field_config["name"]

    # Fallback for assignment workflows.
    for field_name in ("policy_number", "order_id"):

        if any(
            field["name"] == field_name
            for field in fields
        ):
            return field_name

    raise ValueError("No reference field found in schema")

def separate_lead_data(validated_data, schema):
    """Separate PII, reference data, and normal attributes."""

    pii_data = {}
    attributes = {}

    reference_field = get_reference_field(schema)

    reference_value = validated_data.get(reference_field)

    for field_config in get_schema_fields(schema):

        field_name = field_config["name"]
        value = validated_data.get(field_name)

        if field_name == reference_field:
            continue

        if is_pii_field(field_config):
            pii_data[field_name] = value
        else:
            attributes[field_name] = value

    return pii_data, reference_value, attributes

# ==================================================
# 5. APPLY DEFAULT VALUES
# ==================================================

def apply_defaults(attributes, schema):
    """Apply schema defaults to fields that are still NULL."""

    for field_config in get_schema_fields(schema):

        field_name = field_config["name"]

        if is_pii_field(field_config):
            continue

        if (
            field_name not in attributes
            or attributes[field_name] is None
        ):
            if "default" in field_config:
                attributes[field_name] = field_config["default"]

    return attributes

# ==================================================
# 6. INSERT OR MERGE LEAD
# ==================================================

def insert_or_merge_lead(
    conn,
    workflow_id,
    batch_id,
    validated_data,
    schema
):
    """
    Insert a new lead or merge an existing lead.

    Identity:
        workflow_id + phone_hmac

    Merge:
        Last non-null value wins.
        Original batch_id remains unchanged.
    """

    pii_data, reference_value, attributes = separate_lead_data(
        validated_data,
        schema
    )

    canonical_phone = pii_data.get("phone")
    customer_name = pii_data.get("customer_name")

    if not canonical_phone or not customer_name:
        raise ValueError("Required PII fields are missing")

    phone_hmac = phone_fingerprint(canonical_phone)

    existing = conn.execute(
        """
        SELECT *
        FROM leads
        WHERE workflow_id = ? AND phone_hmac = ?
        """,
        (workflow_id, phone_hmac)
    ).fetchone()

    now = datetime.now(timezone.utc).isoformat()

    # Existing lead: merge values.
    if existing:

        old_attributes = json.loads(
            existing["attributes_json"] or "{}"
        )

        for field_name, value in attributes.items():

            if value is not None:
                old_attributes[field_name] = value

        old_attributes = apply_defaults(
            old_attributes,
            schema
        )

        encrypted_name = existing["customer_name_encrypted"]

        if customer_name is not None:
            encrypted_name = encrypt_text(customer_name)

        if reference_value is None:
            reference_value = existing["reference_value"]

        conn.execute(
            """
            UPDATE leads
            SET customer_name_encrypted = ?,
                reference_value = ?,
                attributes_json = ?,
                updated_at = ?
            WHERE lead_id = ?
            """,
            (
                encrypted_name,
                reference_value,
                json.dumps(old_attributes, ensure_ascii=False),
                now,
                existing["lead_id"]
            )
        )

        return "merged"

    # New lead.
    attributes = apply_defaults(attributes, schema)

    encrypted_phone = encrypt_text(canonical_phone)
    encrypted_name = encrypt_text(customer_name)

    conn.execute(
        """
        INSERT INTO leads (
            workflow_id,
            batch_id,
            phone_hmac,
            phone_encrypted,
            customer_name_encrypted,
            reference_value,
            attributes_json,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            workflow_id,
            batch_id,
            phone_hmac,
            encrypted_phone,
            encrypted_name,
            reference_value,
            json.dumps(attributes, ensure_ascii=False),
            now,
            now
        )
    )

    return "inserted"

# ==================================================
# 7. PROCESS ONE CSV FILE
# ==================================================

def process_csv_file(conn, csv_path, workflow_id, quality):
    """Read, validate, and store leads from one CSV file."""

    schema = load_schema(workflow_id)
    batch_id = csv_path.stem

    with open(
        csv_path,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.reader(file)
        headers = next(reader, None)

        if headers is None:
            return

        mapping = map_csv_headers(headers, schema)

        row_number = 0

        for row in reader:

            if is_blank_row(row):
                continue

            row_number += 1
            quality["lead_rows_total"] += 1

            validated_data, rejection_reason, warnings = (
                prepare_lead_row(row, mapping, schema)
            )

            # Rejected row.
            if rejection_reason:

                quality["lead_rows_rejected"] += 1

                reasons = quality["rejections_by_reason"]

                reasons[rejection_reason] = (
                    reasons.get(rejection_reason, 0) + 1
                )

                conn.execute(
                    """
                    INSERT OR REPLACE INTO rejections (
                        workflow_id,
                        batch_id,
                        row_number,
                        reason
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        workflow_id,
                        batch_id,
                        row_number,
                        rejection_reason
                    )
                )

                continue

            quality["field_warnings"] += warnings

            result = insert_or_merge_lead(
                conn,
                workflow_id,
                batch_id,
                validated_data,
                schema
            )

            if result == "merged":
                quality["duplicate_lead_rows_merged"] += 1

# ==================================================
# 8. DATA QUALITY COUNTERS
# ==================================================

def create_empty_quality():

    return {
        "lead_rows_total": 0,
        "lead_rows_rejected": 0,
        "rejections_by_reason": {},
        "duplicate_lead_rows_merged": 0,
        "field_warnings": 0,
        "events_total": 0,
        "malformed_events": 0,
        "duplicate_events_dropped": 0,
        "orphan_events": 0,
        "unknown_disposition_events": 0
    }

# ==================================================
# 9. INGEST COMPLETE DROP
# ==================================================

def ingest_drop(
    drop_path,
    db_path="data/interaction_ledger.db"
):
    """
    Ingest all leads and events from one drop.

    Repeated ingestion of the same drop is skipped.
    """

    drop_path = Path(drop_path)

    if not drop_path.exists():
        raise FileNotFoundError(
            f"Drop directory not found: {drop_path}"
        )

    leads_dir = drop_path / "leads"
    events_dir = drop_path / "events"

    if not leads_dir.exists():
        raise FileNotFoundError(
            f"Leads directory not found: {leads_dir}"
        )

    quality = create_empty_quality()

    conn = get_connection(db_path)

    normalized_path = str(drop_path.resolve())

    try:

        # Check if this drop was already ingested.
        previous_run = conn.execute(
            """
            SELECT quality_json
            FROM ingestion_runs
            WHERE drop_path = ?
            """,
            (normalized_path,)
        ).fetchone()

        if previous_run:

            print(f"Drop already ingested: {drop_path}")

            return json.loads(previous_run["quality_json"])

        started_at = datetime.now(timezone.utc).isoformat()

        # ------------------------------------------
        # Process lead CSV files.
        # ------------------------------------------

        workflow_dirs = sorted(
            path
            for path in leads_dir.iterdir()
            if path.is_dir()
        )

        for workflow_dir in workflow_dirs:

            workflow_id = workflow_dir.name

            csv_files = sorted(
                workflow_dir.glob("*.csv")
            )

            for csv_path in csv_files:

                print(
                    f"Processing lead: "
                    f"{workflow_id}/{csv_path.name}"
                )

                process_csv_file(
                    conn,
                    csv_path,
                    workflow_id,
                    quality
                )

        # ------------------------------------------
        # Process event JSONL files.
        # ------------------------------------------

        if events_dir.exists():

            event_files = sorted(
                events_dir.glob("*.jsonl")
            )

            for event_file in event_files:

                print(
                    f"Processing events: {event_file.name}"
                )

                process_event_file(
                    event_file,
                    conn,
                    quality
                )

        # ------------------------------------------
        # Reconcile event-to-lead links.
        # ------------------------------------------

        reconcile_event_links(conn)

        # ------------------------------------------
        # Calculate currently unresolved events.
        # ------------------------------------------

        quality["orphan_events"] = conn.execute(
            """
            SELECT COUNT(*)
            FROM interaction_events e
            LEFT JOIN event_links el
                ON e.event_id = el.event_id
            WHERE el.event_id IS NULL
            """
        ).fetchone()[0]

        # ------------------------------------------
        # Save ingestion run.
        # ------------------------------------------

        completed_at = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            INSERT INTO ingestion_runs (
                drop_path,
                started_at,
                completed_at,
                quality_json
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                normalized_path,
                started_at,
                completed_at,
                json.dumps(quality)
            )
        )

        conn.commit()

        print("\nIngestion completed successfully!")

        print(
            json.dumps(
                quality,
                indent=4
            )
        )

        return quality

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()