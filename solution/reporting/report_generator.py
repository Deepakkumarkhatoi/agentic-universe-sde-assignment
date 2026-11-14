
import csv
import json

from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from solution.database.db import get_connection
from solution.ingestion.event_ingestion import load_dispositions

IST = timezone(timedelta(hours=5, minutes=30))

# ==================================================
# 1. DATE CONVERSION
# ==================================================

def to_ist(value):
    """Convert a stored UTC timestamp into IST."""

    if not value:
        return None

    parsed = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(IST)

# ==================================================
# 2. LOAD DATABASE DATA
# ==================================================

def load_leads(conn):
    rows = conn.execute("""
        SELECT *
        FROM leads
        ORDER BY workflow_id, reference_value
    """).fetchall()

    return [dict(row) for row in rows]

def load_linked_events(conn):
    rows = conn.execute("""
        SELECT
            e.event_id,
            e.workflow_id,
            e.call_id,
            e.event_type,
            e.occurred_at,
            e.payload_json,
            el.lead_id
        FROM interaction_events e
        JOIN event_links el
            ON e.event_id = el.event_id
        ORDER BY e.occurred_at, e.event_id
    """).fetchall()

    events = []

    for row in rows:
        event = dict(row)
        event["payload"] = json.loads(
            event.pop("payload_json") or "{}"
        )
        events.append(event)

    return events

# ==================================================
# 3. BUILD CALLS FOR EACH LEAD
# ==================================================

def build_lead_calls(leads, events, dispositions):
    """
    Build calls using linked events.

    A call is counted only when call.initiated exists.
    """

    events_by_lead = defaultdict(list)

    for event in events:
        events_by_lead[event["lead_id"]].append(event)

    lead_calls = {}

    for lead in leads:

        lead_id = lead["lead_id"]

        calls_by_id = defaultdict(list)

        for event in events_by_lead[lead_id]:

            call_id = event["call_id"]

            if call_id is not None:
                calls_by_id[call_id].append(event)

        calls = []

        for call_id, call_events in calls_by_id.items():

            initiated_events = [
                e for e in call_events
                if e["event_type"] == "call.initiated"
            ]

            if not initiated_events:
                continue

            initiated = max(
                initiated_events,
                key=lambda e: (e["occurred_at"], e["event_id"])
            )

            connected = any(
                e["event_type"] == "call.connected"
                for e in call_events
            )

            telephony_failed = any(
                e["event_type"] == "call.telephony_failed"
                for e in call_events
            )

            set_events = [
                e for e in call_events
                if e["event_type"] == "disposition.set"
            ]

            override_events = [
                e for e in call_events
                if e["event_type"] == "disposition.override"
            ]

            # An override takes precedence over a normal disposition.
            if override_events:
                effective_event = max(
                    override_events,
                    key=lambda e: (e["occurred_at"], e["event_id"])
                )

            elif set_events:
                effective_event = max(
                    set_events,
                    key=lambda e: (e["occurred_at"], e["event_id"])
                )

            else:
                effective_event = None

            disposition_code = None
            is_terminal = False
            is_success = False

            if effective_event:

                disposition_code = (
                    effective_event["payload"].get("disposition_code")
                )

                disposition_info = dispositions.get(
                    lead["workflow_id"], {}
                ).get(disposition_code, {})

                is_terminal = disposition_info.get(
                    "is_terminal", False
                )

                is_success = disposition_info.get(
                    "is_success", False
                )

            calls.append({
                "call_id": call_id,
                "initiated_at": initiated["occurred_at"],
                "initiated_ist": to_ist(initiated["occurred_at"]),
                "connected": connected,
                "telephony_failed": telephony_failed,
                "disposition": disposition_code,
                "is_terminal": is_terminal,
                "is_success": is_success
            })

        calls.sort(
            key=lambda call: call["initiated_at"]
        )

        lead_calls[lead_id] = calls

    return lead_calls

# ==================================================
# 4. DETERMINE LEAD BUCKET
# ==================================================

def determine_bucket(calls):

    if not calls:
        return "yet_to_reach_out"

    if any(call["is_terminal"] for call in calls):
        return "completed"

    if all(call["telephony_failed"] for call in calls):
        return "in_progress_telephony_failed"

    return "in_progress_dialed"

# ==================================================
# 5. WRITE CSV FILE
# ==================================================

def write_csv(file_path, headers, rows):

    file_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        file_path,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=headers
        )

        writer.writeheader()
        writer.writerows(rows)

# ==================================================
# 6. BATCH SUMMARY
# ==================================================

def generate_batch_summary(leads, lead_calls, output_dir):

    grouped = defaultdict(list)

    for lead in leads:
        grouped[
            (lead["workflow_id"], lead["batch_id"])
        ].append(lead)

    rows = []

    buckets = [
        "yet_to_reach_out",
        "in_progress_telephony_failed",
        "in_progress_dialed",
        "completed"
    ]

    for (workflow_id, batch_id), batch_leads in sorted(
        grouped.items()
    ):

        counts = {
            bucket: 0
            for bucket in buckets
        }

        for lead in batch_leads:

            bucket = determine_bucket(
                lead_calls[lead["lead_id"]]
            )

            counts[bucket] += 1

        rows.append({
            "workflow_id": workflow_id,
            "batch_id": batch_id,
            "total_leads": len(batch_leads),
            **counts
        })

    headers = [
        "workflow_id",
        "batch_id",
        "total_leads",
        *buckets
    ]

    write_csv(
        output_dir / "batch_summary.csv",
        headers,
        rows
    )

# ==================================================
# 7. DAILY OVERVIEW
# ==================================================

def generate_daily_overview(
    leads,
    lead_calls,
    output_dir
):

    daily_calls = defaultdict(dict)
    daily_success_leads = defaultdict(set)

    for lead in leads:

        workflow_id = lead["workflow_id"]
        lead_id = lead["lead_id"]

        for call in lead_calls[lead_id]:

            date = call["initiated_ist"].date().isoformat()

            key = (workflow_id, date)

            daily_calls[key][call["call_id"]] = call

            if call["is_success"]:
                daily_success_leads[key].add(lead_id)

    rows = []

    for key in sorted(daily_calls):

        workflow_id, date = key

        calls = list(daily_calls[key].values())

        total_calls = len(calls)

        connected_calls = sum(
            1 for call in calls if call["connected"]
        )

        connectivity_rate = (
            connected_calls / total_calls
            if total_calls else 0
        )

        rows.append({
            "workflow_id": workflow_id,
            "date": date,
            "total_calls": total_calls,
            "connected_calls": connected_calls,
            "connectivity_rate": f"{connectivity_rate:.4f}",
            "success_leads": len(
                daily_success_leads[key]
            )
        })

    headers = [
        "workflow_id",
        "date",
        "total_calls",
        "connected_calls",
        "connectivity_rate",
        "success_leads"
    ]

    write_csv(
        output_dir / "daily_overview.csv",
        headers,
        rows
    )

# ==================================================
# 8. LEAD REPORT
# ==================================================

def generate_lead_report(
    leads,
    lead_calls,
    output_dir
):

    rows = []

    for lead in leads:

        calls = lead_calls[lead["lead_id"]]

        connected_calls = sum(
            1 for call in calls if call["connected"]
        )

        # Latest initiated call.
        last_call_at = ""

        if calls:

            latest_call = max(
                calls,
                key=lambda call: call["initiated_at"]
            )

            last_call_at = (
                latest_call["initiated_ist"].isoformat()
            )

        # Latest call by initiated time that has a disposition.
        calls_with_disposition = [
            call for call in calls
            if call["disposition"] is not None
        ]

        current_disposition = ""

        if calls_with_disposition:

            latest_disposition_call = max(
                calls_with_disposition,
                key=lambda call: call["initiated_at"]
            )

            current_disposition = (
                latest_disposition_call["disposition"]
            )

        # Ever successful.
        ever_success = any(
            call["is_success"] for call in calls
        )

        # Phone masking: +91****** followed by last four digits.
        phone_masked = ""

        if lead["phone_encrypted"]:

            from solution.security.crypto import decrypt_text

            phone = decrypt_text(
                lead["phone_encrypted"]
            )

            phone_masked = "+91******" + phone[-4:]

        rows.append({
            "workflow_id": lead["workflow_id"],
            "external_ref": lead["reference_value"] or "",
            "batch_id": lead["batch_id"],
            "phone_masked": phone_masked,
            "bucket": determine_bucket(calls),
            "total_calls": len(calls),
            "connected_calls": connected_calls,
            "last_call_at": last_call_at,
            "current_disposition": current_disposition,
            "ever_success": str(ever_success).lower()
        })

    rows.sort(
        key=lambda row: (
            row["workflow_id"],
            row["external_ref"]
        )
    )

    headers = [
        "workflow_id",
        "external_ref",
        "batch_id",
        "phone_masked",
        "bucket",
        "total_calls",
        "connected_calls",
        "last_call_at",
        "current_disposition",
        "ever_success"
    ]

    write_csv(
        output_dir / "lead_report.csv",
        headers,
        rows
    )

# ==================================================
# 9. REJECTIONS REPORT
# ==================================================

def generate_rejections(conn, output_dir):

    records = conn.execute("""
        SELECT
            workflow_id,
            batch_id,
            row_number,
            reason
        FROM rejections
        ORDER BY workflow_id, batch_id, row_number
    """).fetchall()

    rows = [
        dict(record)
        for record in records
    ]

    headers = [
        "workflow_id",
        "batch_id",
        "row_number",
        "reason"
    ]

    write_csv(
        output_dir / "rejections.csv",
        headers,
        rows
    )

# ==================================================
# 10. DATA QUALITY REPORT
# ==================================================

def generate_data_quality(conn, output_dir):

    quality = {
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

    runs = conn.execute("""
        SELECT quality_json
        FROM ingestion_runs
    """).fetchall()

    additive_fields = [
        "lead_rows_total",
        "lead_rows_rejected",
        "duplicate_lead_rows_merged",
        "field_warnings",
        "events_total",
        "malformed_events",
        "duplicate_events_dropped",
        "unknown_disposition_events"
    ]

    for run in runs:

        run_quality = json.loads(
            run["quality_json"]
        )

        for field in additive_fields:
            quality[field] += run_quality.get(field, 0)

        for reason, count in run_quality.get(
            "rejections_by_reason", {}
        ).items():

            quality["rejections_by_reason"][reason] = (
                quality["rejections_by_reason"].get(reason, 0)
                + count
            )

    # Final-state orphan count, not the sum of old snapshots.
    quality["orphan_events"] = conn.execute("""
        SELECT COUNT(*)
        FROM interaction_events e
        LEFT JOIN event_links el
            ON e.event_id = el.event_id
        WHERE el.event_id IS NULL
    """).fetchone()[0]

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        output_dir / "data_quality.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            quality,
            file,
            indent=4
        )

# ==================================================
# 11. MAIN REPORT GENERATOR
# ==================================================

def generate_reports(
    output_path="reports",
    db_path="data/interaction_ledger.db"
):
    """Generate all five assignment reports."""

    output_dir = Path(output_path)

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    conn = get_connection(db_path)

    try:

        print("Loading leads...")

        leads = load_leads(conn)

        print("Loading linked events...")

        events = load_linked_events(conn)

        print("Loading dispositions...")

        dispositions = load_dispositions()

        print("Building calls...")

        lead_calls = build_lead_calls(
            leads,
            events,
            dispositions
        )

        print("Generating batch summary...")

        generate_batch_summary(
            leads,
            lead_calls,
            output_dir
        )

        print("Generating daily overview...")

        generate_daily_overview(
            leads,
            lead_calls,
            output_dir
        )

        print("Generating lead report...")

        generate_lead_report(
            leads,
            lead_calls,
            output_dir
        )

        print("Generating rejections...")

        generate_rejections(
            conn,
            output_dir
        )

        print("Generating data quality report...")

        generate_data_quality(
            conn,
            output_dir
        )

        print("\nAll five reports generated successfully!")

        print(f"Output directory: {output_dir.resolve()}")

    finally:
        conn.close()

if __name__ == "__main__":
    generate_reports()