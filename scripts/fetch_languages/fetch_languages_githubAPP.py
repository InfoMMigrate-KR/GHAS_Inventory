import os
import sys
import time
import logging
import requests
import pandas as pd
import csv
import psutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from dotenv import load_dotenv
from typing import List, Dict, Tuple, Optional
from functools import wraps
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Add the parent directory to the path to import github_auth
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from github_auth.github_app_auth import GitHubAppAuth

# --- Configuration ---
# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Get the root directory (two levels up from this script)
root_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))

# Load environment variables from .env file in root directory
dotenv_path = os.path.join(root_dir, ".env")
load_dotenv(dotenv_path=dotenv_path)
print(f"Loading .env from: {dotenv_path}")

# Setup Logging (will be enhanced in main function)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

# Constants
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
ENTERPRISE_SLUG = os.getenv("GH_ENTERPRISE_SLUG")

if not ENTERPRISE_SLUG:
    raise ValueError("Please set GH_ENTERPRISE_SLUG in .env file.")

# Performance and reliability constants
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "2"))  # seconds
TIMEOUT = int(os.getenv("TIMEOUT", "30"))  # seconds
MAX_CONCURRENT_ORGS = int(
    os.getenv("MAX_CONCURRENT_ORGS", "3")
)  # Conservative for GitHub App
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "1.0"))  # seconds between requests
SESSION_POOL_SIZE = int(os.getenv("SESSION_POOL_SIZE", "10"))
MEMORY_THRESHOLD_MB = int(os.getenv("MEMORY_THRESHOLD_MB", "1000"))
RATE_LIMIT_BUFFER = int(os.getenv("RATE_LIMIT_BUFFER", "100"))


# --- Performance Monitoring ---
class PerformanceMonitor:
    def __init__(self):
        self.start_time = time.time()
        self.organizations_processed = 0
        self.organizations_failed = 0
        self.total_repos = 0
        self.total_languages = 0
        self.api_requests = 0
        self.memory_peak_mb = 0
        self.rate_limit_hits = 0
        self.retry_attempts = 0
        self._lock = threading.Lock()

    def update_stats(
        self,
        orgs_processed=0,
        orgs_failed=0,
        repos=0,
        languages=0,
        api_calls=0,
        retries=0,
        rate_limits=0,
    ):
        with self._lock:
            self.organizations_processed += orgs_processed
            self.organizations_failed += orgs_failed
            self.total_repos += repos
            self.total_languages += languages
            self.api_requests += api_calls
            self.retry_attempts += retries
            self.rate_limit_hits += rate_limits

    def monitor_memory(self) -> float:
        try:
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            if memory_mb > self.memory_peak_mb:
                self.memory_peak_mb = memory_mb
            if memory_mb > MEMORY_THRESHOLD_MB:
                logging.warning(f"High memory usage detected: {memory_mb:.1f} MB")
            return memory_mb
        except Exception:
            return 0

    def log_summary(self):
        elapsed = time.time() - self.start_time
        logging.info("=" * 60)
        logging.info("PERFORMANCE SUMMARY")
        logging.info("=" * 60)
        logging.info(f"Total Execution Time: {elapsed:.2f}s ({elapsed/60:.1f} minutes)")
        logging.info(f"Organizations Processed: {self.organizations_processed}")
        logging.info(f"Organizations Failed: {self.organizations_failed}")
        logging.info(
            f"Success Rate: {(self.organizations_processed/(self.organizations_processed+self.organizations_failed)*100):.1f}%"
            if (self.organizations_processed + self.organizations_failed) > 0
            else "0%"
        )
        logging.info(f"Total Repositories: {self.total_repos}")
        logging.info(f"Total Language Records: {self.total_languages}")
        logging.info(f"API Requests Made: {self.api_requests}")
        logging.info(f"Retry Attempts: {self.retry_attempts}")
        logging.info(f"Rate Limit Hits: {self.rate_limit_hits}")
        logging.info(f"Peak Memory Usage: {self.memory_peak_mb:.1f} MB")
        if self.organizations_processed > 0:
            logging.info(
                f"Average Repos per Org: {self.total_repos/self.organizations_processed:.1f}"
            )
            logging.info(
                f"Average Processing Time per Org: {elapsed/self.organizations_processed:.2f}s"
            )
        logging.info(
            f"Processing Rate: {self.total_languages/elapsed:.1f} language records per second"
        )
        logging.info("=" * 60)


def retry_on_failure(
    max_retries: int = MAX_RETRIES,
    delay: int = RETRY_DELAY,
    monitor: PerformanceMonitor = None,
):
    """Enhanced retry decorator with exponential backoff and monitoring"""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (
                    requests.exceptions.RequestException,
                    requests.exceptions.HTTPError,
                ) as e:
                    last_exception = e
                    if monitor:
                        monitor.update_stats(retries=1)

                    if attempt < max_retries:
                        wait_time = delay * (2**attempt)  # Exponential backoff
                        logging.warning(
                            f"Attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s..."
                        )
                        time.sleep(wait_time)
                    else:
                        logging.error(
                            f"All {max_retries + 1} attempts failed for {func.__name__}"
                        )
                except Exception as e:
                    logging.error(f"Unexpected error in {func.__name__}: {e}")
                    raise
            raise last_exception

        return wrapper

    return decorator


def create_session_with_retries() -> requests.Session:
    """Create a requests session with retry strategy and connection pooling"""
    session = requests.Session()

    # Configure retry strategy
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST", "OPTIONS"],
        raise_on_status=False,
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


# Constants
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
ENTERPRISE_SLUG = os.getenv("GH_ENTERPRISE_SLUG")

if not ENTERPRISE_SLUG:
    raise ValueError("Please set GH_ENTERPRISE_SLUG in .env file.")

# Performance and reliability constants
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "2"))  # seconds
TIMEOUT = int(os.getenv("TIMEOUT", "30"))  # seconds
MAX_CONCURRENT_ORGS = int(
    os.getenv("MAX_CONCURRENT_ORGS", "3")
)  # Conservative for GitHub App
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "1.0"))  # seconds between requests
SESSION_POOL_SIZE = int(os.getenv("SESSION_POOL_SIZE", "10"))
MEMORY_THRESHOLD_MB = int(os.getenv("MEMORY_THRESHOLD_MB", "1000"))
RATE_LIMIT_BUFFER = int(os.getenv("RATE_LIMIT_BUFFER", "100"))

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
    def __init__(
        self, github_app_auth, enterprise_slug, monitor: PerformanceMonitor = None
    ):
        self.enterprise_slug = enterprise_slug
        self.github_app_auth = github_app_auth
        self.session = None
        self.monitor = monitor or PerformanceMonitor()
        self.rate_limit_remaining = None
        self.rate_limit_reset_time = None
        self.authenticated_orgs = {}  # Cache for authenticated sessions

    def get_organizations_from_csv(self, csv_path: str = None):
        """
        Fetch organizations from a CSV file with automatic fallback to fetch_orgs.py.

        Args:
            csv_path: Path to CSV file with organizations. If None, uses default locations.

        Returns:
            List of organization login names
        """
        logging.info("Fetching organizations from CSV...")

        # Try multiple locations for the CSV file
        possible_paths = []

        if csv_path:
            possible_paths.append(csv_path)

        # Check common locations
        script_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))

        possible_paths.extend(
            [
                os.path.join(script_dir, "organizations.csv"),
                os.path.join(root_dir, "scripts", "output", "organizations.csv"),
                os.path.join(script_dir, "..", "output", "organizations.csv"),
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
                        # Check again for the CSV file in multiple expected locations
                        potential_outputs = [
                            os.path.join(root_dir, "scripts", "output", "organizations.csv"),
                            os.path.join(script_dir, "..", "output", "organizations.csv"),
                            os.path.join(root_dir, "output", "organizations.csv"),
                        ]
                        
                        for output_csv in potential_outputs:
                            if os.path.exists(output_csv):
                                csv_file = output_csv
                                logging.info(
                                    f"Organizations CSV file created at: {csv_file}"
                                )
                                break
                        else:
                            logging.error(
                                f"fetch_orgs.py completed but organizations.csv not found. Checked locations:\n" +
                                "\n".join(f"  - {p}" for p in potential_outputs)
                            )
                    else:
                        logging.error(
                            f"fetch_orgs.py failed with error: {result.stderr}"
                        )
                except Exception as e:
                    logging.error(f"Failed to execute fetch_orgs.py: {e}")
            else:
                logging.error(f"fetch_orgs.py not found at: {fetch_orgs_path}")

            if not csv_file:
                logging.error(
                    "Could not find or generate organizations.csv file.\n"
                    "Please either:\n"
                    "1. Create an organizations.csv file (one org name per line) in one of these locations:\n" +
                    "\n".join(f"   - {p}" for p in possible_paths) + "\n"
                    "2. OR ensure the GitHub App is installed in at least one organization in your enterprise.\n"
                    "   The script will auto-detect available installations."
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

    @retry_on_failure()
    def check_rate_limit(self, headers: Dict[str, str]):
        """Check and handle rate limiting"""
        try:
            self.rate_limit_remaining = int(headers.get("X-RateLimit-Remaining", 5000))
            reset_timestamp = int(headers.get("X-RateLimit-Reset", time.time() + 3600))
            self.rate_limit_reset_time = datetime.fromtimestamp(reset_timestamp)

            if self.rate_limit_remaining < RATE_LIMIT_BUFFER:
                wait_time = (
                    self.rate_limit_reset_time - datetime.now()
                ).total_seconds()
                if wait_time > 0:
                    logging.warning(
                        f"Rate limit low ({self.rate_limit_remaining} remaining). Waiting {wait_time:.1f}s..."
                    )
                    self.monitor.update_stats(rate_limits=1)
                    time.sleep(min(wait_time, 900))  # Max 15 minutes
        except (ValueError, TypeError) as e:
            logging.debug(f"Could not parse rate limit headers: {e}")

    @retry_on_failure()
    def fetch_repo_languages(
        self, org_login: str
    ) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """
        Fetches repository language data for a specific organization using GraphQL.
        Returns:
           - (List[Dict], None): Data if successful
           - (None, str): Error message if failed
        """
        org_start_time = time.time()
        logging.info(f"Scanning Organization: {org_login}")
        repo_data = []
        cursor = None
        has_next = True
        repos_processed = 0

        # Get or create authenticated session for this organization
        try:
            if org_login not in self.authenticated_orgs:
                if not self.github_app_auth.authenticate_for_organization(org_login):
                    error_msg = f"Failed to authenticate for organization {org_login}"
                    logging.error(error_msg)
                    self.monitor.update_stats(orgs_failed=1)
                    return None, f"ERROR: {error_msg}"

                session = create_session_with_retries()
                session.headers.update(
                    self.github_app_auth.get_authenticated_session().headers
                )
                session.headers.update({"Accept": "application/vnd.github.v3+json"})
                self.authenticated_orgs[org_login] = session
                logging.info(f"Created authenticated session for {org_login}")
            else:
                session = self.authenticated_orgs[org_login]
                logging.debug(f"Reusing authenticated session for {org_login}")

        except Exception as e:
            error_msg = f"Failed to get authenticated session for {org_login}: {str(e)}"
            logging.error(error_msg)
            self.monitor.update_stats(orgs_failed=1)
            return None, f"ERROR: {error_msg}"

        try:
            while has_next:
                variables = {"org": org_login, "cursor": cursor}
                self.monitor.monitor_memory()

                try:
                    # Add request delay for rate limiting
                    time.sleep(REQUEST_DELAY)

                    response = session.post(
                        GITHUB_GRAPHQL_URL,
                        json={"query": QUERY_ORG_REPOS, "variables": variables},
                        timeout=TIMEOUT,
                    )

                    self.monitor.update_stats(api_calls=1)
                    self.check_rate_limit(response.headers)

                    # Enhanced HTTP status handling
                    if response.status_code == 401:
                        error_msg = "Unauthorized - Invalid or expired token"
                        logging.error(f"{org_login}: {error_msg}")
                        # Try to re-authenticate
                        if org_login in self.authenticated_orgs:
                            del self.authenticated_orgs[org_login]
                        return None, f"ERROR: {error_msg}"
                    elif response.status_code == 403:
                        error_msg = "Forbidden - Token lacks necessary permissions or rate limited"
                        logging.error(f"{org_login}: {error_msg}")
                        return None, f"ERROR: {error_msg}"
                    elif response.status_code == 404:
                        error_msg = (
                            "Not Found - Organization may not exist or no access"
                        )
                        logging.warning(f"{org_login}: {error_msg}")
                        return None, f"ERROR: {error_msg}"
                    elif response.status_code == 429:
                        error_msg = "Rate limited - too many requests"
                        logging.warning(f"{org_login}: {error_msg}")
                        self.monitor.update_stats(rate_limits=1)
                        # Wait and retry handled by decorator
                        raise requests.exceptions.HTTPError(f"429 {error_msg}")
                    elif response.status_code not in [200, 201]:
                        error_msg = (
                            f"HTTP {response.status_code} - {response.text[:200]}"
                        )
                        logging.error(f"{org_login}: {error_msg}")
                        raise requests.exceptions.HTTPError(error_msg)

                    try:
                        json_resp = response.json()
                    except Exception as json_error:
                        error_msg = f"Failed to parse JSON response: {json_error}"
                        logging.error(f"{org_login}: {error_msg}")
                        raise requests.exceptions.RequestException(error_msg)

                    # Enhanced GraphQL error handling
                    if "errors" in json_resp:
                        errors = json_resp["errors"]
                        error_details = []

                        for error in errors:
                            error_type = error.get("type", "UNKNOWN")
                            error_msg = error.get("message", "Unknown error")
                            error_details.append(f"{error_type}: {error_msg}")

                            # Specific error handling
                            if "RATE_LIMITED" in error_type:
                                logging.warning(
                                    f"{org_login}: Rate limited, waiting..."
                                )
                                self.monitor.update_stats(rate_limits=1)
                                time.sleep(60)  # Wait 1 minute for rate limit reset
                                continue
                            elif "FORBIDDEN" in error_type or "SAML" in error_msg:
                                logging.warning(
                                    f"{org_login}: Access restriction - {error_msg}"
                                )
                                self.monitor.update_stats(orgs_failed=1)
                                return None, f"ERROR: Access restriction - {error_msg}"
                            elif "NOT_FOUND" in error_type:
                                logging.warning(f"{org_login}: Not found - {error_msg}")
                                self.monitor.update_stats(orgs_failed=1)
                                return (
                                    None,
                                    f"ERROR: Organization not found - {error_msg}",
                                )

                        full_error = "; ".join(error_details)
                        logging.error(f"{org_login}: GraphQL errors - {full_error}")
                        self.monitor.update_stats(orgs_failed=1)
                        return None, f"ERROR: GraphQL - {full_error}"

                    # Validate response structure
                    if not json_resp.get("data"):
                        error_msg = (
                            "No data in response - possible authentication issue"
                        )
                        logging.error(f"{org_login}: {error_msg}")
                        self.monitor.update_stats(orgs_failed=1)
                        return None, f"ERROR: {error_msg}"

                    if not json_resp.get("data", {}).get("organization"):
                        error_msg = "Organization not found or no access permissions"
                        logging.warning(f"{org_login}: {error_msg}")
                        self.monitor.update_stats(orgs_failed=1)
                        return None, f"ERROR: {error_msg}"

                    repos_node = json_resp["data"]["organization"]["repositories"]
                    page_repos = repos_node["nodes"]
                    repos_processed += len(page_repos)

                    for repo in page_repos:
                        total_size = repo["languages"]["totalSize"]

                        # Handle repositories with no languages
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

                        # Process language data
                        for edge in repo["languages"]["edges"]:
                            size = edge["size"]
                            percentage = (
                                (size / total_size * 100) if total_size > 0 else 0
                            )

                            repo_data.append(
                                {
                                    "Organization": org_login,
                                    "Repository": repo["name"],
                                    "Language": edge["node"]["name"],
                                    "Bytes": size,
                                    "Percentage": round(percentage, 2),
                                }
                            )

                    # Update pagination
                    page_info = repos_node["pageInfo"]
                    has_next = page_info["hasNextPage"]
                    cursor = page_info["endCursor"] if has_next else None

                    if has_next:
                        logging.debug(
                            f"{org_login}: Processing next page (cursor: {cursor[:10] if cursor else 'None'}...)"
                        )

                except requests.exceptions.Timeout:
                    error_msg = f"Request timeout after {TIMEOUT}s"
                    logging.error(f"{org_login}: {error_msg}")
                    self.monitor.update_stats(orgs_failed=1)
                    raise requests.exceptions.RequestException(error_msg)
                except requests.exceptions.RequestException as e:
                    error_msg = f"Network error: {str(e)}"
                    logging.error(f"{org_login}: {error_msg}")
                    self.monitor.update_stats(orgs_failed=1)
                    raise
                except Exception as e:
                    error_msg = f"Unexpected error processing page: {str(e)}"
                    logging.error(f"{org_login}: {error_msg}")
                    self.monitor.update_stats(orgs_failed=1)
                    raise

            # Success - update stats and log results
            org_time = time.time() - org_start_time
            languages_count = len(repo_data)

            self.monitor.update_stats(
                orgs_processed=1, repos=repos_processed, languages=languages_count
            )

            logging.info(
                f"✓ {org_login}: {repos_processed} repos, {languages_count} language records "
                f"in {org_time:.2f}s ({languages_count/org_time:.1f} records/s)"
            )

            return repo_data, None

        except Exception as e:
            org_time = time.time() - org_start_time
            error_msg = f"Failed after {org_time:.2f}s: {str(e)}"
            logging.error(f"✗ {org_login}: {error_msg}")
            self.monitor.update_stats(orgs_failed=1)
            return None, f"ERROR: {error_msg}"

    def process_organizations_concurrently(
        self, organizations: List[str]
    ) -> Tuple[List[Dict], List[str]]:
        """Process multiple organizations concurrently with proper rate limiting"""
        all_repo_data = []
        error_messages = []

        def process_single_org(
            org_login: str,
        ) -> Tuple[str, Optional[List[Dict]], Optional[str]]:
            """Process a single organization and return results"""
            try:
                data, error = self.fetch_repo_languages(org_login)
                return org_login, data, error
            except Exception as e:
                error_msg = f"Unexpected error processing {org_login}: {str(e)}"
                logging.error(error_msg)
                self.monitor.update_stats(orgs_failed=1)
                return org_login, None, f"ERROR: {error_msg}"

        # Use ThreadPoolExecutor for concurrent processing
        with ThreadPoolExecutor(
            max_workers=MAX_CONCURRENT_ORGS, thread_name_prefix="GitHubOrg"
        ) as executor:
            logging.info(
                f"Processing {len(organizations)} organizations with {MAX_CONCURRENT_ORGS} concurrent workers..."
            )

            # Submit all tasks
            future_to_org = {
                executor.submit(process_single_org, org): org for org in organizations
            }

            # Process completed tasks
            for future in as_completed(future_to_org):
                org_login = future_to_org[future]
                try:
                    _, data, error = future.result()

                    if data:
                        all_repo_data.extend(data)
                        logging.info(
                            f"✓ Successfully processed {org_login}: {len(data)} language records"
                        )
                    else:
                        error_messages.append(f"{org_login}: {error}")
                        logging.warning(f"✗ Failed to process {org_login}: {error}")

                except Exception as e:
                    error_msg = f"Exception in future for {org_login}: {str(e)}"
                    error_messages.append(f"{org_login}: {error_msg}")
                    logging.error(error_msg)
                    self.monitor.update_stats(orgs_failed=1)

        return all_repo_data, error_messages

    def cleanup_resources(self):
        """Clean up resources and close sessions"""
        for org_login, session in self.authenticated_orgs.items():
            try:
                session.close()
                logging.debug(f"Closed session for {org_login}")
            except Exception as e:
                logging.debug(f"Error closing session for {org_login}: {e}")

        self.authenticated_orgs.clear()
        logging.info("Cleaned up all authenticated sessions")


def main():
    # Start timing and performance monitoring
    monitor = PerformanceMonitor()
    start_time = datetime.now()

    # Setup enhanced logging with file output
    timestamp = start_time.strftime("%Y%m%d_%H%M%S")
    log_dir = os.path.join(script_dir, "..", "output", "fetch_languages", "logs")
    os.makedirs(log_dir, exist_ok=True)

    # Create detailed log file
    log_filename = os.path.join(log_dir, f"language_scan_{timestamp}.log")

    # Clear any existing handlers
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    # Enhanced logging configuration
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Create formatters
    detailed_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - [%(threadName)s] %(funcName)s:%(lineno)d - %(message)s"
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

    # Initialize GitHub App authentication
    try:
        github_app_auth = GitHubAppAuth()
        logging.info("Successfully initialized GitHub App authentication")
    except Exception as e:
        logging.error(f"FATAL: Failed to initialize GitHub App auth: {e}")
        return

    scanner = GitHubScanner(github_app_auth, ENTERPRISE_SLUG)

    # 1. Get List of Organizations from CSV with automatic fallback to fetch_orgs.py
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
    output_dir = os.path.join(script_dir, "..", "output", "fetch_languages")
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
    try:
        main()
    except KeyboardInterrupt:
        logging.warning("Script interrupted by user (Ctrl+C)")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Fatal error in main execution: {e}")
        import traceback

        logging.error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)
