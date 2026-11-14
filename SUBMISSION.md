# Submission

## Candidate
- **Name:** Deepak Kumar Khatoi
- **Assignment chosen:** A (Data)
- **Time spent (honest estimate):** 6.53 hr

## How to run

Run these commands from the repository root using Python 3.12.

```bash
# 1. Create and activate virtual environment
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Generate encryption and HMAC keys
python -m solution.security.generate_keys

# 4. Generate sample input data
python assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data

# 5. Initialize the database
python -m solution.database.db

# 6. Ingest both data drops
python -m solution.main ingest data/drop_1
python -m solution.main ingest data/drop_2

# 7. Generate reports
python -m solution.main report --out reports

# 8. Run tests
pytest -q
```

Generated data, database files, encryption keys, and reports are excluded from version control.

## Design

The solution uses Python and SQLite to implement an append-only interaction ledger and reporting pipeline.

**Architecture:**

1. **Lead ingestion:** Reads workflow-specific CSV files, normalizes headers, validates fields using the provided JSON schemas, and applies defaults. Invalid rows are recorded in a rejection table without storing PII in rejection records.
2. **PII protection:** Customer names and phone numbers are encrypted using AES-GCM. Phone numbers are normalized and fingerprinted using HMAC-SHA256 for identity matching without storing plaintext phone numbers.
3. **Event ingestion:** Reads JSONL event files, validates event IDs, ignores duplicate events, and stores accepted events in the interaction ledger. Event-to-lead relationships are maintained separately so previously orphaned events can be linked when their leads arrive.
4. **Reporting:** Processes linked events and generates the five required CSV/JSON reports.

**Database schema:**

| Table | Purpose |
|---|---|
| `leads` | Stores lead identity, encrypted PII, reference values, and non-PII attributes |
| `interaction_events` | Stores accepted interaction events |
| `event_links` | Links events to their corresponding leads |
| `rejections` | Stores rejected lead rows and rejection reasons |
| `ingestion_runs` | Tracks processed drops and ingestion quality metrics |

Unique constraints and indexes support deduplication, event lookup, and efficient reporting. Events are retained as ledger records rather than overwritten when dispositions change.

## Decisions & assumptions

| Decision | Why | Alternative considered |
|---|---|---|
| SQLite for persistence | Simple, reliable, and sufficient for the assignment | PostgreSQL |
| AES-GCM encryption for PII | Provides authenticated encryption at rest | Plaintext storage or basic encoding |
| HMAC-SHA256 for phone identity | Allows duplicate matching without decrypting phone numbers | Plaintext phone-number matching |
| First valid lead keeps its original batch ID | Preserves the original batch attribution | Moving a lead to the latest batch |
| Later non-null values update existing lead attributes | Preserves useful information while allowing incremental enrichment | Replacing all existing values |
| Naive timestamps are interpreted as IST | Follows the assignment's timestamp convention | Treating them as UTC |
| Latest override determines effective disposition | Preserves the disposition correction history | Updating the original disposition event |
| Repeated ingestion of the same drop is skipped | Prevents accidental reprocessing | Reprocessing every input file |

## Failure modes considered

**Handled:**
- Invalid CSV values and missing required fields are recorded as rejections.
- Optional invalid fields become null and generate field warnings.
- Duplicate leads are merged using workflow ID and HMAC phone fingerprint.
- Duplicate event IDs are ignored.
- Malformed JSONL records are counted and skipped.
- Unknown disposition codes are counted and ignored.
- Orphan events are retained and reconciled when matching leads become available.
- Re-running an already ingested drop is prevented.
- PII is encrypted before being stored in the database.

**Not fully handled:**
- Concurrent ingestion of the same drop by multiple processes.
- Recovery from a crash in the middle of a drop as a fully atomic operation.
- Key rotation and recovery if encryption keys are lost.
- Large-scale performance testing beyond the supplied sample data.
- Comprehensive validation of every possible malformed event payload.

## Testing

Tested:
- Database initialization and table creation.
- Encryption/decryption and HMAC phone fingerprinting.
- Phone, date, decimal, and enum normalization.
- Lead ingestion, validation, rejection, and duplicate merging.
- Event ingestion, malformed events, duplicate IDs, and orphan reconciliation.
- Repeated ingestion of the same drop.
- Report generation for the supplied datasets.

Automated test results: 

Not yet tested:
- Very large datasets and sustained concurrent ingestion.
- Simultaneous ingestion processes.
- Crash recovery and encryption-key rotation.

## Results

- Successfully processed the supplied `drop_1` and `drop_2` datasets.
- Re-ingesting `drop_1` correctly reported that the drop had already been ingested.
- Processing `drop_2` reduced the unresolved orphan-event count because additional leads became available.
- Generated the required reports:
  - `batch_summary.csv`
  - `daily_overview.csv`
  - `lead_report.csv`
  - `rejections.csv`
  - `data_quality.json`

**Performance:** 

**Data quality:** [Add the final values from `reports/data_quality.json`.]

## If I had another day

1. Add comprehensive automated tests using isolated temporary databases.
2. Improve crash recovery and transactional handling for complete ingestion drops.
3. Add structured logging and clearer error reporting.
4. Optimize database queries and reporting for larger datasets.
5. Add key rotation and stronger operational security practices.
6. Add performance benchmarks for ingestion and report generation.