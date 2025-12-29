#!/usr/bin/env python3
"""
GitHub Security Alert Assignment Script (GitHub App Authentication)

This script reads secret scanning alerts from CSV and assigns them to the committer
who introduced the secret (based on Commit_Author column).

Features:
- Uses GitHub App authentication instead of PAT
- Reads secret scanning data from CSV
- Filters alerts that have a valid Commit_Author
- Can assign alerts via GitHub API or generate assignment lists
- Supports dry-run mode for testing

Usage:
    python assign_alerts_githubApp.py --csv-file ../output/secret_scanning_secret_scanning_report.csv --dry-run

Environment Variables:
    GH_APP_ID: GitHub App ID
    GH_PRIVATE_KEY: GitHub App private key content or path
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

# Add the parent directory to the path to import github_auth
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from github_auth.github_app_auth import GitHubAppAuth

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


def get_github_app_auth() -> GitHubAppAuth:
    """
    Initialize GitHub App authentication.
    
    Returns:
        GitHubAppAuth: Initialized GitHub App authentication handler
        
    Raises:
        SystemExit: If authentication setup fails
    """
    try:
        auth = GitHubAppAuth()
        logging.info("GitHub App authentication initialized successfully")
        return auth
    except Exception as e:
        logging.error(f"Failed to initialize GitHub App authentication: {e}")
        logging.error("Please ensure GH_APP_ID and GH_PRIVATE_KEY environment variables are set")
        sys.exit(1)


def get_alert_details(
    org: str,
    repo: str,
    alert_number: int,
    auth: GitHubAppAuth,
    max_retries: int = 3
) -> Optional[Dict]:
    """
    Fetch details of a secret scanning alert including current assignee.
    
    Args:
        org: Organization name
        repo: Repository name
        alert_number: Alert number
        auth: GitHub App authentication handler
        max_retries: Maximum number of retry attempts
        
    Returns:
        Dictionary with alert details or None if failed
    """
    repo_full_name = f"{org}/{repo}"
    
    # Authenticate for the organization if not already authenticated
    if not auth.access_token or auth.installation_id is None:
        if not auth.authenticate_for_organization(org):
            logging.error(f"Failed to authenticate for organization: {org}")
            return None
    
    # Get authenticated session
    session = auth.get_authenticated_session()
    
    url = f"https://api.github.com/repos/{repo_full_name}/secret-scanning/alerts/{alert_number}"
    
    for attempt in range(max_retries):
        try:
            response = session.get(url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                # Extract assignee if present
                assignee = data.get("assignee", {})
                current_assignee = assignee.get("login", "") if assignee else ""
                return {"current_assignee": current_assignee}
            elif response.status_code == 404:
                logging.warning(
                    f"Alert #{alert_number} not found in {repo_full_name} (404)"
                )
                return None
            elif response.status_code == 401:
                # Token expired, try to re-authenticate
                logging.warning(f"Authentication expired, re-authenticating for {org}")
                if auth.authenticate_for_organization(org):
                    session = auth.get_authenticated_session()
                    continue
                else:
                    logging.error(f"Re-authentication failed for {org}")
                    return None
            else:
                logging.warning(
                    f"Unexpected status {response.status_code} for alert #{alert_number} in {repo_full_name}"
                )
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
                
        except requests.exceptions.RequestException as e:
            logging.error(
                f"Request failed for alert #{alert_number} in {repo_full_name}: {e}"
            )
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return None
    
    return None


def assign_alert_to_user(
    org: str,
    repo: str,
    alert_number: int,
    assignee: str,
    auth: GitHubAppAuth,
    max_retries: int = 3
) -> bool:
    """
    Assign a secret scanning alert to a user via GitHub API.
    
    Args:
        org: Organization name
        repo: Repository name
        alert_number: Alert number
        assignee: GitHub username to assign the alert to
        auth: GitHub App authentication handler
        max_retries: Maximum number of retry attempts
        
    Returns:
        True if assignment succeeded, False otherwise
    """
    repo_full_name = f"{org}/{repo}"
    
    # Authenticate for the organization if not already authenticated
    if not auth.access_token or auth.installation_id is None:
        if not auth.authenticate_for_organization(org):
            logging.error(f"Failed to authenticate for organization: {org}")
            return False
    
    # Get authenticated session
    session = auth.get_authenticated_session()
    
    url = f"https://api.github.com/repos/{repo_full_name}/secret-scanning/alerts/{alert_number}"
    
    # Use 'assignee' (singular) not 'assignees' (plural) for secret scanning alerts
    payload = {"assignee": assignee}
    
    for attempt in range(max_retries):
        try:
            response = session.patch(url, json=payload, timeout=30)
            
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
                    f"Check GitHub App permissions."
                )
                return False
            elif response.status_code == 401:
                # Token expired, try to re-authenticate
                logging.warning(f"Authentication expired, re-authenticating for {org}")
                if auth.authenticate_for_organization(org):
                    session = auth.get_authenticated_session()
                    continue
                else:
                    logging.error(f"Re-authentication failed for {org}")
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
        
        # Include Organization_Name in the alerts data
        columns_to_include = ["Alert_Number", "Repository_Name", "Secret_Type", "State", "URL"]
        if "Organization_Name" in group.columns:
            columns_to_include.insert(0, "Organization_Name")

        summary[committer] = {
            "total_alerts": alert_count,
            "open_alerts": open_alerts,
            "resolved_alerts": alert_count - open_alerts,
            "repositories": repositories,
            "secret_types": secret_types,
            "alerts": group[columns_to_include].to_dict("records"),
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


def save_assignment_report(
    summary: Dict, 
    output_file: str, 
    dry_run: bool = True,
    assignment_results: Optional[List[Dict]] = None,
    current_assignees: Optional[Dict] = None
):
    """
    Save assignment summary to a CSV file.

    Args:
        summary: Assignment summary dictionary
        output_file: Path to output CSV file
        dry_run: True if this is a dry-run report, False for post-run report
        assignment_results: List of assignment results (for post-run)
        current_assignees: Dictionary mapping (org, repo, alert_num) to current assignee (for dry-run)
    """
    try:
        # Flatten the summary data for CSV export
        csv_data = []

        for committer, data in summary.items():
            for alert in data["alerts"]:
                row = {
                    "Assignee": committer,
                    "Alert_Number": alert["Alert_Number"],
                    "Repository_Name": alert["Repository_Name"],
                    "Secret_Type": alert["Secret_Type"],
                    "State": alert["State"],
                    "URL": alert["URL"],
                    "Total_Alerts_For_Assignee": data["total_alerts"],
                    "Open_Alerts_For_Assignee": data["open_alerts"],
                }
                
                # Add mode-specific columns
                if dry_run:
                    # For dry-run: add currently_assigned_to column
                    key = (alert.get("Organization_Name", ""), alert["Repository_Name"], alert["Alert_Number"])
                    current_assignee = ""
                    if current_assignees and key in current_assignees:
                        current_assignee = current_assignees[key]
                    row["Currently_Assigned_To"] = current_assignee
                else:
                    # For post-run: add successful_assignment column
                    successful = False
                    if assignment_results:
                        # Find the result for this alert
                        for result in assignment_results:
                            if (result["alert"] == alert["Alert_Number"] and 
                                result["repo"] == alert["Repository_Name"]):
                                successful = result["success"]
                                break
                    row["Successful_Assignment"] = successful
                
                csv_data.append(row)

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
        description="Assign secret scanning alerts to committers using GitHub App authentication"
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
    
    assignment_results = None
    current_assignees = None
    
    # If dry-run, fetch current assignees
    if args.dry_run:
        logging.info("Dry-run mode: Fetching current assignees...")
        auth = get_github_app_auth()
        current_assignees = {}
        current_org = None
        
        for _, row in filtered_df.iterrows():
            org = row["Organization_Name"]
            repo = row["Repository_Name"]
            alert_num = row["Alert_Number"]
            
            # Re-authenticate if we're processing a new organization
            if org != current_org:
                logging.info(f"Authenticating for organization: {org}")
                if not auth.authenticate_for_organization(org):
                    logging.error(f"Failed to authenticate for organization: {org}. Skipping alerts.")
                    current_assignees[(org, repo, alert_num)] = ""
                    continue
                current_org = org
            
            details = get_alert_details(org, repo, alert_num, auth)
            if details:
                current_assignees[(org, repo, alert_num)] = details.get("current_assignee", "")
            else:
                current_assignees[(org, repo, alert_num)] = ""
            
            # Rate limiting: be nice to the API
            time.sleep(0.1)
        
        logging.info(f"Fetched current assignees for {len(current_assignees)} alerts")
    else:
        # If not dry-run, attempt to assign alerts via API
        logging.info("Attempting to assign alerts via GitHub API (using GitHub App)...")
        auth = get_github_app_auth()
        
        assignment_results = []
        current_org = None
        
        for _, row in filtered_df.iterrows():
            org = row["Organization_Name"]
            repo = row["Repository_Name"]
            alert_num = row["Alert_Number"]
            assignee = row["Commit_Author"]
            
            # Re-authenticate if we're processing a new organization
            if org != current_org:
                logging.info(f"Authenticating for organization: {org}")
                if not auth.authenticate_for_organization(org):
                    logging.error(f"Failed to authenticate for organization: {org}. Skipping alerts.")
                    assignment_results.append({
                        "org": org,
                        "repo": repo,
                        "alert": alert_num,
                        "assignee": assignee,
                        "success": False
                    })
                    continue
                current_org = org
            
            success = assign_alert_to_user(org, repo, alert_num, assignee, auth)
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
        save_assignment_report(
            summary, 
            args.output, 
            dry_run=args.dry_run,
            assignment_results=assignment_results,
            current_assignees=current_assignees
        )
    else:
        # Generate default output filename in the output directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        mode_prefix = "dry_run" if args.dry_run else "post_run"
        default_output = os.path.join(output_dir, f"alert_assignments_{mode_prefix}_{timestamp}.csv")
        save_assignment_report(
            summary, 
            default_output,
            dry_run=args.dry_run,
            assignment_results=assignment_results,
            current_assignees=current_assignees
        )

    # Show next steps
    print("\n" + "=" * 80)
    print("NEXT STEPS:")
    print("=" * 80)
    if args.dry_run:
        print("1. Review the assignment summary above")
        print("2. Check the dry-run CSV report for current assignees")
        print("3. Run without --dry-run to assign alerts via GitHub API")
        print("4. Or manually assign alerts using the committer GitHub handles from the CSV")
        print("\nNote: Currently in dry-run mode. Assignments were not made.")
    else:
        successful = sum(1 for r in assignment_results if r["success"])
        failed = len(assignment_results) - successful
        
        if successful > 0:
            print(f"✓ Successfully assigned {successful} alert(s) via GitHub API")
        if failed > 0:
            print(f"✗ Failed to assign {failed} alert(s)")
            print("  Check the logs above for details on failed assignments")
        print("\nReview the post-run CSV file for assignment results (Successful_Assignment column).")


if __name__ == "__main__":
    main()
