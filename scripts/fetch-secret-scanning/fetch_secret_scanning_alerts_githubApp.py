import os
import sys
import json
import logging
import itertools
import time
import asyncio
import tracemalloc
import psutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple, Optional, Generator, Union
from functools import wraps, lru_cache
from collections import defaultdict, Counter
from dataclasses import dataclass, field

import requests
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

# Add the parent directory to the path to import github_auth
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from github_auth.github_app_auth import GitHubAppAuth

# --- Configuration ---
# Set up enhanced logging with both console and file output
# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Get the root directory (two levels up from this script)
root_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))

# Ensure output directories exist under scripts/output/fetch_secret_scanning
output_dir = os.path.join(script_dir, "..", "output", "fetch_secret_scanning")
logs_dir = os.path.join(output_dir, "logs")
os.makedirs(output_dir, exist_ok=True)
os.makedirs(logs_dir, exist_ok=True)

log_filename = os.path.join(
    logs_dir, f"security_alerts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s",
    handlers=[logging.FileHandler(log_filename), logging.StreamHandler()],
)

# Load environment variables from .env file in root directory
dotenv_path = os.path.join(root_dir, ".env")
load_dotenv(dotenv_path=dotenv_path)
print(f"Loading .env from: {dotenv_path}")

# Configurable Constants (loaded from environment with defaults)
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "2"))  # seconds
TIMEOUT = int(os.getenv("TIMEOUT", "30"))  # seconds
MAX_CONCURRENT_ORGS = int(os.getenv("MAX_CONCURRENT_ORGS", "5"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.5"))  # seconds between requests
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))  # alerts per chunk for processing
SESSION_POOL_SIZE = int(os.getenv("SESSION_POOL_SIZE", "10"))
MEMORY_THRESHOLD_MB = int(
    os.getenv("MEMORY_THRESHOLD_MB", "1000")
)  # Memory usage warning threshold
RATE_LIMIT_BUFFER = int(
    os.getenv("RATE_LIMIT_BUFFER") or "100"
)  # Remaining requests before slowing down


@dataclass
class PerformanceMetrics:
    """Track performance metrics during execution"""

    start_time: float = field(default_factory=time.time)
    organizations_processed: int = 0
    organizations_failed: int = 0
    total_alerts: int = 0
    api_requests: int = 0
    memory_peak_mb: float = 0
    processing_times: Dict[str, float] = field(default_factory=dict)

    def log_summary(self):
        """Log performance summary"""
        elapsed = time.time() - self.start_time
        logging.info("=" * 50)
        logging.info("PERFORMANCE METRICS SUMMARY")
        logging.info("=" * 50)
        logging.info(f"Total Execution Time: {elapsed:.2f}s")
        logging.info(f"Organizations Processed: {self.organizations_processed}")
        logging.info(f"Organizations Failed: {self.organizations_failed}")
        logging.info(f"Total Alerts Fetched: {self.total_alerts}")
        logging.info(f"API Requests Made: {self.api_requests}")
        logging.info(f"Peak Memory Usage: {self.memory_peak_mb:.1f} MB")
        if self.processing_times:
            logging.info("Processing Times:")
            for stage, duration in self.processing_times.items():
                logging.info(f"  - {stage}: {duration:.2f}s")
        logging.info("=" * 50)


def validate_configuration() -> bool:
    """Validate configuration and environment setup"""
    errors = []
    warnings = []

    # Validate required environment variables
    required_vars = ["GH_ENTERPRISE_SLUG"]
    for var in required_vars:
        if not os.getenv(var):
            errors.append(f"Missing required environment variable: {var}")

    # Validate numeric configurations
    numeric_configs = {
        "MAX_RETRIES": (1, 10),
        "TIMEOUT": (10, 300),
        "MAX_CONCURRENT_ORGS": (1, 20),
        "CHUNK_SIZE": (100, 10000),
        "RATE_LIMIT_BUFFER": (10, 1000),
    }

    for var, (min_val, max_val) in numeric_configs.items():
        try:
            value = int(os.getenv(var, "0"))
            if not (min_val <= value <= max_val):
                warnings.append(
                    f"{var} value {value} outside recommended range ({min_val}-{max_val})"
                )
        except ValueError:
            errors.append(f"Invalid numeric value for {var}: {os.getenv(var)}")

    # Log validation results
    if errors:
        for error in errors:
            logging.error(f"Configuration Error: {error}")
        return False

    if warnings:
        for warning in warnings:
            logging.warning(f"Configuration Warning: {warning}")

    logging.info("Configuration validation passed")
    return True


def monitor_memory() -> float:
    """Monitor current memory usage"""
    try:
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        if memory_mb > MEMORY_THRESHOLD_MB:
            logging.warning(f"High memory usage detected: {memory_mb:.1f} MB")
        return memory_mb
    except Exception:
        return 0


def create_session_with_retries() -> requests.Session:
    """Create a requests session with retry strategy and connection pooling"""
    session = requests.Session()

    # Configure retry strategy
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
    )

    # Configure adapter with connection pooling
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=SESSION_POOL_SIZE,
        pool_maxsize=SESSION_POOL_SIZE,
    )

    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


# --- Helper Functions ---


def retry_on_failure(max_retries: int = MAX_RETRIES, delay: int = RETRY_DELAY):
    """
    Decorator to retry functions that may fail due to transient errors.

    Args:
        max_retries (int): Maximum number of retry attempts
        delay (int): Delay between retries in seconds
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (
                    requests.exceptions.RequestException,
                    requests.exceptions.HTTPError,
                ) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait_time = delay * (2**attempt)  # Exponential backoff
                        logging.warning(
                            f"Attempt {attempt + 1}/{max_retries} failed for {func.__name__}: {e}. "
                            f"Retrying in {wait_time}s..."
                        )
                        time.sleep(wait_time)
                    else:
                        logging.error(
                            f"All {max_retries} attempts failed for {func.__name__}: {e}"
                        )
            raise last_exception

        return wrapper

    return decorator


def safe_get(dictionary: Dict, *keys, default=None) -> Any:
    """
    Safely navigate nested dictionaries without KeyError.

    Args:
        dictionary (dict): The dictionary to navigate
        *keys: Sequence of keys to traverse
        default: Default value if key path doesn't exist

    Returns:
        The value at the key path or default value
    """
    result = dictionary
    for key in keys:
        if isinstance(result, dict):
            result = result.get(key, {})
        else:
            return default
    return result if result != {} else default


def extract_alert_data(
    alerts: List[Dict], field_mapping: Dict[str, tuple], alert_type: str
) -> List[Dict]:
    """
    Generic function to extract alert data using field mappings.

    Args:
        alerts (list): List of alert dictionaries
        field_mapping (dict): Mapping of output field names to nested key paths
        alert_type (str): Type of alert for logging purposes

    Returns:
        list: Extracted data as list of dictionaries
    """
    extracted_data = []
    errors = 0

    for idx, alert in enumerate(alerts):
        try:
            record = {}
            for field_name, key_path in field_mapping.items():
                if callable(key_path):
                    # Handle custom extraction functions
                    record[field_name] = key_path(alert)
                else:
                    # Handle nested dictionary navigation
                    record[field_name] = safe_get(alert, *key_path)
            extracted_data.append(record)
        except Exception as e:
            errors += 1
            logging.error(
                f"Error extracting {alert_type} alert at index {idx}: {e}. "
                f"Alert number: {safe_get(alert, 'number', default='unknown')}"
            )

    if errors > 0:
        logging.warning(
            f"Encountered {errors} errors while extracting {len(alerts)} {alert_type} alerts"
        )

    return extracted_data


def parse_organization_name(org_name: str) -> Tuple[str, str]:
    """
    Parse organization name to extract Project_Code and Cost_Center.

    Expected format: xxxxx-yyyyy-zzzzz (exactly 3 parts)
    - xxxxx: Project_Code (first part)
    - zzzzz: Cost_Center (last part)

    Invalid formats (treated as NO PROJECT CODE / NO COST CENTER):
    - Less than 3 parts
    - More than 3 parts (e.g., 'xxxxx-yyyyy-zzzzz-aaaaa')

    Args:
        org_name: Organization name string

    Returns:
        Tuple of (Project_Code, Cost_Center)
    """
    if not org_name:
        return "NO PROJECT CODE", "NO COST CENTER"

    parts = org_name.split("-")

    # Check if the format has exactly 3 parts separated by '-'
    if len(parts) == 3:
        project_code = parts[0]
        cost_center = parts[2]  # Last part (third part)
        return project_code, cost_center
    else:
        return "NO PROJECT CODE", "NO COST CENTER"


def extract_repository_info(repo_full_name: str) -> Tuple[str, str, str, str]:
    """Extract organization and repository info once to avoid duplicate calculations"""
    if not repo_full_name or "/" not in repo_full_name:
        return None, None, "NO PROJECT CODE", "NO COST CENTER"

    parts = repo_full_name.split("/")
    org_name = parts[0]
    repo_name = parts[1] if len(parts) > 1 else repo_full_name
    project_code, cost_center = parse_organization_name(org_name)

    return org_name, repo_name, project_code, cost_center


def extract_secret_scanning_data(alerts: List[Dict]) -> Generator[Dict, None, None]:
    """
    Extract relevant fields from secret scanning alerts using generator for memory efficiency.
    """
    errors = 0
    processed = 0

    for alert in alerts:
        try:
            # Extract repository info once
            repo_full_name = safe_get(alert, "repository", "full_name")
            org_name, repo_name, project_code, cost_center = extract_repository_info(
                repo_full_name
            )

            # Build record efficiently
            record = {
                "Alert_Number": safe_get(alert, "number"),
                "Organization_Name": org_name,
                "Repository_Name": repo_name,
                "Project_Code": project_code,
                "Cost_Center": cost_center,
                "Secret_Type": safe_get(alert, "secret_type_display_name"),
                "Secret_Type_ID": safe_get(alert, "secret_type"),
                "State": safe_get(alert, "state"),
                "Created_At": safe_get(alert, "created_at"),
                "Updated_At": safe_get(alert, "updated_at"),
                "URL": safe_get(alert, "html_url"),
                "Validity": safe_get(alert, "validity"),
                "Resolution": safe_get(alert, "resolution"),
                "Resolved_By": safe_get(alert, "resolved_by", "login"),
                "Resolved_At": safe_get(alert, "resolved_at"),
                "Publicly_Leaked": safe_get(alert, "publicly_leaked"),
                "Push_Protection_Bypassed": safe_get(alert, "push_protection_bypassed"),
                "Location_Path": safe_get(alert, "first_location_detected", "path"),
                "Location_Start_Line": safe_get(
                    alert, "first_location_detected", "start_line"
                ),
                "Location_End_Line": safe_get(
                    alert, "first_location_detected", "end_line"
                ),
                "Location_Start_Column": safe_get(
                    alert, "first_location_detected", "start_column"
                ),
                "Location_End_Column": safe_get(
                    alert, "first_location_detected", "end_column"
                ),
                "Location_Blob_Sha": safe_get(
                    alert, "first_location_detected", "blob_sha"
                ),
                "Location_Blob_URL": safe_get(
                    alert, "first_location_detected", "blob_url"
                ),
                # Commit fields (populated later if enrichment enabled)
                "Commit_Author": None,
                "Commit_Committer": None,
                "Commit_SHA": None,
            }

            yield record
            processed += 1

            # Monitor memory every 1000 alerts
            if processed % 1000 == 0:
                monitor_memory()

        except Exception as e:
            errors += 1
            logging.error(f"Error extracting secret alert at index {processed}: {e}")
            continue

    if errors > 0:
        logging.warning(
            f"Encountered {errors} errors while extracting {processed} secret scanning alerts"
        )


def count_by_field(data: List[Dict], field: str, value: Any) -> int:
    """
    Count occurrences of a specific value in a field across all records.

    Args:
        data (list): List of dictionaries
        field (str): Field name to check
        value: Value to count

    Returns:
        int: Count of matching records
    """
    return sum(1 for item in data if item.get(field) == value)


def create_summary_data(
    secret_scanning_data: List[Dict],
    alert_state: str = "open",
    timestamp: str = None,
) -> List[Dict]:
    """
    Create summary statistics for secret scanning alerts.

    Args:
        secret_scanning_data: Secret scanning alerts data
        alert_state: The state filter used for the query
        timestamp: The timestamp of the query execution

    Returns:
        List of summary dictionaries with query metadata
    """
    try:
        summary = []

        # Add query metadata row
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        summary.append(
            {
                "Alert_Type": "Query Information",
                "Query_Timestamp": timestamp,
                "Alert_State_Filter": alert_state,
                "Secret_Scanning_Queried": "Yes",
            }
        )

        # Calculate counts efficiently using Counter
        validity_counts = Counter(
            alert.get("Validity") for alert in secret_scanning_data
        )
        leaked_count = sum(
            1 for alert in secret_scanning_data if alert.get("Publicly_Leaked")
        )

        summary.append(
            {
                "Alert_Type": "Secret Scanning",
                "Total_Count": len(secret_scanning_data),
                "Active_Secrets": validity_counts.get("active", 0),
                "Inactive_Secrets": validity_counts.get("inactive", 0),
                "Unknown_Validity": validity_counts.get("unknown", 0),
                "Publicly_Leaked": leaked_count,
            }
        )

        logging.info(
            f"Successfully created summary statistics for secret scanning alerts"
        )
        return summary
    except Exception as e:
        logging.error(f"Error creating summary data: {e}")
        return []


def validate_pat(pat: str) -> bool:
    """
    Validate PAT format (basic check).

    Args:
        pat (str): Personal Access Token

    Returns:
        bool: True if format looks valid
    """
    pat = pat.strip()
    # GitHub PATs typically start with ghp_, gho_, ghs_, etc. and are 40+ chars
    if len(pat) < 20:
        return False
    if pat.startswith(("ghp_", "gho_", "ghs_", "ghu_", "ghr_")):
        return True
    # Legacy tokens (40 hex chars)
    if len(pat) == 40 and all(c in "0123456789abcdef" for c in pat.lower()):
        return True
    logging.warning(f"PAT format may be invalid: {pat[:10]}...")
    return True  # Allow through but warn


def load_alert_config() -> Dict[str, Any]:
    """
    Load alert fetching configuration from environment variables.
    Can be set in .env file or GitHub Actions environment.

    Environment Variables:
        ALERT_STATE: Alert state to fetch - open, resolved, all (default: all)
        OUTPUT_FILENAME: Custom output filename without extension (default: secret_scanning_report)
        OUTPUT_FORMAT: Output format - xlsx, csv, both (default: csv)
        TEST_MODE: Enable test mode to limit organizations (default: false)
        TEST_ORG_LIMIT: Number of organizations to process in test mode (default: 10)

    Returns:
        dict: Configuration dictionary
    """

    config = {
        "state": os.getenv("ALERT_STATE", "all").lower(),
        "output": os.getenv("OUTPUT_FILENAME", "secret_scanning_report"),
        "format": os.getenv("OUTPUT_FORMAT", "csv").lower(),
        "test_mode": os.getenv("TEST_MODE", "false").lower() in ["true", "1", "yes"],
        "test_org_limit": int(os.getenv("TEST_ORG_LIMIT", "10")),
    }

    # Validate state (Secret scanning supports: open, resolved)
    valid_states = ["open", "resolved", "all"]
    if config["state"] not in valid_states:
        logging.warning(
            f"Invalid ALERT_STATE '{config['state']}'. Using 'all'. "
            f"Valid options for secret scanning: {', '.join(valid_states)}"
        )
        config["state"] = "all"

    # Validate format
    valid_formats = ["xlsx", "csv", "both"]
    if config["format"] not in valid_formats:
        logging.warning(
            f"Invalid OUTPUT_FORMAT '{config['format']}'. Using 'csv'. "
            f"Valid options: {', '.join(valid_formats)}"
        )
        config["format"] = "csv"

    logging.info("Configuration loaded from environment variables:")
    logging.info(f"  - Alert State: {config['state']}")
    logging.info(f"  - Output Format: {config['format']}")
    logging.info(f"  - Output Filename: {config['output']}")
    logging.info(f"  - Test Mode: {config['test_mode']}")
    if config["test_mode"]:
        logging.info(f"  - Test Org Limit: {config['test_org_limit']}")

    # Enrichment is always enabled
    logging.info(f"  - Commit Enrichment: Enabled")
    logging.info(f"  - Repo Admin Enrichment: Enabled")

    return config


def load_config() -> Tuple[str, GitHubAppAuth]:
    """
    Loads configuration from environment variables with validation.
    Sets up GitHub App authentication.

    Returns:
        tuple: (enterprise_slug, GitHubAppAuth instance)
    """
    enterprise_slug = os.getenv("GH_ENTERPRISE_SLUG")

    if not enterprise_slug:
        logging.error("FATAL: GH_ENTERPRISE_SLUG environment variable not set.")
        exit(1)

    if not enterprise_slug.replace("-", "").replace("_", "").isalnum():
        logging.error(f"FATAL: Invalid GH_ENTERPRISE_SLUG format: {enterprise_slug}")
        exit(1)

    # Initialize GitHub App authentication
    try:
        github_app_auth = GitHubAppAuth()
        logging.info(f"Successfully initialized GitHub App authentication")
    except Exception as e:
        logging.error(f"FATAL: Failed to initialize GitHub App auth: {e}")
        exit(1)

    logging.info(f"Loaded configuration for enterprise: '{enterprise_slug}'")

    return enterprise_slug, github_app_auth


def fetch_organizations_from_csv(csv_path: str = None) -> List[str]:
    """
    Fetch organizations from a CSV file.

    Args:
        csv_path: Path to CSV file with organizations. If None, uses default locations.

    Returns:
        List of organization login names
    """
    import csv

    # Try multiple locations for the CSV file
    possible_paths = []

    if csv_path:
        possible_paths.append(csv_path)

    # Check common locations
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))

    possible_paths.extend(
        [
            os.path.join(root_dir, "organizations.csv"),
            os.path.join(script_dir, "organizations.csv"),
            os.path.join(root_dir, "scripts", "output", "organizations.csv"),
        ]
    )

    csv_file = None
    for path in possible_paths:
        if os.path.exists(path):
            csv_file = path
            break

    if not csv_file:
        logging.warning(
            f"Organizations CSV file not found. Tried locations:\n"
            + "\n".join(f"  - {p}" for p in possible_paths)
        )
        logging.info("Attempting to generate organizations.csv using fetch_orgs.py...")

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
                        csv_file = output_csv
                        logging.info(f"Organizations CSV file created at: {csv_file}")
                    else:
                        logging.error(
                            "fetch_orgs.py completed but organizations.csv not found at expected location"
                        )
                else:
                    logging.error(f"fetch_orgs.py failed with error: {result.stderr}")
            except Exception as e:
                logging.error(f"Failed to execute fetch_orgs.py: {e}")
        else:
            logging.error(f"fetch_orgs.py not found at: {fetch_orgs_path}")

        if not csv_file:
            logging.error(
                "Please create an organizations.csv file with a 'login' column containing org names, "
                "or ensure fetch_orgs.py is available and working properly."
            )
            return []

    logging.info(f"Reading organizations from: {csv_file}")

    organizations = []
    try:
        with open(csv_file, "r", encoding="utf-8") as f:
            # First, try reading as CSV with headers
            first_line = f.readline().strip()
            f.seek(0)  # Reset to beginning
            
            # Check if first line looks like a header
            if first_line.lower() in ['login', 'organization', 'org', 'name']:
                # Has header, use DictReader
                reader = csv.DictReader(f)
                for row in reader:
                    org_name = (
                        row.get("login")
                        or row.get("organization")
                        or row.get("org")
                        or row.get("name")
                    )
                    if org_name:
                        organizations.append(org_name.strip())
            else:
                # No header, read as plain CSV (each line is an org name)
                reader = csv.reader(f)
                for row in reader:
                    if row and row[0].strip():
                        organizations.append(row[0].strip())

        logging.info(f"Loaded {len(organizations)} organizations from CSV")
        return organizations

    except Exception as e:
        logging.error(f"Error reading organizations CSV: {e}")
        return []


def fetch_organizations(
    enterprise_slug: str, github_app_auth: GitHubAppAuth
) -> List[str]:
    """
    Fetch all organizations from CSV file.
    GitHub App authentication doesn't have enterprise-level GraphQL access,
    so we read from a pre-generated CSV file.

    Args:
        enterprise_slug: The enterprise slug (for logging purposes)
        github_app_auth: GitHub App authentication instance (not used for org fetching)

    Returns:
        List of organization login names
    """
    logging.info(f"Fetching organizations for enterprise: {enterprise_slug}")
    logging.info(
        "Note: Using CSV file approach (GitHub App doesn't have enterprise GraphQL access)"
    )

    return fetch_organizations_from_csv()


@retry_on_failure()
def fetch_commit_info(
    repo_full_name: str, blob_sha: str, session: requests.Session
) -> Dict:
    """
    Fetch commit information for a specific blob SHA.

    Args:
        repo_full_name: Full repository name (owner/repo)
        blob_sha: The blob SHA from the secret location
        session: Authenticated session

    Returns:
        Dict with commit author and committer information
    """
    if not blob_sha or not repo_full_name:
        return {"author": None, "committer": None, "sha": None}

    try:
        # Search for commits that modified the file
        url = f"https://api.github.com/repos/{repo_full_name}/commits"
        params = {"per_page": 10}  # Get recent commits

        response = session.get(url, params=params, timeout=TIMEOUT)
        response.raise_for_status()

        commits = response.json()

        # For now, return the most recent commit info
        # In a more sophisticated approach, you'd need to find the specific commit
        # that introduced the secret at the blob_sha location
        if commits:
            latest_commit = commits[0]
            return {
                "author": safe_get(latest_commit, "commit", "author", "name"),
                "committer": safe_get(latest_commit, "commit", "committer", "name"),
                "sha": safe_get(latest_commit, "sha"),
            }

    except Exception as e:
        logging.warning(f"Failed to fetch commit info for {repo_full_name}: {e}")

    return {"author": None, "committer": None, "sha": None}


@retry_on_failure()
def fetch_user_email(
    username: str, session: requests.Session, repo_full_name: str = None
) -> Optional[str]:
    """
    Fetch email address for a specific user.
    First tries the public profile, then falls back to commit history if a repo is provided.

    Args:
        username: GitHub username
        session: Authenticated session
        repo_full_name: Optional repository name to search commit history

    Returns:
        User's email address or None if not available
    """
    try:
        # First, try to get email from public profile
        url = f"https://api.github.com/users/{username}"
        response = session.get(url, timeout=TIMEOUT)
        response.raise_for_status()

        user_data = response.json()
        email = user_data.get("email")

        # If no email from profile and we have a repo, try to get it from commit history
        if not email and repo_full_name:
            try:
                commits_url = f"https://api.github.com/repos/{repo_full_name}/commits"
                params = {"author": username, "per_page": 10}
                commits_response = session.get(
                    commits_url, params=params, timeout=TIMEOUT
                )
                commits_response.raise_for_status()

                commits = commits_response.json()
                # Look through recent commits for an email
                for commit in commits:
                    commit_email = safe_get(commit, "commit", "author", "email")
                    # Filter out noreply emails if possible
                    if commit_email and "@users.noreply.github.com" not in commit_email:
                        logging.debug(
                            f"Found email for {username} from commit history: {commit_email}"
                        )
                        return commit_email
                    elif commit_email:
                        # Save noreply email as fallback
                        email = commit_email
            except Exception as commit_error:
                logging.debug(
                    f"Failed to fetch email from commits for {username}: {commit_error}"
                )

        return email

    except Exception as e:
        logging.debug(f"Failed to fetch email for {username}: {e}")
        return None


@retry_on_failure()
def fetch_repository_admins(
    repo_full_name: str, session: requests.Session
) -> List[str]:
    """
    Fetch repository administrators (users with admin permissions).

    Args:
        repo_full_name: Full repository name (owner/repo)
        session: Authenticated session

    Returns:
        List of usernames with admin permissions
    """
    try:
        # Fetch collaborators with admin permission
        url = f"https://api.github.com/repos/{repo_full_name}/collaborators"
        params = {"permission": "admin", "per_page": 100}

        response = session.get(url, params=params, timeout=TIMEOUT)
        response.raise_for_status()

        collaborators = response.json()
        admin_users = [
            collaborator.get("login")
            for collaborator in collaborators
            if collaborator.get("login")
        ]

        logging.debug(f"Found {len(admin_users)} admin users for {repo_full_name}")
        return admin_users

    except Exception as e:
        logging.debug(f"Failed to fetch repository admins for {repo_full_name}: {e}")
        return []


def enrich_secret_data_with_commit_details(
    secret_data: List[Dict], session: requests.Session
) -> List[Dict]:
    """
    Enrich secret scanning data with commit author information.
    This function is separate and not called by default to save API rate limits.

    Args:
        secret_data: List of secret scanning alerts
        session: Authenticated session

    Returns:
        Enriched list of alerts with commit information
    """
    logging.info("Enriching secret scanning data with commit information...")

    enriched_data = []

    for idx, alert in enumerate(secret_data):
        try:
            repo_full_name = (
                f"{alert.get('Organization_Name')}/{alert.get('Repository_Name')}"
            )
            blob_sha = alert.get("Location_Blob_Sha")

            # Fetch commit information
            if (
                blob_sha
                and repo_full_name
                and alert.get("Organization_Name")
                and alert.get("Repository_Name")
            ):
                commit_info = fetch_commit_info(repo_full_name, blob_sha, session)
                alert["Commit_Author"] = commit_info.get("author")
                alert["Commit_Committer"] = commit_info.get("committer")
                alert["Commit_SHA"] = commit_info.get("sha")
            else:
                alert["Commit_Author"] = None
                alert["Commit_Committer"] = None
                alert["Commit_SHA"] = None

            enriched_data.append(alert)

            # Log progress every 50 items
            if (idx + 1) % 50 == 0:
                logging.info(f"Processed {idx + 1}/{len(secret_data)} alerts...")

        except Exception as e:
            logging.error(f"Error enriching alert {idx} with commit info: {e}")
            enriched_data.append(alert)  # Add original alert even if enrichment fails

    logging.info(f"Completed commit enrichment for {len(enriched_data)} alerts")
    return enriched_data


def check_rate_limit(response: requests.Response, metrics: PerformanceMetrics) -> None:
    """Check and handle rate limiting with adaptive backoff"""
    remaining = response.headers.get("X-RateLimit-Remaining")
    reset_time = response.headers.get("X-RateLimit-Reset")

    if remaining:
        try:
            remaining_count = int(remaining)
            # Ensure RATE_LIMIT_BUFFER is always an int
            try:
                buffer = int(RATE_LIMIT_BUFFER)
            except (ValueError, TypeError):
                buffer = 100  # Default fallback
            
            if remaining_count < buffer:
                if reset_time:
                    reset_timestamp = int(reset_time)
                    current_time = int(time.time())
                    wait_time = max(0, reset_timestamp - current_time) + 5
                    logging.warning(
                        f"Rate limit approaching ({remaining_count} remaining). Waiting {wait_time}s..."
                    )
                    time.sleep(wait_time)
                else:
                    # Default wait if no reset time
                    time.sleep(60)
        except (ValueError, TypeError) as e:
            logging.debug(f"Error parsing rate limit headers: {e}")
            pass


@retry_on_failure()
def fetch_all_pages(
    endpoint_url: str,
    session: requests.Session,
    params: Optional[Dict] = None,
    metrics: Optional[PerformanceMetrics] = None,
) -> List[Dict]:
    """
    Fetches all pages of results from a GitHub API endpoint with intelligent rate limiting.
    Uses authenticated session from GitHub App.

    Args:
        endpoint_url (str): The initial URL for the API endpoint.
        session (requests.Session): Authenticated session from GitHub App.
        params (dict): Query parameters for the request.
        metrics (PerformanceMetrics): Performance tracking object.

    Returns:
        list: A list containing all items from all pages.
    """
    all_results = []
    url = endpoint_url
    page_count = 0

    if metrics:
        metrics.api_requests += 1

    while url:
        try:
            # Add delay between requests to be respectful
            if page_count > 0:
                time.sleep(REQUEST_DELAY)

            response = session.get(url, params=params, timeout=TIMEOUT)

            if metrics:
                metrics.api_requests += 1

            # Clear params after the first request as they are included in the 'next' URL
            params = None

            response.raise_for_status()  # Raises an exception for 4XX or 5XX status codes

            # Check and handle rate limiting
            if metrics:
                check_rate_limit(response, metrics)

            data = response.json()

            # Handle different response formats
            if isinstance(data, list):
                all_results.extend(data)
            elif isinstance(data, dict):
                # Some endpoints return a dictionary with an 'items' or other key
                items = data.get("items", data.get("data", []))
                if items:
                    all_results.extend(items if isinstance(items, list) else [items])
                else:
                    # If no known key, assume the whole dict is the item
                    all_results.append(data)

            page_count += 1

            # Handle pagination
            if "next" in response.links:
                url = response.links["next"]["url"]
            else:
                url = None

            remaining_rate = response.headers.get("X-RateLimit-Remaining", "N/A")
            reset_time = response.headers.get("X-RateLimit-Reset", "N/A")

            logging.info(
                f"Fetched page {page_count} ({len(data) if isinstance(data, list) else len(items) if 'items' in locals() else 1} items). "
                f"Rate limit: {remaining_rate} remaining (resets at {reset_time})"
            )

            # Monitor memory usage
            if page_count % 10 == 0:
                memory_mb = monitor_memory()
                if metrics and memory_mb > 0:
                    metrics.memory_peak_mb = max(metrics.memory_peak_mb, memory_mb)

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else None
            error_msg = e.response.text if e.response else str(e)

            logging.error(f"HTTP Error {status_code or 'unknown'} fetching {url}: {error_msg[:200]}")

            # Don't retry on client errors (4xx) except rate limiting
            if status_code == 403:
                # Check if it's a rate limit or permission issue
                if "rate limit" in error_msg.lower():
                    retry_after = e.response.headers.get("Retry-After")
                    if retry_after:
                        wait_time = int(retry_after)
                        logging.warning(
                            f"Rate limited. Waiting {wait_time}s before retry..."
                        )
                        time.sleep(wait_time)
                        continue  # Try again
                else:
                    # Permission error - provide helpful message
                    logging.error(
                        f"Permission denied (403) for {endpoint_url}. "
                        f"Ensure GitHub App has 'Secret scanning alerts: Read' permission "
                        f"and is installed in the organization."
                    )
                    break
            
            if status_code == 429:
                # Rate limited
                retry_after = e.response.headers.get("Retry-After")
                if retry_after:
                    wait_time = int(retry_after)
                    logging.warning(
                        f"Rate limited. Waiting {wait_time}s before retry..."
                    )
                    time.sleep(wait_time)
                    continue  # Try again

            if status_code and 400 <= status_code < 500:
                logging.error(f"Client error {status_code} - stopping pagination for {endpoint_url}")
                break

            # Let the retry decorator handle 5xx errors
            raise

        except requests.exceptions.Timeout:
            logging.error(f"Timeout fetching {url} after {TIMEOUT}s")
            raise

        except requests.exceptions.RequestException as e:
            logging.error(f"Request failed for {url}: {type(e).__name__}: {e}")
            raise

    logging.info(
        f"Completed fetching {len(all_results)} items from {endpoint_url} "
        f"across {page_count} pages"
    )
    return all_results


def export_to_excel(
    summary_data: List[Dict],
    secret_scanning_data: List[Dict],
    output_filename: str = None,
) -> bool:
    """
    Export secret scanning data to Excel file with error handling.

    Args:
        summary_data: Summary statistics
        secret_scanning_data: Secret scanning alerts
        output_filename: Output filename

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        with pd.ExcelWriter(output_filename, engine="openpyxl") as writer:
            # Summary sheet
            if summary_data:
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name="Summary", index=False)
                logging.info("Added summary data to Excel")
            else:
                logging.warning("No summary data to export")

            # Secret Scanning sheet
            if secret_scanning_data:
                secret_df = pd.DataFrame(secret_scanning_data)
                secret_df.to_excel(writer, sheet_name="Secret_Scanning", index=False)
                logging.info(
                    f"Added {len(secret_scanning_data)} secret scanning alerts to Excel"
                )
            else:
                logging.info("No secret scanning alerts found to export")

        logging.info(f"Successfully saved secret scanning alerts to {output_filename}")
        return True

    except PermissionError:
        logging.error(
            f"Permission denied writing to {output_filename}. "
            "File may be open in another application."
        )
        return False
    except Exception as e:
        logging.error(f"Error creating Excel file: {type(e).__name__}: {e}")
        return False


def create_org_access_issues_csv(timestamp: str) -> str:
    """
    Create the org access issues CSV file with headers.

    Args:
        timestamp: Timestamp string for filename

    Returns:
        str: Path to the created CSV file
    """
    try:
        issues_file = os.path.join(output_dir, f"org_access_issues_{timestamp}.csv")
        # Create file with headers
        with open(issues_file, "w", newline="", encoding="utf-8") as f:
            f.write("OrgName,Comment\n")
        logging.info(f"Created org access issues CSV: {issues_file}")
        return issues_file
    except Exception as e:
        logging.error(f"Error creating org access issues CSV: {e}")
        return None


def append_org_access_issue(csv_file: str, org_name: str, comment: str) -> bool:
    """
    Append an organization access issue to the CSV file in real-time.

    Args:
        csv_file: Path to the CSV file
        org_name: Organization name
        comment: Error/issue comment

    Returns:
        bool: True if successfully appended
    """
    try:
        if csv_file and os.path.exists(csv_file):
            with open(csv_file, "a", newline="", encoding="utf-8") as f:
                # Escape commas in the comment by wrapping in quotes if needed
                if "," in comment or '"' in comment:
                    comment = f'"{comment.replace(chr(34), chr(34)+chr(34))}"'
                f.write(f"{org_name},{comment}\n")
            return True
        return False
    except Exception as e:
        logging.error(f"Error appending org access issue to CSV: {e}")
        return False


def export_org_access_issues(
    org_access_issues: List[Dict],
    timestamp: str = None,
) -> bool:
    """
    DEPRECATED: Organization access issues are now written in real-time.
    Export organization access issues to CSV file.

    Args:
        org_access_issues: List of organizations with access issues
        timestamp: Timestamp string for filename

    Returns:
        bool: True if file was successfully created
    """
    try:
        if org_access_issues:
            issues_df = pd.DataFrame(org_access_issues)
            issues_file = os.path.join(output_dir, f"org_access_issues_{timestamp}.csv")
            issues_df.to_csv(issues_file, index=False)
            logging.info(
                f"Saved {len(org_access_issues)} organization access issues to CSV"
            )
            return True
        else:
            logging.info("No organization access issues to report")
            return True
    except Exception as e:
        logging.error(f"Error exporting organization access issues: {e}")
        return False


def export_to_csv(
    secret_scanning_data: List[Dict],
    timestamp: str = None,
) -> bool:
    """
    Export secret scanning data to CSV files as fallback.

    Args:
        secret_scanning_data: Secret scanning alerts
        timestamp: Timestamp string for filenames

    Returns:
        bool: True if any file was successfully created (or no data to export)
    """
    try:
        if secret_scanning_data:
            secret_df = pd.DataFrame(secret_scanning_data)
            secret_df.to_csv(
                os.path.join(output_dir, f"secret_scanning_{timestamp}.csv"),
                index=False,
            )
            logging.info(
                f"Saved {len(secret_scanning_data)} secret scanning alerts as CSV"
            )
            return True
        else:
            logging.warning(
                "No secret scanning alerts to export - skipping CSV creation"
            )
            return True  # Not a failure, just no data
    except Exception as e:
        logging.error(f"Error saving secret scanning CSV: {e}")
        return False


def process_single_organization(
    org_name: str,
    org_index: int,
    total_orgs: int,
    github_app_auth: GitHubAppAuth,
    params: Dict,
    base_api_url: str,
    org_issues_csv: str,
    metrics: PerformanceMetrics,
) -> Tuple[List[Dict], bool]:
    """
    Process alerts for a single organization.

    Returns:
        tuple: (list of alerts, success flag)
    """
    try:
        logging.info(f"[{org_index}/{total_orgs}] Processing organization: {org_name}")

        # Authenticate for this organization
        if not github_app_auth.authenticate_for_organization(org_name):
            error_msg = "No GitHub App installation found"
            logging.warning(
                f"Failed to authenticate for organization: {org_name}. Skipping."
            )
            append_org_access_issue(org_issues_csv, org_name, error_msg)
            return [], False

        # Get authenticated session
        session = github_app_auth.get_authenticated_session()

        # Create session with retry configuration
        if not hasattr(session, "_retry_configured"):
            retry_strategy = Retry(
                total=MAX_RETRIES,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "OPTIONS"],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            session._retry_configured = True

        # Fetch secret scanning alerts for this organization
        org_endpoint = f"{base_api_url}/orgs/{org_name}/secret-scanning/alerts"

        try:
            org_alerts = fetch_all_pages(org_endpoint, session, params.copy(), metrics)
            logging.info(f"  [OK] Fetched {len(org_alerts)} alerts from {org_name}")

            if metrics:
                metrics.total_alerts += len(org_alerts)

            return org_alerts, True

        except Exception as e:
            error_msg = f"Failed to fetch alerts: {str(e)}"
            logging.error(f"  [FAIL] Failed to fetch alerts from {org_name}: {e}")
            append_org_access_issue(org_issues_csv, org_name, error_msg)
            return [], False

    except Exception as e:
        error_msg = f"Error processing organization: {str(e)}"
        logging.error(f"  [ERROR] Error processing {org_name}: {e}")
        append_org_access_issue(org_issues_csv, org_name, error_msg)
        return [], False


def process_organizations_concurrently(
    organizations: List[str],
    github_app_auth: GitHubAppAuth,
    params: Dict,
    base_api_url: str,
    org_issues_csv: str,
    metrics: PerformanceMetrics,
) -> Tuple[List[Dict], int, int]:
    """
    Process organizations concurrently for better performance.

    Returns:
        tuple: (all_alerts, successful_orgs, failed_orgs)
    """
    all_alerts = []
    successful_orgs = 0
    failed_orgs = 0

    # Use ThreadPoolExecutor for concurrent processing
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_ORGS) as executor:
        # Submit all organization processing tasks
        future_to_org = {
            executor.submit(
                process_single_organization,
                org_name,
                idx,
                len(organizations),
                github_app_auth,
                params,
                base_api_url,
                org_issues_csv,
                metrics,
            ): org_name
            for idx, org_name in enumerate(organizations, 1)
        }

        # Collect results as they complete
        for future in as_completed(future_to_org):
            org_name = future_to_org[future]
            try:
                org_alerts, success = future.result()
                if success:
                    all_alerts.extend(org_alerts)
                    successful_orgs += 1
                    if metrics:
                        metrics.organizations_processed += 1
                else:
                    failed_orgs += 1
                    if metrics:
                        metrics.organizations_failed += 1
            except Exception as e:
                logging.error(f"Exception in processing {org_name}: {e}")
                failed_orgs += 1
                if metrics:
                    metrics.organizations_failed += 1

    return all_alerts, successful_orgs, failed_orgs


def extract_and_enrich_data(
    all_alerts: List[Dict], github_app_auth: GitHubAppAuth, metrics: PerformanceMetrics
) -> List[Dict]:
    """
    Extract and optionally enrich alert data with commit information.
    """
    stage_start = time.time()
    logging.info("Processing secret scanning alert data...")

    # Convert generator to list for processing
    secret_scanning_data = list(extract_secret_scanning_data(all_alerts))

    # Enrich with commit author information (always enabled)
    if secret_scanning_data:
        logging.info("Fetching commit details...")

        # Group alerts by organization for efficient session management
        alerts_by_org = defaultdict(list)
        for idx, alert in enumerate(secret_scanning_data):
            org_name = alert.get("Organization_Name")
            if org_name:
                alerts_by_org[org_name].append((idx, alert))

        # Process each organization's alerts with concurrent processing
        with ThreadPoolExecutor(
            max_workers=min(MAX_CONCURRENT_ORGS, len(alerts_by_org))
        ) as executor:
            futures = []

            for org_name, org_alerts in alerts_by_org.items():
                future = executor.submit(
                    enrich_organization_alerts,
                    org_name,
                    org_alerts,
                    github_app_auth,
                    secret_scanning_data,
                )
                futures.append(future)

            # Wait for all enrichment tasks to complete
            for future in as_completed(futures):
                try:
                    future.result()  # This will raise any exceptions
                except Exception as e:
                    logging.error(f"Error in commit enrichment: {e}")

        logging.info("Commit enrichment completed")

    if metrics:
        metrics.processing_times["data_extraction_and_enrichment"] = (
            time.time() - stage_start
        )

    return secret_scanning_data


def enrich_organization_alerts(
    org_name: str,
    org_alerts: List[Tuple[int, Dict]],
    github_app_auth: GitHubAppAuth,
    secret_scanning_data: List[Dict],
) -> None:
    """
    Enrich alerts for a single organization with commit information and optional repository admin information.
    """
    logging.info(f"Enriching {len(org_alerts)} alerts for {org_name}...")

    try:
        # Authenticate for this organization
        if github_app_auth.authenticate_for_organization(org_name):
            session = github_app_auth.get_authenticated_session()

            # Cache repository admins to avoid repeated API calls for the same repo
            repo_admin_cache = {}

            # Enrich alerts for this org
            for idx, alert in org_alerts:
                try:
                    repo_full_name = f"{alert.get('Organization_Name')}/{alert.get('Repository_Name')}"
                    blob_sha = alert.get("Location_Blob_Sha")

                    # Enrich with commit information
                    if blob_sha and repo_full_name:
                        commit_info = fetch_commit_info(
                            repo_full_name, blob_sha, session
                        )
                        secret_scanning_data[idx]["Commit_Author"] = commit_info.get(
                            "author"
                        )
                        secret_scanning_data[idx]["Commit_Committer"] = commit_info.get(
                            "committer"
                        )
                        secret_scanning_data[idx]["Commit_SHA"] = commit_info.get("sha")

                    # Enrich with repository admin information (always enabled)
                    if repo_full_name:
                        # Check cache first
                        if repo_full_name not in repo_admin_cache:
                            repo_admins = fetch_repository_admins(
                                repo_full_name, session
                            )
                            repo_admin_cache[repo_full_name] = (
                                ", ".join(repo_admins) if repo_admins else ""
                            )

                        secret_scanning_data[idx]["Repo_Admin"] = repo_admin_cache[
                            repo_full_name
                        ]

                except Exception as e:
                    logging.warning(f"Failed to enrich alert {idx}: {e}")
                    # Ensure the column exists even if enrichment fails
                    if "Repo_Admin" not in secret_scanning_data[idx]:
                        secret_scanning_data[idx]["Repo_Admin"] = ""
        else:
            logging.warning(
                f"Could not authenticate for {org_name} - skipping enrichment"
            )
            # Add empty Repo_Admin column for this org's alerts
            for idx, _ in org_alerts:
                secret_scanning_data[idx]["Repo_Admin"] = ""
    except Exception as e:
        logging.error(f"Error enriching alerts for {org_name}: {e}")
        # Add empty Repo_Admin column for this org's alerts
        for idx, _ in org_alerts:
            if "Repo_Admin" not in secret_scanning_data[idx]:
                secret_scanning_data[idx]["Repo_Admin"] = ""


def export_results(
    summary_data: List[Dict],
    secret_scanning_data: List[Dict],
    config: Dict,
    timestamp: str,
    org_issues_csv: str,
    metrics: PerformanceMetrics,
) -> bool:
    """
    Export results in the requested format(s).
    """
    stage_start = time.time()
    base_filename = config["output"]
    export_success = False

    if config["format"] in ["xlsx", "both"]:
        output_filename = os.path.join(output_dir, f"{base_filename}.xlsx")
        logging.info(f"Attempting to export to {output_filename}...")
        excel_success = export_to_excel(
            summary_data, secret_scanning_data, output_filename
        )
        export_success = export_success or excel_success

    if config["format"] in ["csv", "both"]:
        logging.info(f"Exporting to CSV files...")
        csv_success = export_to_csv(secret_scanning_data, timestamp)
        export_success = export_success or csv_success

        # Report organization access issues
        if org_issues_csv and os.path.exists(org_issues_csv):
            with open(org_issues_csv, "r") as f:
                issue_count = sum(1 for line in f) - 1
            if issue_count > 0:
                logging.info(
                    f"Organization access issues logged to: {org_issues_csv} ({issue_count} organizations)"
                )
            else:
                logging.info("No organization access issues encountered")

    if metrics:
        metrics.processing_times["export_results"] = time.time() - stage_start

    return export_success


# --- Main Execution ---


def main():
    """
    Main function to orchestrate fetching secret scanning alerts per organization.
    Uses GitHub App authentication with concurrent processing and performance monitoring.
    Configured via environment variables (.env file or GitHub Actions).
    """
    # Initialize performance tracking
    metrics = PerformanceMetrics()

    # Start memory monitoring
    tracemalloc.start()

    try:
        logging.info("=" * 80)
        logging.info(
            "Starting Secret Scanning Alerts Fetcher (GitHub App Auth) - OPTIMIZED"
        )
        logging.info("=" * 80)

        # Validate configuration first
        if not validate_configuration():
            logging.error("Configuration validation failed. Exiting.")
            return 1

        # Load configuration from environment variables
        config = load_alert_config()

        logging.info("Alert type: Secret Scanning")
        logging.info(f"Alert state filter: {config['state']}")
        logging.info(f"Output format: {config['format']}")
        logging.info(f"Max concurrent organizations: {MAX_CONCURRENT_ORGS}")
        logging.info(f"Memory threshold: {MEMORY_THRESHOLD_MB} MB")
        logging.info("=" * 80)

        enterprise_slug, github_app_auth = load_config()

        # Fetch organizations in the enterprise
        stage_start = time.time()
        logging.info("Fetching organizations in the enterprise...")
        organizations = fetch_organizations(enterprise_slug, github_app_auth)

        if not organizations:
            logging.error("No organizations found. Exiting.")
            return 1

        metrics.processing_times["fetch_organizations"] = time.time() - stage_start

        logging.info(f"Found {len(organizations)} organizations in enterprise")

        # Apply test mode limit if enabled
        if config["test_mode"]:
            original_count = len(organizations)
            organizations = organizations[: config["test_org_limit"]]
            logging.warning(
                f"TEST MODE ENABLED: Processing only {len(organizations)} of {original_count} organizations"
            )

        logging.info(
            f"Processing {len(organizations)} organizations with {MAX_CONCURRENT_ORGS} concurrent workers"
        )
        logging.info("=" * 80)

        base_api_url = "https://api.github.com"

        # Configure secret scanning alert fetching
        requested_state = config["state"] if config["state"] != "all" else None

        # Secret scanning supports: open, resolved
        state_param = requested_state
        if requested_state == "closed":
            state_param = "resolved"  # Map closed to resolved for secret scanning
        elif requested_state in ["dismissed", "fixed"]:
            logging.warning(
                f"Secret scanning doesn't support state '{requested_state}'. "
                f"Valid states are 'open' or 'resolved'. Skipping state filter."
            )
            state_param = None

        params = {"per_page": 100}
        if state_param:
            params["state"] = state_param
            logging.info(f"Secret Scanning: Using state filter '{state_param}'")

        # Generate timestamp for this query execution
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Create org access issues CSV file upfront
        org_issues_csv = create_org_access_issues_csv(timestamp)

        # Process organizations concurrently
        stage_start = time.time()
        all_secret_scanning_alerts, successful_orgs, failed_orgs = (
            process_organizations_concurrently(
                organizations,
                github_app_auth,
                params,
                base_api_url,
                org_issues_csv,
                metrics,
            )
        )
        metrics.processing_times["fetch_alerts"] = time.time() - stage_start

        logging.info("=" * 80)
        logging.info(f"Organization Processing Summary:")
        logging.info(f"  - Total Organizations: {len(organizations)}")
        logging.info(f"  - Successful: {successful_orgs}")
        logging.info(f"  - Failed: {failed_orgs}")
        logging.info(f"  - Total Alerts Fetched: {len(all_secret_scanning_alerts)}")
        logging.info("=" * 80)

        # Extract and enrich data
        secret_scanning_data = extract_and_enrich_data(
            all_secret_scanning_alerts, github_app_auth, metrics
        )

        # Create summary data with query metadata
        summary_data = create_summary_data(
            secret_scanning_data,
            alert_state=config["state"],
            timestamp=timestamp,
        )

        # Log statistics
        logging.info("=" * 80)
        logging.info("Data Processing Complete:")
        logging.info(f"  - Secret Scanning: {len(secret_scanning_data)} alerts")
        logging.info("=" * 80)

        # Export results
        export_success = export_results(
            summary_data,
            secret_scanning_data,
            config,
            timestamp,
            org_issues_csv,
            metrics,
        )

        # Get final memory statistics
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        metrics.memory_peak_mb = max(metrics.memory_peak_mb, peak / 1024 / 1024)

        # Log final performance metrics
        metrics.log_summary()

        if export_success:
            logging.info(f"Script completed successfully.")
            logging.info(f"Peak memory usage: {metrics.memory_peak_mb:.1f} MB")
            logging.info(f"Log file: {log_filename}")
            logging.info("=" * 80)
            return 0
        else:
            logging.error("Export failed")
            return 1

    except KeyboardInterrupt:
        logging.warning("Script interrupted by user")
        if "metrics" in locals():
            metrics.log_summary()
        return 130
    except Exception as e:
        logging.error(f"FATAL ERROR: {type(e).__name__}: {e}", exc_info=True)
        if "metrics" in locals():
            metrics.log_summary()
        return 1
    finally:
        # Ensure tracemalloc is stopped
        if tracemalloc.is_tracing():
            tracemalloc.stop()


if __name__ == "__main__":
    exit(main())
