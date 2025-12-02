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
        "Repository_Name": lambda alert: (
            safe_get(alert, "repository", "full_name").split("/")[1]
            if safe_get(alert, "repository", "full_name")
            and "/" in safe_get(alert, "repository", "full_name")
            else safe_get(alert, "repository", "full_name")
        ),
        "Secret_Type": ("secret_type_display_name",),
        "Secret_Type_ID": ("secret_type",),
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
        ALERT_STATE: Alert state to fetch - open, resolved, all (default: open)
        OUTPUT_FILENAME: Custom output filename without extension (optional)
        OUTPUT_FORMAT: Output format - xlsx, csv, both (default: xlsx)

    Returns:
        dict: Configuration dictionary
    """

    config = {
        "state": os.getenv("ALERT_STATE", "open").lower(),
        "output": os.getenv("OUTPUT_FILENAME"),
        "format": os.getenv("OUTPUT_FORMAT", "xlsx").lower(),
    }

    # Validate state (Secret scanning supports: open, resolved)
    valid_states = ["open", "resolved", "all"]
    if config["state"] not in valid_states:
        logging.warning(
            f"Invalid ALERT_STATE '{config['state']}'. Using 'open'. "
            f"Valid options for secret scanning: {', '.join(valid_states)}"
        )
        config["state"] = "open"

    # Validate format
    valid_formats = ["xlsx", "csv", "both"]
    if config["format"] not in valid_formats:
        logging.warning(
            f"Invalid OUTPUT_FORMAT '{config['format']}'. Using 'xlsx'. "
            f"Valid options: {', '.join(valid_formats)}"
        )
        config["format"] = "xlsx"

    logging.info("Configuration loaded from environment variables:")
    logging.info(f"  - Alert State: {config['state']}")
    logging.info(f"  - Output Format: {config['format']}")
    if config["output"]:
        logging.info(f"  - Custom Output Filename: {config['output']}")

    return config


def load_config() -> Tuple[str, List[str]]:
    """
    Loads configuration from environment variables with validation.
    Exits if required configuration is missing or invalid.

    Returns:
        tuple: (enterprise_slug, list of PATs)
    """
    enterprise_slug = os.getenv("GITHUB_ENTERPRISE_SLUG")
    pats_str = os.getenv("GITHUB_PATS")

    if not enterprise_slug:
        logging.error("FATAL: GITHUB_ENTERPRISE_SLUG environment variable not set.")
        exit(1)

    if not enterprise_slug.replace("-", "").replace("_", "").isalnum():
        logging.error(
            f"FATAL: Invalid GITHUB_ENTERPRISE_SLUG format: {enterprise_slug}"
        )
        exit(1)

    if not pats_str:
        logging.error("FATAL: GITHUB_PATS environment variable not set.")
        exit(1)

    pats = [token.strip() for token in pats_str.split(",") if token.strip()]

    if not pats:
        logging.error("FATAL: No valid PATs found in GITHUB_PATS.")
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
def fetch_all_pages(
    endpoint_url: str,
    headers: Dict,
    params: Optional[Dict],
    pat_cycler: itertools.cycle,
) -> List[Dict]:
    """
    Fetches all pages of results from a GitHub API endpoint with retry logic.

    Args:
        endpoint_url (str): The initial URL for the API endpoint.
        headers (dict): Base headers for the request.
        params (dict): Query parameters for the request.
        pat_cycler (itertools.cycle): A cycler for PATs.

    Returns:
        list: A list containing all items from all pages.
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
    summary_data: List[Dict],
    secret_scanning_data: List[Dict],
    timestamp: str = None,
) -> bool:
    """
    Export secret scanning data to CSV files as fallback.

    Args:
        summary_data: Summary statistics
        secret_scanning_data: Secret scanning alerts
        timestamp: Timestamp string for filenames

    Returns:
        bool: True if any file was successfully created
    """
    success_count = 0

    try:
        if summary_data:
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_csv(
                os.path.join(output_dir, f"summary_{timestamp}.csv"), index=False
            )
            logging.info("Saved summary data as CSV")
            success_count += 1
    except Exception as e:
        logging.error(f"Error saving summary CSV: {e}")

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

        # Fetch secret scanning alerts
        try:
            secret_scanning_alerts = fetch_all_pages(
                f"{base_api_url}/enterprises/{enterprise_slug}/secret-scanning/alerts",
                headers,
                params,
                pat_cycler,
            )
            logging.info(
                f"SUCCESS: Fetched {len(secret_scanning_alerts)} secret scanning alerts."
            )
        except Exception as exc:
            logging.error(
                f"ERROR: Failed to fetch secret scanning alerts: {type(exc).__name__}: {exc}"
            )
            secret_scanning_alerts = []

        # Extract and process secret scanning data
        logging.info("Processing secret scanning alert data...")
        secret_scanning_data = extract_secret_scanning_data(secret_scanning_alerts)

        # Generate timestamp for this query execution
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

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

        # Use custom filename if provided, otherwise generate default
        if config["output"]:
            base_filename = config["output"]
        else:
            base_filename = f"secret_scanning_alerts_{timestamp}"

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
                summary_data,
                secret_scanning_data,
                timestamp if not config["output"] else config["output"],
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
