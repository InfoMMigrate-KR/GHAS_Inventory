#!/usr/bin/env python3
"""
GitHub Security Alert Assignment Script

This script reads secret scanning alerts from CSV and assigns them to the committer
who introduced the secret (based on Committer_Id column).

Features:
- Reads secret scanning data from CSV
- Filters alerts that have a valid Committer_Id
- Can assign alerts via GitHub API or generate assignment lists
- Supports dry-run mode for testing

Usage:
    python assign_alerts.py --csv-file ../output/secret_scanning_secret_scanning_report.csv --dry-run

Environment Variables:
    GH_PAT: GitHub Personal Access Token for API calls
    DRY_RUN: Set to 'true' to only show what would be assigned without making actual API calls
"""

import os
import sys
import pandas as pd
import argparse
import logging
from typing import List, Dict, Optional
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def load_secret_scanning_data(csv_file: str) -> pd.DataFrame:
    """
    Load secret scanning data from CSV file.

    Args:
        csv_file: Path to the CSV file containing secret scanning alerts

    Returns:
        DataFrame with secret scanning data
    """
    try:
        df = pd.read_csv(csv_file)
        logging.info(f"Loaded {len(df)} alerts from {csv_file}")
        return df
    except Exception as e:
        logging.error(f"Failed to load CSV file {csv_file}: {e}")
        sys.exit(1)


def filter_alerts_with_committer(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter alerts that have a valid Committer_Id.

    Args:
        df: DataFrame with secret scanning alerts

    Returns:
        DataFrame filtered to only include alerts with valid Committer_Id
    """
    # Check if Committer_Id column exists
    if "Committer_Id" not in df.columns:
        logging.warning("Committer_Id column not found in CSV. Available columns:")
        for col in df.columns:
            logging.warning(f"  - {col}")
        logging.warning(
            "To get committer information, enable commit enrichment and re-run the fetch script."
        )
        return pd.DataFrame()  # Return empty DataFrame

    # Filter out alerts without committer information
    filtered_df = df.dropna(subset=["Committer_Id"])
    filtered_df = filtered_df[filtered_df["Committer_Id"] != ""]

    logging.info(
        f"Found {len(filtered_df)} alerts with committer information out of {len(df)} total alerts"
    )

    return filtered_df


def generate_assignment_summary(df: pd.DataFrame) -> Dict:
    """
    Generate a summary of alert assignments by committer.

    Args:
        df: DataFrame with filtered secret scanning alerts

    Returns:
        Dictionary with assignment summary
    """
    summary = {}

    # Group by committer
    committer_groups = df.groupby("Committer_Id")

    for committer, group in committer_groups:
        alert_count = len(group)
        repositories = group["Repository_Name"].unique().tolist()
        secret_types = group["Secret_Type"].unique().tolist()
        open_alerts = len(group[group["State"] == "open"])

        summary[committer] = {
            "total_alerts": alert_count,
            "open_alerts": open_alerts,
            "resolved_alerts": alert_count - open_alerts,
            "repositories": repositories,
            "secret_types": secret_types,
            "alerts": group[
                ["Alert_Number", "Repository_Name", "Secret_Type", "State", "URL"]
            ].to_dict("records"),
        }

    return summary


def print_assignment_summary(summary: Dict):
    """
    Print a formatted summary of alert assignments.

    Args:
        summary: Assignment summary dictionary
    """
    print("\n" + "=" * 80)
    print("SECRET SCANNING ALERT ASSIGNMENT SUMMARY")
    print("=" * 80)

    total_committers = len(summary)
    total_alerts = sum(data["total_alerts"] for data in summary.values())
    total_open = sum(data["open_alerts"] for data in summary.values())

    print(f"Total committers with alerts: {total_committers}")
    print(f"Total alerts to assign: {total_alerts}")
    print(f"Open alerts: {total_open}")
    print(f"Resolved alerts: {total_alerts - total_open}")
    print("\n" + "-" * 80)
    print("ASSIGNMENTS BY COMMITTER:")
    print("-" * 80)

    for committer, data in summary.items():
        print(f"\nCommitter: {committer}")
        print(f"  Total alerts: {data['total_alerts']}")
        print(f"  Open alerts: {data['open_alerts']}")
        print(f"  Repositories: {', '.join(data['repositories'][:5])}")
        if len(data["repositories"]) > 5:
            print(f"    ... and {len(data['repositories']) - 5} more")
        print(f"  Secret types: {', '.join(data['secret_types'][:3])}")
        if len(data["secret_types"]) > 3:
            print(f"    ... and {len(data['secret_types']) - 3} more")

        # Show first few open alerts
        open_alerts = [alert for alert in data["alerts"] if alert["State"] == "open"]
        if open_alerts:
            print(f"  Sample open alerts:")
            for alert in open_alerts[:3]:
                print(
                    f"    - #{alert['Alert_Number']} in {alert['Repository_Name']} ({alert['Secret_Type']})"
                )


def save_assignment_report(summary: Dict, output_file: str):
    """
    Save assignment summary to a CSV file.

    Args:
        summary: Assignment summary dictionary
        output_file: Path to output CSV file
    """
    try:
        # Flatten the summary data for CSV export
        csv_data = []

        for committer, data in summary.items():
            for alert in data["alerts"]:
                csv_data.append(
                    {
                        "Committer_Id": committer,
                        "Alert_Number": alert["Alert_Number"],
                        "Repository_Name": alert["Repository_Name"],
                        "Secret_Type": alert["Secret_Type"],
                        "State": alert["State"],
                        "URL": alert["URL"],
                        "Total_Alerts_For_Committer": data["total_alerts"],
                        "Open_Alerts_For_Committer": data["open_alerts"],
                    }
                )

        df = pd.DataFrame(csv_data)
        df.to_csv(output_file, index=False)
        logging.info(f"Saved assignment report to {output_file}")

    except Exception as e:
        logging.error(f"Failed to save assignment report: {e}")


def main():
    """
    Main function to process secret scanning alerts and generate assignment information.
    """
    parser = argparse.ArgumentParser(
        description="Assign secret scanning alerts to committers"
    )
    parser.add_argument(
        "--csv-file", required=True, help="Path to secret scanning CSV file"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show assignments without making API calls",
    )
    parser.add_argument(
        "--output", help="Output file for assignment report (CSV format)"
    )

    args = parser.parse_args()

    # Load the CSV data
    df = load_secret_scanning_data(args.csv_file)

    # Filter to alerts with committer information
    filtered_df = filter_alerts_with_committer(df)

    if filtered_df.empty:
        logging.warning(
            "No alerts found with committer information. Ensure commit enrichment is enabled."
        )
        print(
            "\nTo enable committer information collection, set the environment variable:"
        )
        print("ENABLE_COMMIT_ENRICHMENT=true")
        print("\nThen re-run the fetch_secret_scanning_alerts.py script.")
        return

    # Generate assignment summary
    summary = generate_assignment_summary(filtered_df)

    # Print summary
    print_assignment_summary(summary)

    # Save report if output file specified
    if args.output:
        save_assignment_report(summary, args.output)
    else:
        # Generate default output filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_output = f"alert_assignments_{timestamp}.csv"
        save_assignment_report(summary, default_output)

    # Show next steps
    print("\n" + "=" * 80)
    print("NEXT STEPS:")
    print("=" * 80)
    print("1. Review the assignment summary above")
    print("2. Use the generated CSV file to bulk assign alerts via GitHub API")
    print("3. Or manually assign alerts using the committer GitHub handles")
    print("\nNote: This is a dry-run. To implement actual GitHub API assignment,")
    print(
        "you would need to extend this script with GitHub API calls to assign alerts."
    )


if __name__ == "__main__":
    main()
