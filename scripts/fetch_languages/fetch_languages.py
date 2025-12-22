import os
import time
import logging
import requests
import pandas as pd
import csv
from datetime import datetime
from dotenv import load_dotenv

# --- Configuration ---
load_dotenv()

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

# Constants
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
ENTERPRISE_SLUG = os.getenv("GH_ENTERPRISE_SLUG")
GITHUB_TOKEN = os.getenv("GH_PATS").split(",")[0]

if not GITHUB_TOKEN or not ENTERPRISE_SLUG:
    raise ValueError("Please set GH_PATS and GH_ENTERPRISE_SLUG in .env file.")

# --- GraphQL Query ---
QUERY_ORG_REPOS = """
query($org: String!, $cursor: String) {
  organization(login: $org) {
    repositories(first: 50, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage, endCursor }
      nodes {
        name
        nameWithOwner
        isPrivate
        isArchived
        primaryLanguage { name }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          totalSize
          edges {
            size
            node { name }
          }
        }
      }
    }
  }
}
"""


class GitHubScanner:
    def __init__(self, token, enterprise_slug):
        self.enterprise_slug = enterprise_slug
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
            }
        )

    def get_organizations_from_csv(
        self, csv_file_path="scripts/output/organizations.csv"
    ):
        """
        Reads organization list from CSV file.
        Returns list of organization login names.
        """

        # Check if the CSV file exists, if not try to generate it
        if not os.path.exists(csv_file_path):
            logging.warning(f"Organizations CSV file not found at: {csv_file_path}")

            # Try alternative locations
            script_dir = os.path.dirname(os.path.abspath(__file__))
            root_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))
            possible_paths = [
                os.path.join(root_dir, "organizations.csv"),
                os.path.join(script_dir, "organizations.csv"),
                os.path.join(root_dir, "output", "organizations.csv"),
                os.path.join(script_dir, "output", "organizations.csv"),
                os.path.join(root_dir, "scripts", "output", "organizations.csv"),
            ]

            csv_file = None
            for path in possible_paths:
                if os.path.exists(path):
                    csv_file = path
                    csv_file_path = path
                    break

            if not csv_file:
                logging.warning(
                    f"Organizations CSV file not found. Tried locations:\n"
                    + "\n".join(f"  - {p}" for p in possible_paths)
                )
                logging.info(
                    "Attempting to generate organizations.csv using fetch_orgs.py..."
                )

                # Try to run fetch_orgs.py to generate the organizations.csv file
                fetch_orgs_path = os.path.join(
                    root_dir, "scripts", "fetch_Orgs", "fetch_orgs.py"
                )
                if os.path.exists(fetch_orgs_path):
                    try:
                        import subprocess
                        import sys

                        logging.info(f"Running fetch_orgs.py from: {fetch_orgs_path}")
                        result = subprocess.run(
                            [sys.executable, fetch_orgs_path],
                            capture_output=True,
                            text=True,
                            cwd=root_dir,
                        )

                        if result.returncode == 0:
                            logging.info("Successfully executed fetch_orgs.py")
                            # Check again for the CSV file in the expected location
                            output_csv = os.path.join(
                                root_dir, "scripts", "output", "organizations.csv"
                            )
                            if os.path.exists(output_csv):
                                csv_file_path = output_csv
                                logging.info(
                                    f"Organizations CSV file created at: {csv_file_path}"
                                )
                            else:
                                logging.error(
                                    "fetch_orgs.py completed but organizations.csv not found at expected location"
                                )
                        else:
                            logging.error(
                                f"fetch_orgs.py failed with error: {result.stderr}"
                            )
                    except Exception as e:
                        logging.error(f"Failed to execute fetch_orgs.py: {e}")
                else:
                    logging.error(f"fetch_orgs.py not found at: {fetch_orgs_path}")

                if not os.path.exists(csv_file_path):
                    logging.error(
                        "Please create an organizations.csv file with a 'login' column containing org names, "
                        "or ensure fetch_orgs.py is available and working properly."
                    )
                    return []

        try:
            logging.info(f"Reading organizations from: {csv_file_path}")
            df = pd.read_csv(csv_file_path)

            # Extract login column
            if "login" in df.columns:
                orgs = df["login"].dropna().tolist()
                logging.info(f"Loaded {len(orgs)} organizations from CSV")
                return orgs
            else:
                logging.error("CSV file must have a 'login' column")
                return []

        except Exception as e:
            logging.error(f"Error reading CSV file: {e}")
            return []

    def fetch_repo_languages(self, org_login):
        """
        Fetches repository language data for a specific organization using GraphQL.
        Returns:
           - (List[Dict]): Data if successful
           - (str): Error message if skipped/failed
        """
        logging.info(f"Scanning Organization: {org_login}")
        repo_data = []
        cursor = None
        has_next = True

        while has_next:
            variables = {"org": org_login, "cursor": cursor}

            try:
                response = self.session.post(
                    GITHUB_GRAPHQL_URL,
                    json={"query": QUERY_ORG_REPOS, "variables": variables},
                    timeout=30,
                )

                # Check HTTP status codes first
                if response.status_code == 401:
                    return None, "ERROR: Unauthorized - Invalid or expired token"
                elif response.status_code == 403:
                    return None, "ERROR: Forbidden - Token lacks necessary permissions"
                elif response.status_code == 404:
                    return (
                        None,
                        "ERROR: Not Found - Organization may not exist or no access",
                    )
                elif response.status_code != 200:
                    return (
                        None,
                        f"ERROR: HTTP {response.status_code} - {response.text[:100]}",
                    )

                # Rate Limit Handling
                remaining = int(response.headers.get("X-RateLimit-Remaining", 1))
                if remaining < 10:
                    time.sleep(5)

                try:
                    json_resp = response.json()
                except ValueError as e:
                    return None, f"ERROR: Invalid JSON response - {str(e)}"

                # --- ERROR HANDLING & SKIPPING LOGIC ---
                if "errors" in json_resp:
                    error_msg = json_resp["errors"][0].get("message", "Unknown Error")
                    error_type = json_resp["errors"][0].get("type", "UNKNOWN")

                    # Detect Token Policy Error
                    if "forbids access via a personal access tokens" in error_msg:
                        logging.warning(
                            f"  [SKIP] {org_login}: Token Policy Restriction (SSO/Expiry)"
                        )
                        return (
                            None,
                            f"ERROR: Token Policy Restriction - {error_msg}",
                        )

                    # Detect SAML Enforcement Error
                    if "SAML" in error_msg or error_type == "FORBIDDEN":
                        logging.warning(
                            f"  [SKIP] {org_login}: SAML/Access Restriction"
                        )
                        return None, f"ERROR: SAML/Access Restriction - {error_msg}"

                    # Detect Resource Not Found
                    if error_type == "NOT_FOUND":
                        return None, f"ERROR: Organization not found - {error_msg}"

                    # Generic GraphQL Error
                    logging.error(f"  [ERROR] {org_login}: {error_msg}")
                    return None, f"ERROR: GraphQL - {error_type}: {error_msg}"

                # Check if organization data exists
                if not json_resp.get("data"):
                    return (
                        None,
                        "ERROR: No data in response - possible authentication issue",
                    )

                if not json_resp.get("data", {}).get("organization"):
                    return (
                        None,
                        "ERROR: Organization not found or no access permissions",
                    )

                repos_node = json_resp["data"]["organization"]["repositories"]

                for repo in repos_node["nodes"]:
                    # Skip archived repos if you want (optional)
                    # if repo['isArchived']: continue

                    total_size = repo["languages"]["totalSize"]

                    # Handle empty languages
                    if not repo["languages"]["edges"]:
                        repo_data.append(
                            {
                                "Organization": org_login,
                                "Repository": repo["name"],
                                "Language": "None",
                                "Bytes": 0,
                                "Percentage": 0.0,
                            }
                        )
                        continue

                    for edge in repo["languages"]["edges"]:
                        size = edge["size"]
                        percentage = (size / total_size * 100) if total_size > 0 else 0

                        repo_data.append(
                            {
                                "Organization": org_login,
                                "Repository": repo["name"],
                                "Language": edge["node"]["name"],
                                "Bytes": size,
                                "Percentage": round(percentage, 2),
                            }
                        )

                has_next = repos_node["pageInfo"]["hasNextPage"]
                cursor = repos_node["pageInfo"]["endCursor"]

            except requests.exceptions.Timeout:
                logging.error(f"Timeout for {org_login}")
                return None, "ERROR: Request timeout - organization may be too large"
            except requests.exceptions.ConnectionError:
                logging.error(f"Connection error for {org_login}")
                return None, "ERROR: Network connection error"
            except requests.exceptions.RequestException as e:
                logging.error(f"Request exception for {org_login}: {e}")
                return None, f"ERROR: Request failed - {str(e)}"
            except Exception as e:
                logging.error(f"Unexpected exception for {org_login}: {e}")
                return None, f"ERROR: Unexpected error - {str(e)}"

        return repo_data, "SUCCESS"


def main():
    # Start timing
    start_time = datetime.now()

    # Setup enhanced logging with file output
    timestamp = start_time.strftime("%Y%m%d_%H%M%S")
    log_dir = "scripts/fetch_languages/output/logs"
    os.makedirs(log_dir, exist_ok=True)

    # Create detailed log file
    log_filename = os.path.join(log_dir, f"language_scan_{timestamp}.log")

    # Enhanced logging configuration
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Create formatter
    detailed_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
    )
    simple_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    file_handler.setFormatter(detailed_formatter)
    console_handler.setFormatter(simple_formatter)

    # Get root logger and configure
    logger = logging.getLogger()
    logger.handlers.clear()  # Clear existing handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.setLevel(logging.DEBUG)

    logging.info(
        f"=== GitHub Language Scanner Started at {start_time.strftime('%Y-%m-%d %H:%M:%S')} ==="
    )
    logging.info(f"Log file: {log_filename}")
    logging.info(f"Enterprise: {ENTERPRISE_SLUG}")

    scanner = GitHubScanner(GITHUB_TOKEN, ENTERPRISE_SLUG)

    # 1. Get List of Organizations from CSV first, fallback to REST API
    csv_start_time = time.time()
    logging.info("Attempting to load organizations from CSV file...")
    org_list = scanner.get_organizations_from_csv()
    csv_load_time = time.time() - csv_start_time
    logging.info(f"CSV loading completed in {csv_load_time:.2f} seconds")

    # # Limit to top 10 organizations for testing
    # if len(org_list) > 10:
    #     logging.info(
    #         f"Limiting to top 10 organizations for testing (out of {len(org_list)} total)"
    #     )
    #     org_list = org_list[:10]

    logging.info(f"Total Organizations to scan: {len(org_list)}")

    if not org_list:
        logging.error(
            "No organizations found. Please ensure CSV file exists or REST API access is available."
        )
        return

    # Setup output files (reuse timestamp from start)
    output_dir = "scripts/fetch_languages/output"
    os.makedirs(output_dir, exist_ok=True)

    filename = os.path.join(output_dir, f"languages_report_{timestamp}.csv")
    error_filename = os.path.join(output_dir, f"languages_errors_{timestamp}.csv")

    # Create CSV files with headers
    headers = ["Organization", "Repository", "Language", "Bytes", "Percentage"]
    error_headers = [
        "Organization",
        "Error_Type",
        "Error_Message",
        "Timestamp",
        "HTTP_Status",
    ]

    # Initialize CSV files with headers
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

    with open(error_filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(error_headers)

    logging.info(f"Created report file: {filename}")
    logging.info(f"Created error log file: {error_filename}")

    all_data = []
    total_processed = 0
    org_timings = []
    processing_start_time = time.time()

    # 2. Iterate and Scan (GraphQL)
    logging.info("=== Starting Organization Processing ===")
    for i, org in enumerate(org_list, 1):
        org_start_time = time.time()
        print("-" * 60)
        logging.info(f"Processing {i}/{len(org_list)}: {org}")

        data, status = scanner.fetch_repo_languages(org)
        org_end_time = time.time()
        org_duration = org_end_time - org_start_time

        if data is not None:
            # Append data immediately to CSV
            with open(filename, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                for record in data:
                    writer.writerow(record)

            all_data.extend(data)
            total_processed += len(data)

            # Log timing information
            repos_count = len(set(record["Repository"] for record in data))
            org_timings.append(
                {
                    "organization": org,
                    "duration": org_duration,
                    "repositories": repos_count,
                    "language_records": len(data),
                    "status": "SUCCESS",
                }
            )

            logging.info(
                f"  > Successfully fetched {len(data)} language records from {repos_count} repos in {org_duration:.2f}s. Total so far: {total_processed}"
            )
        else:
            # Parse error details for better logging
            error_type = "UNKNOWN"
            error_message = status
            http_status = "N/A"

            if status.startswith("ERROR: HTTP"):
                # Extract HTTP status code
                parts = status.split(" ")
                if len(parts) >= 3:
                    http_status = parts[2]
                    error_type = "HTTP_ERROR"
            elif status.startswith("ERROR: Token Policy"):
                error_type = "TOKEN_POLICY"
            elif status.startswith("ERROR: SAML"):
                error_type = "SAML_RESTRICTION"
            elif status.startswith("ERROR: Organization not found"):
                error_type = "ORG_NOT_FOUND"
            elif status.startswith("ERROR: Unauthorized"):
                error_type = "UNAUTHORIZED"
                http_status = "401"
            elif status.startswith("ERROR: Forbidden"):
                error_type = "FORBIDDEN"
                http_status = "403"
            elif status.startswith("ERROR: Request timeout"):
                error_type = "TIMEOUT"
            elif status.startswith("ERROR: Network"):
                error_type = "NETWORK_ERROR"

            # Append error to CSV immediately
            error_record = {
                "Organization": org,
                "Error_Type": error_type,
                "Error_Message": error_message,
                "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "HTTP_Status": http_status,
            }

            with open(error_filename, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=error_headers)
                writer.writerow(error_record)

            # Record timing for failed organization
            org_timings.append(
                {
                    "organization": org,
                    "duration": org_duration,
                    "repositories": 0,
                    "language_records": 0,
                    "status": error_type,
                }
            )

            logging.error(
                f"  > Organization failed: {org} - {status} (took {org_duration:.2f}s)"
            )

    # Calculate total processing time
    total_processing_time = time.time() - processing_start_time

    # Create timing report
    timing_filename = os.path.join(log_dir, f"timing_report_{timestamp}.csv")
    timing_headers = [
        "organization",
        "duration_seconds",
        "repositories",
        "language_records",
        "status",
    ]

    with open(timing_filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=timing_headers)
        writer.writeheader()
        for timing in org_timings:
            writer.writerow(
                {
                    "organization": timing["organization"],
                    "duration_seconds": round(timing["duration"], 2),
                    "repositories": timing["repositories"],
                    "language_records": timing["language_records"],
                    "status": timing["status"],
                }
            )

    logging.info(f"Timing report saved to: {timing_filename}")
    logging.info(f"=== Processing completed in {total_processing_time:.2f} seconds ===")

    # 3. Generate Final Summary Report
    if all_data:
        logging.info("Generating summary report...")

        # Create summary
        df_data = pd.DataFrame(all_data)
        summary = (
            df_data.groupby("Language")["Bytes"]
            .sum()
            .sort_values(ascending=False)
            .reset_index()
        )
        total_bytes = summary["Bytes"].sum()
        summary["Global_Share_%"] = (summary["Bytes"] / total_bytes * 100).round(2)

        # Save summary
        summary_filename = os.path.join(
            output_dir, f"languages_summary_{timestamp}.csv"
        )
        summary.to_csv(summary_filename, index=False)
        logging.info(f"Languages summary saved to: {summary_filename}")

    # Calculate and log final statistics
    end_time = datetime.now()
    total_execution_time = (end_time - start_time).total_seconds()

    successful_orgs = [t for t in org_timings if t["status"] == "SUCCESS"]
    failed_orgs = [t for t in org_timings if t["status"] != "SUCCESS"]

    # Calculate timing statistics
    if successful_orgs:
        avg_time_per_org = sum(t["duration"] for t in successful_orgs) / len(
            successful_orgs
        )
        max_time = max(t["duration"] for t in successful_orgs)
        min_time = min(t["duration"] for t in successful_orgs)
        slowest_org = max(successful_orgs, key=lambda x: x["duration"])
    else:
        avg_time_per_org = max_time = min_time = 0
        slowest_org = None

    logging.info(f"Done! Total language records processed: {total_processed}")
    logging.info(f"Detailed report: {filename}")
    logging.info(f"Error log: {error_filename}")
    logging.info(f"Timing report: {timing_filename}")

    # Final execution summary
    logging.info("=== EXECUTION SUMMARY ===")
    logging.info(
        f"Total execution time: {total_execution_time:.2f} seconds ({total_execution_time/60:.1f} minutes)"
    )
    logging.info(f"Organizations processed: {len(org_list)}")
    logging.info(f"Successful organizations: {len(successful_orgs)}")
    logging.info(f"Failed organizations: {len(failed_orgs)}")

    if successful_orgs:
        logging.info(f"Average time per successful org: {avg_time_per_org:.2f} seconds")
        logging.info(f"Fastest organization: {min_time:.2f} seconds")
        logging.info(
            f"Slowest organization: {max_time:.2f} seconds ({slowest_org['organization']})"
        )

    logging.info(
        f"Processing rate: {total_processed/total_execution_time:.1f} language records per second"
    )
    logging.info(f"=== Scan completed at {end_time.strftime('%Y-%m-%d %H:%M:%S')} ===")

    # Show final statistics
    try:
        with open(error_filename, "r") as f:
            error_count = sum(1 for line in f) - 1  # Subtract header row
        if error_count > 0:
            logging.warning(f"Total organizations with errors: {error_count}")
        else:
            logging.info("All organizations processed successfully!")
    except:
        pass


if __name__ == "__main__":
    main()
