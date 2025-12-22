import os
import json
import logging
import itertools
import time
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
from functools import wraps

import requests
import pandas as pd
from dotenv import load_dotenv

# --- Configuration ---
# Set up enhanced logging with both console and file output
# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Ensure output directories exist relative to script location
output_dir = os.path.join(script_dir, "output")
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

# Load environment variables from .env file for local execution
load_dotenv()

# Constants
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
TIMEOUT = 30  # seconds

# Feature flags for enrichment
ENABLE_REPO_ADMIN_ENRICHMENT = (
    os.getenv("ENABLE_REPO_ADMIN_ENRICHMENT", "false").lower() == "true"
)

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


def is_default_secret_type(secret_type: str) -> str:
    """
    Determine if a secret type is a default GitHub pattern or a generic/custom pattern.

    Default patterns are GitHub's built-in secret detection patterns.
    Generic patterns are user-defined custom patterns.

    Args:
        secret_type: The secret_type value from the API

    Returns:
        "default" or "generic"
    """
    # List of known GitHub default secret type prefixes/patterns
    # These are the standard patterns GitHub provides out-of-the-box
    default_patterns = [
        # Common service tokens
        "github_",
        "aws_",
        "azure_",
        "google_",
        "slack_",
        "stripe_",
        "twilio_",
        "mailchimp_",
        "sendgrid_",
        "heroku_",
        "digitalocean_",
        "dropbox_",
        "paypal_",
        "square_",
        "shopify_",
        "alibaba_",
        "npm_",
        # Specific patterns
        "adafruit_",
        "adobe_",
        "age_",
        "airtable_",
        "algolia_",
        "ansible_",
        "asana_",
        "atlassian_",
        "authress_",
        "beamer_",
        "bitbucket_",
        "bittrex_",
        "clojars_",
        "codecov_",
        "coinbase_",
        "confluence_",
        "contentful_",
        "databricks_",
        "datadog_",
        "defined_",
        "discord_",
        "doppler_",
        "droneci_",
        "duffel_",
        "dynatrace_",
        "easypost_",
        "etsy_",
        "facebook_",
        "fastly_",
        "finicity_",
        "flutterwave_",
        "frameio_",
        "freshbooks_",
        "gcp_",
        "gitlab_",
        "gitter_",
        "grafana_",
        "hashicorp_",
        "hubspot_",
        "intercom_",
        "ionic_",
        "jfrog_",
        "linear_",
        "lob_",
        "mailgun_",
        "mapbox_",
        "messagebird_",
        "microsoft_",
        "netlify_",
        "new_relic_",
        "notion_",
        "nytimes_",
        "okta_",
        "openai_",
        "planetscale_",
        "postman_",
        "pulumi_",
        "readme_",
        "rubygems_",
        "samsara_",
        "segment_",
        "sendinblue_",
        "sentry_",
        "shippo_",
        "shopify_",
        "sidekiq_",
        "supabase_",
        "telegram_",
        "travis_",
        "twitch_",
        "typeform_",
        "vault_",
        "vercel_",
        "yandex_",
        "zendesk_",
        # Generic credential patterns
        "private_key",
        "rsa_private",
        "ssh_private",
        "pgp_private",
        "pkcs8_private",
    ]

    if not secret_type:
        return "unknown"

    secret_type_lower = secret_type.lower()

    # Check if it matches any default pattern
    for pattern in default_patterns:
        if secret_type_lower.startswith(pattern) or pattern in secret_type_lower:
            return "default"

    # If it doesn't match any known default pattern, it's likely generic/custom
    return "generic"


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


def extract_secret_scanning_data(alerts: List[Dict]) -> List[Dict]:
    """
    Extract relevant fields from secret scanning alerts.
    """
    field_mapping = {
        "Alert_Number": ("number",),
        "Organization_Name": lambda alert: (
            safe_get(alert, "repository", "full_name").split("/")[0]
            if safe_get(alert, "repository", "full_name")
            else None
        ),
        "Project_Code": lambda alert: parse_organization_name(
            safe_get(alert, "repository", "full_name").split("/")[0]
            if safe_get(alert, "repository", "full_name")
            else None
        )[0],
        "Cost_Center": lambda alert: parse_organization_name(
            safe_get(alert, "repository", "full_name").split("/")[0]
            if safe_get(alert, "repository", "full_name")
            else None
        )[1],
        "Repository_Name": lambda alert: (
            safe_get(alert, "repository", "full_name").split("/")[1]
            if safe_get(alert, "repository", "full_name")
            and "/" in safe_get(alert, "repository", "full_name")
            else safe_get(alert, "repository", "full_name")
        ),
        "Secret_Type": ("secret_type_display_name",),
        "Secret_Type_ID": ("secret_type",),
        "Pattern_Category": lambda alert: is_default_secret_type(
            safe_get(alert, "secret_type")
        ),
        "State": ("state",),
        "Created_At": ("created_at",),
        "Updated_At": ("updated_at",),
        "URL": ("html_url",),
        "Validity": ("validity",),
        "Resolution": ("resolution",),
        "Resolved_By": lambda alert: (
            safe_get(alert, "resolved_by", "login")
            if safe_get(alert, "resolved_by")
            else None
        ),
        "Resolved_At": ("resolved_at",),
        "Publicly_Leaked": ("publicly_leaked",),
        "Push_Protection_Bypassed": ("push_protection_bypassed",),
        "Location_Path": ("first_location_detected", "path"),
        # New fields for commit information
        "Location_Start_Line": ("first_location_detected", "start_line"),
        "Location_End_Line": ("first_location_detected", "end_line"),
        "Location_Start_Column": ("first_location_detected", "start_column"),
        "Location_End_Column": ("first_location_detected", "end_column"),
        "Location_Blob_Sha": ("first_location_detected", "blob_sha"),
        "Location_Blob_URL": ("first_location_detected", "blob_url"),
        # Commit author information
        "Commit_Author": lambda alert: None,
        "Commit_Committer": lambda alert: None,
        "Commit_SHA": lambda alert: None,
        # Repository admin information (populated during enrichment if enabled)
        "Repo_Admin": lambda alert: "",
    }
    return extract_alert_data(alerts, field_mapping, "Secret Scanning")


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
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        summary.append(
            {
                "Alert_Type": "Query Information",
                "Query_Timestamp": timestamp,
                "Alert_State_Filter": alert_state,
                "Secret_Scanning_Queried": "Yes",
            }
        )

        summary.append(
            {
                "Alert_Type": "Secret Scanning",
                "Total_Count": len(secret_scanning_data),
                "Default_Patterns": count_by_field(
                    secret_scanning_data, "Pattern_Category", "default"
                ),
                "Generic_Patterns": count_by_field(
                    secret_scanning_data, "Pattern_Category", "generic"
                ),
                "Unknown_Category": count_by_field(
                    secret_scanning_data, "Pattern_Category", "unknown"
                ),
                "Active_Secrets": count_by_field(
                    secret_scanning_data, "Validity", "active"
                ),
                "Inactive_Secrets": count_by_field(
                    secret_scanning_data, "Validity", "inactive"
                ),
                "Unknown_Validity": count_by_field(
                    secret_scanning_data, "Validity", "unknown"
                ),
                "Publicly_Leaked": count_by_field(
                    secret_scanning_data, "Publicly_Leaked", True
                ),
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
        ENABLE_COMMIT_ENRICHMENT: Enable commit information enrichment to get committer GitHub handles (default: true)
                                 Set to 'false' to disable and save API rate limits
        TEST_MODE: Enable testing mode with limited results (default: false)
        TEST_LIMIT: Number of alerts to fetch in testing mode (default: 20)
        SECRET_TYPES: Comma-separated list of secret types to include (default: all)
                     By default, GitHub API returns only default patterns.
                     To include generic/custom patterns, specify their names explicitly.
                     Example: 'my_custom_pattern,another_pattern'
                     Note: Results will include a 'Pattern_Category' column (default/generic)

    Returns:
        dict: Configuration dictionary
    """

    config = {
        "state": os.getenv("ALERT_STATE", "all").lower(),
        "output": os.getenv("OUTPUT_FILENAME", "secret_scanning_report"),
        "format": os.getenv("OUTPUT_FORMAT", "csv").lower(),
        "enable_commit_enrichment": os.getenv(
            "ENABLE_COMMIT_ENRICHMENT", "true"
        ).lower()
        == "true",
        "test_mode": os.getenv("TEST_MODE", "false").lower() == "true",
        "test_limit": int(os.getenv("TEST_LIMIT", "20")),
        "secret_types": os.getenv("SECRET_TYPES", "all").strip(),
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
    logging.info(f"  - Commit Enrichment: {config['enable_commit_enrichment']}")
    if config["test_mode"]:
        logging.info(f"  - Test Mode: ENABLED (limit: {config['test_limit']} alerts)")
    else:
        logging.info(f"  - Test Mode: disabled")
    logging.info(f"  - Secret Types: {config['secret_types']}")

    # Log enrichment settings
    commit_enrichment_enabled = (
        os.getenv("ENABLE_COMMIT_ENRICHMENT", "false").lower() == "true"
    )
    logging.info(f"  - Commit Enrichment: {commit_enrichment_enabled}")
    logging.info(f"  - Repo Admin Enrichment: {ENABLE_REPO_ADMIN_ENRICHMENT}")

    return config


def load_config() -> Tuple[str, List[str]]:
    """
    Loads configuration from environment variables with validation.
    Exits if required configuration is missing or invalid.

    Returns:
        tuple: (enterprise_slug, list of PATs)
    """
    enterprise_slug = os.getenv("GH_ENTERPRISE_SLUG")
    pats_str = os.getenv("GH_PATS")

    if not enterprise_slug:
        logging.error("FATAL: GH_ENTERPRISE_SLUG environment variable not set.")
        exit(1)

    if not enterprise_slug.replace("-", "").replace("_", "").isalnum():
        logging.error(f"FATAL: Invalid GH_ENTERPRISE_SLUG format: {enterprise_slug}")
        exit(1)

    if not pats_str:
        logging.error("FATAL: GH_PATS environment variable not set.")
        exit(1)

    pats = [token.strip() for token in pats_str.split(",") if token.strip()]

    if not pats:
        logging.error("FATAL: No valid PATs found in GH_PATS.")
        exit(1)

    # Validate PAT formats
    valid_pats = [pat for pat in pats if validate_pat(pat)]
    if not valid_pats:
        logging.error("FATAL: No valid PATs found after validation.")
        exit(1)

    if len(valid_pats) < len(pats):
        logging.warning(
            f"Removed {len(pats) - len(valid_pats)} invalid PATs. "
            f"Using {len(valid_pats)} valid PATs."
        )

    logging.info(f"Loaded configuration for enterprise: '{enterprise_slug}'")
    logging.info(f"Found {len(valid_pats)} valid PATs to use in round-robin.")

    return enterprise_slug, valid_pats


@retry_on_failure()
def fetch_commit_info(
    repo_full_name: str, commit_sha: str, pat_cycler: itertools.cycle
) -> Dict:
    """
    Fetch commit information for a specific commit SHA.
    This function uses the commit_sha directly from the secret scanning API response.

    Args:
        repo_full_name: Full repository name (owner/repo)
        commit_sha: The commit SHA from first_location_detected.commit_sha
        pat_cycler: PAT cycler for authentication

    Returns:
        Dict with commit author, committer information and GitHub handles
    """
    if not commit_sha or not repo_full_name:
        return {
            "author": None,
            "committer": None,
            "committer_login": None,
            "author_login": None,
            "sha": None,
            "message": None,
            "author_email": None,
            "committer_email": None,
        }

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    token = next(pat_cycler)
    headers["Authorization"] = f"Bearer {token}"

    try:
        # Get detailed commit info using the commit SHA directly
        commit_detail_url = (
            f"https://api.github.com/repos/{repo_full_name}/commits/{commit_sha}"
        )
        commit_detail_response = requests.get(
            commit_detail_url, headers=headers, timeout=TIMEOUT
        )
        commit_detail_response.raise_for_status()

        commit_detail = commit_detail_response.json()

        return {
            "author": safe_get(commit_detail, "commit", "author", "name"),
            "committer": safe_get(commit_detail, "commit", "committer", "name"),
            "committer_login": safe_get(commit_detail, "committer", "login"),
            "author_login": safe_get(commit_detail, "author", "login"),
            "sha": commit_sha,
            "message": (
                safe_get(commit_detail, "commit", "message", "").split("\n")[0]
                if safe_get(commit_detail, "commit", "message")
                else None
            ),
            "author_email": safe_get(commit_detail, "commit", "author", "email"),
            "committer_email": safe_get(commit_detail, "commit", "committer", "email"),
        }

    except Exception as e:
        logging.warning(
            f"Failed to fetch commit info for {repo_full_name} (commit: {commit_sha}): {e}"
        )

    return {
        "author": None,
        "committer": None,
        "committer_login": None,
        "author_login": None,
        "sha": None,
        "message": None,
        "author_email": None,
        "committer_email": None,
    }


@retry_on_failure()
def fetch_user_email(
    username: str, pat_cycler: itertools.cycle, repo_full_name: str = None
) -> Optional[str]:
    """
    Fetch email address for a specific user.
    First tries the public profile, then falls back to commit history if a repo is provided.

    Args:
        username: GitHub username
        pat_cycler: PAT cycler for authentication
        repo_full_name: Optional repository name to search commit history

    Returns:
        User's email address or None if not available
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    token = next(pat_cycler)
    headers["Authorization"] = f"Bearer {token}"

    try:
        # First, try to get email from public profile
        url = f"https://api.github.com/users/{username}"
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()

        user_data = response.json()
        email = user_data.get("email")

        # If no email from profile and we have a repo, try to get it from commit history
        if not email and repo_full_name:
            try:
                commits_url = f"https://api.github.com/repos/{repo_full_name}/commits"
                params = {"author": username, "per_page": 10}
                commits_response = requests.get(
                    commits_url, headers=headers, params=params, timeout=TIMEOUT
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
    repo_full_name: str, pat_cycler: itertools.cycle
) -> List[str]:
    """
    Fetch repository administrators (users with admin permissions).

    Args:
        repo_full_name: Full repository name (owner/repo)
        pat_cycler: PAT cycler for authentication

    Returns:
        List of usernames with admin permissions
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    token = next(pat_cycler)
    headers["Authorization"] = f"Bearer {token}"

    try:
        # Fetch collaborators with admin permission
        url = f"https://api.github.com/repos/{repo_full_name}/collaborators"
        params = {"permission": "admin", "per_page": 100}

        response = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
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
    secret_data: List[Dict], pat_cycler: itertools.cycle
) -> List[Dict]:
    """
    Enrich secret scanning data with commit author information and optional repository admin information.
    This function is separate and not called by default to save API rate limits.
    """
    logging.info("Enriching secret scanning data with commit information...")

    # Cache repository admins to avoid repeated API calls for the same repo
    repo_admin_cache = {}

    enriched_data = []

    for idx, alert in enumerate(secret_data):
        try:
            repo_full_name = (
                f"{alert.get('Organization_Name')}/{alert.get('Repository_Name')}"
            )
            blob_sha = alert.get("Location_Blob_Sha")

            # Fetch commit information
            if (
                repo_full_name
                and alert.get("Organization_Name")
                and alert.get("Repository_Name")
            ):
                commit_sha = alert.get("Location_Commit_Sha")
                if commit_sha:
                    commit_info = fetch_commit_info(
                        repo_full_name, commit_sha, pat_cycler
                    )
                    alert["Commit_Author"] = commit_info.get("author")
                    alert["Commit_Committer"] = commit_info.get("committer")
                    alert["Commit_SHA"] = commit_info.get("sha")
                    alert["Committer_Id"] = commit_info.get("committer_login")
                    alert["Author_Id"] = commit_info.get("author_login")
                    alert["Commit_Message"] = commit_info.get("message")
                    alert["Author_Email"] = commit_info.get("author_email")
                    alert["Committer_Email"] = commit_info.get("committer_email")
                else:
                    logging.warning(
                        f"No commit_sha found for alert {alert.get('Alert_Number')}"
                    )
                    alert["Commit_Author"] = None
                    alert["Commit_Committer"] = None
                    alert["Commit_SHA"] = None
                    alert["Committer_Id"] = None
                    alert["Author_Id"] = None
                    alert["Commit_Message"] = None
                    alert["Author_Email"] = None
                    alert["Committer_Email"] = None
            else:
                alert["Commit_Author"] = None
                alert["Commit_Committer"] = None
                alert["Commit_SHA"] = None
                alert["Committer_Id"] = None
                alert["Author_Id"] = None
                alert["Commit_Message"] = None
                alert["Author_Email"] = None
                alert["Committer_Email"] = None

            # Enrich with repository admin information if enabled
            if ENABLE_REPO_ADMIN_ENRICHMENT and repo_full_name:
                # Check cache first
                if repo_full_name not in repo_admin_cache:
                    repo_admins = fetch_repository_admins(repo_full_name, pat_cycler)
                    repo_admin_cache[repo_full_name] = (
                        ", ".join(repo_admins) if repo_admins else ""
                    )

                alert["Repo_Admin"] = repo_admin_cache[repo_full_name]
            else:
                # Ensure column exists even if feature is disabled
                alert["Repo_Admin"] = ""

            enriched_data.append(alert)

            # Log progress every 50 items
            if (idx + 1) % 50 == 0:
                logging.info(f"Processed {idx + 1}/{len(secret_data)} alerts...")

        except Exception as e:
            logging.error(f"Error enriching alert {idx} with commit info: {e}")
            # Ensure Repo_Admin column exists even if enrichment fails
            if "Repo_Admin" not in alert:
                alert["Repo_Admin"] = ""
            enriched_data.append(alert)  # Add original alert even if enrichment fails

    logging.info(f"Completed commit enrichment for {len(enriched_data)} alerts")
    if ENABLE_REPO_ADMIN_ENRICHMENT:
        logging.info(
            f"Repository admin information added for {len(repo_admin_cache)} unique repositories"
        )
    return enriched_data


@retry_on_failure()
def fetch_all_pages(
    endpoint_url: str,
    headers: Dict,
    params: Optional[Dict],
    pat_cycler: itertools.cycle,
    max_results: Optional[int] = None,
) -> List[Dict]:
    """
    Fetches all pages of results from a GitHub API endpoint with retry logic.

    Args:
        endpoint_url (str): The initial URL for the API endpoint.
        headers (dict): Base headers for the request.
        params (dict): Query parameters for the request.
        pat_cycler (itertools.cycle): A cycler for PATs.
        max_results (int, optional): Maximum number of results to return. If None, fetches all.

    Returns:
        list: A list containing all items from all pages (limited by max_results if specified).
    """
    all_results = []
    url = endpoint_url
    page_count = 0

    while url:
        token = next(pat_cycler)
        headers["Authorization"] = f"Bearer {token}"

        try:
            response = requests.get(
                url, headers=headers, params=params, timeout=TIMEOUT
            )
            # Clear params after the first request as they are included in the 'next' URL
            params = None

            response.raise_for_status()  # Raises an exception for 4XX or 5XX status codes

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

            # Check if we've reached the maximum results limit
            if max_results and len(all_results) >= max_results:
                logging.info(
                    f"Reached maximum results limit of {max_results}. Stopping fetch."
                )
                all_results = all_results[:max_results]  # Trim to exact limit
                break

            # Handle pagination
            if "next" in response.links:
                url = response.links["next"]["url"]
            else:
                url = None

            remaining_rate = response.headers.get("X-RateLimit-Remaining", "N/A")
            reset_time = response.headers.get("X-RateLimit-Reset", "N/A")

            logging.info(
                f"Fetched page {page_count} from {endpoint_url}. "
                f"Rate limit: {remaining_rate} remaining (resets at {reset_time})"
            )

            # Warn if rate limit is getting low
            try:
                if remaining_rate != "N/A" and int(remaining_rate) < 100:
                    logging.warning(
                        f"Rate limit running low: {remaining_rate} requests remaining"
                    )
            except (ValueError, TypeError):
                pass

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else "unknown"
            error_msg = e.response.text if e.response else str(e)

            logging.error(f"HTTP Error {status_code} fetching {url}: {error_msg[:200]}")

            # Don't retry on client errors (4xx) except rate limiting
            if status_code == 403 or status_code == 429:
                # Rate limited - check if we should wait
                retry_after = e.response.headers.get("Retry-After")
                if retry_after:
                    wait_time = int(retry_after)
                    logging.warning(
                        f"Rate limited. Waiting {wait_time}s before retry..."
                    )
                    time.sleep(wait_time)
                    continue  # Try again

            if 400 <= status_code < 500:
                logging.error(f"Client error - stopping pagination for {endpoint_url}")
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
        bool: True if any file was successfully created
    """
    success_count = 0

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
            success_count += 1
    except Exception as e:
        logging.error(f"Error saving secret scanning CSV: {e}")

    if success_count > 0:
        logging.info(f"Successfully saved {success_count} CSV files")
        return True
    else:
        logging.error("Failed to save any CSV files")
        return False


# --- Main Execution ---


def main():
    """
    Main function to orchestrate fetching secret scanning alerts.
    Configured via environment variables (.env file or GitHub Actions).
    """
    start_time = time.time()
    logging.info("=" * 80)
    logging.info("Starting Secret Scanning Alerts Fetcher")
    logging.info("=" * 80)

    try:
        # Load configuration from environment variables
        config = load_alert_config()

        logging.info("Alert type: Secret Scanning")
        logging.info(f"Alert state filter: {config['state']}")
        logging.info(f"Output format: {config['format']}")
        logging.info("=" * 80)

        enterprise_slug, pats = load_config()
        pat_cycler = itertools.cycle(pats)

        logging.info("Fetching secret scanning alerts using REST API...")

        base_api_url = "https://api.github.com"

        # Common headers for all requests
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

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

        # Add secret_type parameter if specified
        # By default, API returns only default patterns
        # To include generic/custom patterns, you must specify them explicitly
        if config["secret_types"] and config["secret_types"].lower() != "all":
            params["secret_type"] = config["secret_types"]
            logging.info(
                f"Secret Scanning: Using secret_type filter '{config['secret_types']}'"
            )
            logging.info(
                "NOTE: This will return specified secret types. To get ALL types including custom patterns, you may need to list them explicitly."
            )
        else:
            logging.warning("=" * 80)
            logging.warning(
                "SECRET_TYPES not configured - API will return DEFAULT patterns ONLY"
            )
            logging.warning(
                "If you have GENERIC/CUSTOM patterns, they will NOT be returned!"
            )
            logging.warning("")
            logging.warning("To include generic/custom patterns:")
            logging.warning(
                "1. Find your custom pattern names from Enterprise/Org settings"
            )
            logging.warning(
                "2. Set SECRET_TYPES in .env file (e.g., SECRET_TYPES=password,api_key)"
            )
            logging.warning("3. Or run: python discover_custom_patterns.py")
            logging.warning("=" * 80)

        # Fetch secret scanning alerts
        try:
            max_results = config["test_limit"] if config["test_mode"] else None
            if config["test_mode"]:
                logging.info(
                    f"TEST MODE: Fetching only first {config['test_limit']} alerts"
                )

            secret_scanning_alerts = fetch_all_pages(
                f"{base_api_url}/enterprises/{enterprise_slug}/secret-scanning/alerts",
                headers,
                params,
                pat_cycler,
                max_results,
            )
            logging.info(
                f"SUCCESS: Fetched {len(secret_scanning_alerts)} secret scanning alerts."
            )

            # Provide helpful message if no results
            if len(secret_scanning_alerts) == 0:
                logging.warning("")
                logging.warning("No alerts returned from API!")
                logging.warning("")
                if (
                    not config.get("secret_types")
                    or config["secret_types"].lower() == "all"
                ):
                    logging.warning("Possible reasons:")
                    logging.warning(
                        "1. No default pattern alerts exist in your enterprise"
                    )
                    logging.warning(
                        "2. You only have GENERIC/CUSTOM pattern alerts (not returned by default)"
                    )
                    logging.warning("3. All alerts are in a state you filtered out")
                    logging.warning("")
                    logging.warning(
                        "If you see alerts in the GitHub UI with 'results:generic' filter:"
                    )
                    logging.warning(
                        "  → You MUST specify custom pattern names in SECRET_TYPES"
                    )
                    logging.warning(
                        "  → Check Enterprise Settings > Security > Custom patterns for names"
                    )
                    logging.warning(
                        "  → Example: SECRET_TYPES=password,internal_api_key"
                    )
                logging.warning("")
        except Exception as exc:
            logging.error(
                f"ERROR: Failed to fetch secret scanning alerts: {type(exc).__name__}: {exc}"
            )
            secret_scanning_alerts = []

        # Extract and process secret scanning data
        logging.info("Processing secret scanning alert data...")
        secret_scanning_data = extract_secret_scanning_data(secret_scanning_alerts)

        # Enrich with commit author information if enabled
        if secret_scanning_data and os.getenv(
            "ENABLE_COMMIT_ENRICHMENT", "false"
        ).lower() in ["true", "1", "yes"]:
            logging.info("Commit enrichment is enabled - fetching commit details...")
            secret_scanning_data = enrich_secret_data_with_commit_details(
                secret_scanning_data, pat_cycler
            )
            logging.info("Commit enrichment completed")
        elif secret_scanning_data:
            logging.info(
                "Commit enrichment is disabled. Set ENABLE_COMMIT_ENRICHMENT=true to enable."
            )

            # Enrich with commit information to get committer GitHub handles (if enabled)
            if config["enable_commit_enrichment"]:
                logging.info(
                    "Enriching data with commit information to get committer GitHub handles..."
                )
                secret_scanning_data = enrich_secret_data_with_commit_details(
                    secret_scanning_data, pat_cycler
                )
            else:
                logging.info(
                    "Commit enrichment disabled. Skipping committer GitHub handle retrieval."
                )

        # Generate timestamp for this query execution
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Create summary data with query metadata
        summary_data = create_summary_data(
            secret_scanning_data,
            alert_state=config["state"],
            timestamp=timestamp,
        )

        # Log statistics with pattern breakdown
        logging.info("=" * 80)
        logging.info("Data Processing Complete:")
        logging.info(f"  - Secret Scanning: {len(secret_scanning_data)} alerts")
        if secret_scanning_data:
            default_count = count_by_field(
                secret_scanning_data, "Pattern_Category", "default"
            )
            generic_count = count_by_field(
                secret_scanning_data, "Pattern_Category", "generic"
            )
            logging.info(f"    • Default Patterns: {default_count}")
            logging.info(f"    • Generic Patterns: {generic_count}")
        logging.info("=" * 80)

        # Use custom filename if provided, otherwise generate default
        base_filename = config["output"]

        # Export based on format preference
        export_success = False

        if config["format"] in ["xlsx", "both"]:
            output_filename = os.path.join(output_dir, f"{base_filename}.xlsx")
            logging.info(f"Attempting to export to {output_filename}...")
            excel_success = export_to_excel(
                summary_data,
                secret_scanning_data,
                output_filename,
            )
            export_success = export_success or excel_success

        if config["format"] in ["csv", "both"]:
            logging.info(f"Exporting to CSV files...")
            csv_success = export_to_csv(
                secret_scanning_data,
                config["output"],
            )
            export_success = export_success or csv_success

        if not export_success:
            logging.error("Export failed!")
            return 1

        # Calculate and log execution time
        elapsed_time = time.time() - start_time
        logging.info("=" * 80)
        logging.info(f"Script finished successfully in {elapsed_time:.2f} seconds")
        logging.info(f"Log file: {log_filename}")
        logging.info("=" * 80)
        return 0

    except KeyboardInterrupt:
        logging.warning("Script interrupted by user")
        return 130
    except Exception as e:
        logging.error(f"FATAL ERROR: {type(e).__name__}: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit(main())
