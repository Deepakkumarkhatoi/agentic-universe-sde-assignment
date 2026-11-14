def test_solution_imports():
    from solution.database.db import initialize_database
    from solution.ingestion.lead_ingestion import ingest_drop
    from solution.ingestion.event_ingestion import process_event_file
    from solution.reporting.report_generator import generate_reports

    assert callable(initialize_database)
    assert callable(ingest_drop)
    assert callable(process_event_file)
    assert callable(generate_reports)