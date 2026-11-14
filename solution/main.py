
import argparse

from solution.ingestion.lead_ingestion import ingest_drop
from solution.reporting.report_generator import generate_reports

def main():
    parser = argparse.ArgumentParser(
        description="Interaction Ledger and Reporting Pipeline"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True
    )

    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("drop_path")

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument(
        "--out",
        default="reports"
    )

    args = parser.parse_args()

    if args.command == "ingest":
        ingest_drop(args.drop_path)

    elif args.command == "report":
        generate_reports(output_path=args.out)

if __name__ == "__main__":
    main()