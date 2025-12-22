#!/usr/bin/env python3
"""
GitHub Security Alert Assignment Script

This script reads secret scanning alerts from CSV and assigns them to the committer
who introduced the secret (based on Commit_Author column).

Features:
- Reads secret scanning data from CSV
- Filters alerts that have a valid Commit_Author
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
import requests
import time
from typing import List, Dict, Optional
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Get the scripts directory (parent of assign_alerts)
script_dir = os.path.dirname(os.path.abspath(__file__))
scripts_dir = os.path.dirname(script_dir)

# Ensure output directory exists at scripts/output/assign_alerts
output_dir = os.path.join(scripts_dir, "output", "assign_alerts")
os.makedirs(output_dir, exist_ok=True)


def get_github_token() -> str:
    """
    Get GitHub token from environment variables.
    Tries GH_PATS first (for consistency with other scripts), then GITHUB_TOKEN.
    
    Returns:
        GitHub Personal Access Token
        
    Raises:
        SystemExit: If no valid token is found
    """
    pats_str = os.getenv("GH_PATS")
    if pats_str:
        # Take the first PAT from the comma-separated list
        pats = [token.strip() for token in pats_str.split(",") if token.strip()]
        if pats:
            logging.info(f"Using first PAT from GH_PATS (found {len(pats)} total)")
            return pats[0]
    
    # Fallback to GITHUB_TOKEN
    token = os.getenv("GITHUB_TOKEN")
    if token:
        logging.info("Using GITHUB_TOKEN")
        return token
    
    logging.error("No GitHub token found. Set GH_PATS or GITHUB_TOKEN environment variable.")
    sys.exit(1)


def assign_alert_to_user(
    org: str,
    repo: str,
    alert_number: int,
    assignee: str,
    token: str,
    max_retries: int = 3
) -> bool:
    """
    Assign a secret scanning alert to a user via GitHub API.
    
    Args:
        org: Organization name
        repo: Repository name
        alert_number: Alert number
        assignee: GitHub username to assign the alert to
        token: GitHub Personal Access Token
        max_retries: Maximum number of retry attempts
        
    Returns:
        True if assignment succeeded, False otherwise
    """
    repo_full_name = f"{org}/{repo}"
    url = f"https://api.github.com/repos/{repo_full_name}/secret-scanning/alerts/{alert_number}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    # Use 'assignee' (singular) not 'assignees' (plural) for secret scanning alerts
    payload = {"assignee": assignee}
    
    for attempt in range(max_retries):
        try:
            response = requests.patch(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                logging.info(
                    f"Successfully assigned alert #{alert_number} in {repo_full_name} to @{assignee}"
                )
                return True
            elif response.status_code == 404:
                logging.error(
                    f"Alert #{alert_number} not found in {repo_full_name} (404)"
                )
                return False
            elif response.status_code == 422:
                # Unprocessable entity - might mean the assignee doesn't exist or other validation error
                error_msg = response.json().get("message", "Unknown error")
                logging.warning(
                    f"Cannot assign alert #{alert_number} in {repo_full_name} to @{assignee}: {error_msg}. "
                    f"The user may not exist or may not have access to the repository."
                )
                return False
            elif response.status_code == 403:
                logging.error(
                    f"Permission denied to assign alert #{alert_number} in {repo_full_name}. "
                    f"Check token permissions."
                )
                return False
            else:
                logging.warning(
                    f"Unexpected status {response.status_code} for alert #{alert_number} in {repo_full_name}: "
                    f"{response.text}"
                )
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue
                return False
                
        except requests.exceptions.RequestException as e:
            logging.error(
                f"Request failed for alert #{alert_number} in {repo_full_name}: {e}"
            )
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return False
    
    return False


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
    Filter alerts that have a valid Commit_Author.

    Args:
        df: DataFrame with secret scanning alerts

    Returns:
        DataFrame filtered to only include alerts with valid Commit_Author
    """
    # Check if Commit_Author column exists
    if "Commit_Author" not in df.columns:
        logging.warning("Commit_Author column not found in CSV. Available columns:")
        for col in df.columns:
            logging.warning(f"  - {col}")
        logging.warning(
            "To get committer information, enable commit enrichment and re-run the fetch script."
        )
        return pd.DataFrame()  # Return empty DataFrame

    # Filter out alerts without committer information
    filtered_df = df.dropna(subset=["Commit_Author"])
    filtered_df = filtered_df[filtered_df["Commit_Author"] != ""]

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
    committer_groups = df.groupby("Commit_Author")

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
                        "Assignee": committer,
                        "Alert_Number": alert["Alert_Number"],
                        "Repository_Name": alert["Repository_Name"],
                        "Secret_Type": alert["Secret_Type"],
                        "State": alert["State"],
                        "URL": alert["URL"],
                        "Total_Alerts_For_Assignee": data["total_alerts"],
                        "Open_Alerts_For_Assignee": data["open_alerts"],
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
    
    # If not dry-run, attempt to assign alerts via API
    if not args.dry_run:
        logging.info("Attempting to assign alerts via GitHub API...")
        token = get_github_token()
        
        assignment_results = []
        for _, row in filtered_df.iterrows():
            org = row["Organization_Name"]
            repo = row["Repository_Name"]
            alert_num = row["Alert_Number"]
            assignee = row["Commit_Author"]
            
            success = assign_alert_to_user(org, repo, alert_num, assignee, token)
            assignment_results.append({
                "org": org,
                "repo": repo,
                "alert": alert_num,
                "assignee": assignee,
                "success": success
            })
            
            # Rate limiting: be nice to the API
            time.sleep(0.1)
        
        # Log results
        successful = sum(1 for r in assignment_results if r["success"])
        failed = len(assignment_results) - successful
        logging.info(f"Assignment complete: {successful} succeeded, {failed} failed")

    # Print summary
    print_assignment_summary(summary)

    # Save report if output file specified
    if args.output:
        save_assignment_report(summary, args.output)
    else:
        # Generate default output filename in the output directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_output = os.path.join(output_dir, f"alert_assignments_{timestamp}.csv")
        save_assignment_report(summary, default_output)

    # Show next steps
    print("\n" + "=" * 80)
    print("NEXT STEPS:")
    print("=" * 80)
    if args.dry_run:
        print("1. Review the assignment summary above")
        print("2. Run without --dry-run to assign alerts via GitHub API")
        print("3. Or manually assign alerts using the committer GitHub handles from the CSV")
        print("\nNote: Currently in dry-run mode. No API calls were made.")
    else:
        successful = sum(1 for r in assignment_results if r["success"])
        failed = len(assignment_results) - successful
        
        if successful > 0:
            print(f"✓ Successfully assigned {successful} alert(s) via GitHub API")
        if failed > 0:
            print(f"✗ Failed to assign {failed} alert(s)")
            print("  Check the logs above for details on failed assignments")
        print("\nReview the generated CSV file for complete assignment details.")


if __name__ == "__main__":
    main()
