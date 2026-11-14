# AI Usage Disclosure

## Tools used
- ChatGPT

## What I used them for
- Understanding the assignment requirements and breaking the work into smaller tasks.
- Getting guidance on the project structure and SQLite database design.
- Understanding and implementing CSV lead ingestion, JSONL event ingestion, data validation, phone number normalization, and duplicate handling.
- Getting help with AES encryption and HMAC hashing for protecting PII.
- Understanding event linking, call processing, disposition handling, and report generation.
- Debugging errors and improving the implementation.

## What I wrote or decided myself
- I reviewed the assignment requirements and followed the implementation step by step.
- I made decisions about the project structure, database organization, and how the ingestion flow should work.
- I worked through the edge cases, including duplicate leads, invalid phone numbers, missing required fields, duplicate events, and orphan events.
- I reviewed the generated code, made changes, and ran the commands to execute the pipeline.

## Where the AI was wrong or unhelpful
- One issue occurred when inserting an ingestion run into SQLite. The initial implementation tried to insert a UUID string into an integer primary-key column. I identified the database error and corrected the insert to let SQLite generate the ID automatically.
- Another issue occurred with timezone handling on Windows because the `Asia/Kolkata` timezone database was unavailable. I changed the implementation to use an explicit UTC+05:30 offset.

## How I verified AI-generated code
- Ran the database initialization and checked that the database was created successfully.
- Manually tested phone normalization, date parsing, decimal parsing, and enum validation.
- Tested encryption and decryption to confirm that sensitive values could be securely stored and recovered.
- Ran ingestion for both `drop_1` and `drop_2` and checked the quality metrics.
- Ran the same drop again to verify that duplicate ingestion was skipped.
- Generated the required reports and reviewed the output files.
- Reviewed the implementation and used test execution to identify and fix errors.