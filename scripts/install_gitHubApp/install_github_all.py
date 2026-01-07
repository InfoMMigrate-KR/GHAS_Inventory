#!/usr/bin/env python3
"""
API-Based GitHub App Installation Across Enterprise Organizations

This script automates the installation of one or more GitHub Apps across all
organizations in a GitHub Enterprise using the GitHub REST API. Unlike browser
automation, this approach uses the Enterprise App Installation API and requires:

1. An "Installer App" - Enterprise-owned app with permission to install other apps
2. One or more "Automation Apps" - The apps you want installed across organizations

This follows the official GitHub documentation:
https://docs.github.com/en/enterprise-cloud@latest/admin/managing-github-apps-for-your-enterprise/automate-installations

Permissions and Access Requirements:
- ENTERPRISE OWNER: Required to create and manage the Installer App
- ORGANIZATION ADMIN: NOT required - Enterprise-level access is sufficient
- Install Mode: Installer App needs 'Enterprise organization installations' (read/write)
- Uninstall Mode: Requires the Automation App's own JWT (not Installer App)
  - The DELETE /app/installations/{id} API requires auth AS the app being deleted
- Installer App Token: Used for listing enterprise organizations via GraphQL API

Features:
- Pure API-based (no browser required)
- CI/CD pipeline friendly
- **Multi-app support** - Install multiple apps in one run
- JWT-based GitHub App authentication
- Parallel installation support
- Comprehensive error handling and retry logic
- Detailed JSON output with installation results

Requirements:
- Python 3.9+
- PyJWT: pip install pyjwt[crypto]
- requests: pip install requests
- Installer App private key file

Usage:
    # Single app installation
    python install_github_all.py \\
        --enterprise my-enterprise \\
        --installer-app-id 12345 \\
        --installer-private-key /path/to/installer-app.pem \\
        --installer-install-id 67890 \\
        --automation-app-client-id Iv1.abc123

    # Multiple apps installation (comma-separated)
    python install_github_all.py \\
        --enterprise my-enterprise \\
        --installer-app-id 12345 \\
        --installer-private-key /path/to/installer-app.pem \\
        --installer-install-id 67890 \\
        --automation-app-client-id Iv1.abc123,Iv1.def456,Iv1.ghi789

    # With parallel processing
    python install_github_all.py \\
        --enterprise my-enterprise \\
        --installer-app-id 12345 \\
        --installer-private-key /path/to/installer-app.pem \\
        --installer-install-id 67890 \\
        --automation-app-client-id Iv1.abc123,Iv1.def456 \\
        --parallel

Author: GitHub Copilot
Date: 2026-01-05
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Iterator


# Load .env file if it exists
def load_env_file():
    """Load environment variables from .env file if it exists.

    Note: Environment variables from .env file take priority over existing
    environment variables to ensure consistent configuration.
    """
    env_paths = [
        Path(__file__).parent.parent / ".env",  # Project root
        Path.cwd() / ".env",  # Current directory
    ]
    # Keys that should be loaded from .env (all API installer config keys)
    api_installer_keys = {
        "GH_ENTERPRISE_SLUG",
        "INSTALLER_APP_ID",
        "INSTALLER_PRIVATE_KEY",
        "INSTALLER_INSTALL_ID",
        "AUTOMATION_APP_CLIENT_ID",
        "AUTOMATION_APP_CLIENT_IDS",
        "AUTOMATION_APPS_CONFIG",
    }

    for env_path in env_paths:
        if env_path.exists():
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        # Load all keys (override existing for consistent behavior)
                        if key:
                            os.environ[key] = value
            return str(env_path)
    return None


_env_file = load_env_file()

try:
    import jwt
except ImportError:
    print("Error: PyJWT is required. Install with: pip install pyjwt[crypto]")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("Error: requests is required. Install with: pip install requests")
    sys.exit(1)

# Setup logging (console only initially, file handler added in main)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def setup_file_logging(enterprise: str, log_folder: str = "logs") -> Path:
    """
    Setup file logging for the execution.

    Creates a log file in the logs folder with enterprise name and timestamp.
    Returns the path to the log file.
    """
    # Create logs directory if it doesn't exist
    log_dir = Path(__file__).parent.parent / log_folder
    log_dir.mkdir(parents=True, exist_ok=True)

    # Create log filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"api_app_installer_{enterprise}_{timestamp}.log"

    # Create file handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)  # Capture all levels in file
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
    )

    # Add file handler to root logger
    logging.getLogger().addHandler(file_handler)

    logger.info(f"Logging to file: {log_file}")
    return log_file


@dataclass
class InstallationResult:
    """Result of an app installation or uninstallation attempt."""

    org_name: str
    success: bool
    operation: str = "install"  # "install" or "uninstall"
    app_client_id: Optional[str] = None
    installation_id: Optional[int] = None
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GitHubAppAuth:
    """Handles GitHub App JWT generation and token management."""

    def __init__(
        self,
        app_id: str,
        private_key_path: str,
        base_url: str = "https://api.github.com",
    ):
        self.app_id = app_id
        self.private_key_path = private_key_path
        self.base_url = base_url
        self._private_key: Optional[str] = None
        self._token_cache: Dict[str, Dict[str, Any]] = {}

        # Validate private key exists
        if not Path(private_key_path).exists():
            raise FileNotFoundError(f"Private key not found: {private_key_path}")

    @property
    def private_key(self) -> str:
        """Lazy load private key."""
        if self._private_key is None:
            with open(self.private_key_path, "r") as f:
                self._private_key = f.read()
        return self._private_key

    def generate_jwt(self) -> str:
        """
        Generate a JWT for GitHub App authentication.

        JWT is valid for 10 minutes (GitHub's maximum).
        """
        now = int(time.time())
        payload = {
            "iat": now - 60,  # Issued 60 seconds ago (clock drift buffer)
            "exp": now + 600,  # Expires in 10 minutes
            "iss": self.app_id,  # Issuer is the App ID
        }

        token = jwt.encode(payload, self.private_key, algorithm="RS256")
        logger.debug(
            f"Generated JWT for app {self.app_id}, expires at {datetime.fromtimestamp(now + 600)}"
        )
        return token

    def get_installation_token(self, installation_id: str) -> str:
        """
        Get an installation access token for the specified installation.

        Tokens are cached and reused until 5 minutes before expiration.
        """
        cache_key = f"install_{installation_id}"

        # Check cache
        if cache_key in self._token_cache:
            cached = self._token_cache[cache_key]
            if cached["expires_at"] > datetime.now().replace(tzinfo=None) + timedelta(
                minutes=5
            ):
                logger.debug(f"Using cached token for installation {installation_id}")
                return cached["token"]
            else:
                del self._token_cache[cache_key]

        # Request new token
        jwt_token = self.generate_jwt()
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "gh-scripts-api-installer",
        }

        url = f"{self.base_url}/app/installations/{installation_id}/access_tokens"
        response = requests.post(url, headers=headers, timeout=30)

        if response.status_code != 201:
            raise Exception(
                f"Failed to get installation token: {response.status_code} - {response.text}"
            )

        data = response.json()
        expires_at_str = data["expires_at"]

        # Parse the ISO format datetime and convert to timezone-naive
        if expires_at_str.endswith("Z"):
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        else:
            expires_at = datetime.fromisoformat(expires_at_str)

        # Convert to naive datetime for consistency
        expires_at = expires_at.replace(tzinfo=None)

        # Cache the token
        self._token_cache[cache_key] = {
            "token": data["token"],
            "expires_at": expires_at,
        }

        logger.debug(f"Obtained installation token, expires at {expires_at}")
        return data["token"]

    def get_first_accessible_org(self) -> Optional[str]:
        """
        Get the first organization where the GitHub App is installed.
        This can be used to authenticate for enterprise queries.

        Returns:
            str: Organization login name, or None if none found
        """
        jwt_token = self.generate_jwt()
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        try:
            # List all installations for this GitHub App
            response = requests.get(
                f"{self.base_url}/app/installations", headers=headers, timeout=30
            )

            if response.status_code == 200:
                installations = response.json()

                for installation in installations:
                    account = installation.get("account", {})
                    account_login = account.get("login")

                    # Prefer Organization accounts, but accept User accounts too
                    if account_login:
                        logger.debug(f"Using GitHub App installation: {account_login}")
                        return account_login

                logger.warning(
                    "No valid GitHub App installations found with login names"
                )
                return None
            else:
                logger.error(
                    f"Failed to list installations: HTTP {response.status_code}"
                )
                logger.debug(f"Response: {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error getting installations: {e}")
            return None

    def get_authenticated_session(
        self, installation_id: str = None
    ) -> requests.Session:
        """
        Get an authenticated requests session using the installation token.

        Args:
            installation_id: The installation ID to authenticate with.
                           If not provided, will try to use a default one.

        Returns:
            requests.Session: An authenticated session ready to use
        """
        if installation_id is None:
            # Try to get the first accessible installation
            first_org = self.get_first_accessible_org()
            if not first_org:
                raise Exception("No accessible installations found for authentication")
            # We need to find the installation ID for this org - this is a simplified approach
            # In practice, you'd store this or look it up
            installation_id = "default"  # This would need to be set properly

        try:
            token = self.get_installation_token(installation_id)
        except Exception as e:
            raise Exception(f"Failed to get installation token: {e}")

        session = requests.Session()
        session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "gh-scripts-api-installer",
            }
        )

        return session


class EnterpriseAppInstaller:
    """
    Installs or uninstalls one or more GitHub Apps across all organizations in an enterprise.

    Install Mode:
    Uses the Enterprise Organization Installations API:
    POST /enterprises/{enterprise}/apps/organizations/{org}/installations

    Uninstall Mode:
    Uses the GitHub App Installations API:
    DELETE /app/installations/{installation_id}
    Note: Uninstall requires authenticating as the automation app being uninstalled,
    not the installer app. This means you need the automation app's private key.

    Supports both single app installation (backwards compatible) and
    multi-app installation in a single run.

    Large Enterprise Support (3000+ orgs):
    - Rate limiting to respect GitHub API limits
    - Batched parallel processing to control memory usage
    - Thread-safe progress saving with locks
    - Periodic checkpointing for recovery
    """

    # GitHub API rate limits
    RATE_LIMIT_REQUESTS_PER_HOUR = 5000
    RATE_LIMIT_BUFFER = 0.8  # Use only 80% of limit to be safe

    def __init__(
        self,
        enterprise: str,
        installer_auth: GitHubAppAuth,
        installer_install_id: str,
        automation_app_client_ids: List[str],
        repository_selection: str = "all",
        base_url: str = "https://api.github.com",
        output_folder: str = "outputs",
        parallel: bool = False,
        max_workers: int = 5,
        dry_run: bool = False,
        resume_from: Optional[str] = None,
        batch_size: int = 100,
        rate_limit_delay: float = 0.0,
        uninstall: bool = False,
        automation_app_auth: Optional[Dict[str, GitHubAppAuth]] = None,
    ):
        self.enterprise = enterprise
        self.installer_auth = installer_auth
        self.installer_install_id = installer_install_id
        self.automation_app_client_ids = automation_app_client_ids
        self.repository_selection = repository_selection
        self.base_url = base_url
        self.output_folder = Path(output_folder)
        self.parallel = parallel
        self.max_workers = max_workers
        self.dry_run = dry_run
        self.resume_from = resume_from
        self.batch_size = batch_size
        self.rate_limit_delay = rate_limit_delay
        self.uninstall = uninstall
        self.automation_app_auth = automation_app_auth or {}

        # Validate uninstall requirements
        if self.uninstall and not self.automation_app_auth:
            raise ValueError(
                "Uninstall mode requires automation app authentication. "
                "Provide --automation-app-id and --automation-app-private-key for each app to uninstall."
            )

        # Thread-safety lock for saving results
        self._save_lock = threading.Lock()
        self._api_lock = threading.Lock()  # For rate limiting
        self._last_api_call = 0.0

        # Execution timing tracking
        self._execution_start_time: Optional[float] = None
        self._execution_end_time: Optional[float] = None
        self._org_listing_duration: float = 0.0
        self._installation_duration: float = 0.0

        # API call tracking
        self._api_calls_lock = threading.Lock()
        self._api_calls: Dict[str, int] = {}  # endpoint -> count
        self._total_api_calls: int = 0

        # Rate limit tracking (from response headers)
        self._rate_limit_info: Dict[str, Any] = {
            "limit": None,
            "remaining": None,
            "reset": None,
            "used": None,
            "last_checked": None,
        }
        self._rate_limit_log_interval: int = 100  # Log every N calls

        # Enterprise state tracking - persistent file per enterprise (stored in data/ folder)
        self._enterprise_state_lock = threading.Lock()
        self._data_folder = Path(__file__).parent.parent / "data"
        self._data_folder.mkdir(parents=True, exist_ok=True)
        self._enterprise_state_file = (
            self._data_folder / f"enterprise_apps_state_{self.enterprise}.json"
        )
        self._enterprise_state_md_file = (
            self._data_folder / f"enterprise_apps_state_{self.enterprise}.md"
        )
        self._enterprise_state: Dict[str, Any] = self._load_enterprise_state()

        # Calculate minimum delay between API calls for rate limiting
        # Default: Allow up to 80% of rate limit per hour
        effective_limit = int(
            self.RATE_LIMIT_REQUESTS_PER_HOUR * self.RATE_LIMIT_BUFFER
        )
        self._min_api_delay = 3600.0 / effective_limit  # seconds between calls

        # Multi-app mode flag
        self.multi_app_mode = len(automation_app_client_ids) > 1

        # Operation type for display
        self.operation_name = "Uninstall" if self.uninstall else "Install"
        self.operation_past = "uninstalled" if self.uninstall else "installed"
        self.operation_present = "uninstalling" if self.uninstall else "installing"

        # Results tracking - per-app when multi-app, flat when single-app
        # Use "installed_orgs" and "success_orgs" interchangeably (keeping installed_orgs for backwards compatibility)
        self.results: List[InstallationResult] = []
        if self.multi_app_mode:
            self.installed_orgs: Dict[str, List[str]] = {
                app_id: [] for app_id in automation_app_client_ids
            }
            self.failed_orgs: Dict[str, List[Dict[str, str]]] = {
                app_id: [] for app_id in automation_app_client_ids
            }
            self.skipped_orgs: Dict[str, List[Dict[str, str]]] = {
                app_id: [] for app_id in automation_app_client_ids
            }
            self.previously_completed: Dict[str, set] = {
                app_id: set() for app_id in automation_app_client_ids
            }
        else:
            # Single-app mode: use flat lists for backwards compatibility
            self.installed_orgs: List[str] = []
            self.failed_orgs: List[Dict[str, str]] = []
            self.skipped_orgs: List[Dict[str, str]] = []
            self.previously_completed: set = set()

        # Load previous results if resuming
        if resume_from:
            self._load_previous_results(resume_from)

    def _load_previous_results(self, resume_file: str) -> None:
        """
        Load previous run results to skip already-completed organizations.

        Supports multiple resume sources:
        - "state" or "auto": Use the enterprise state file (data/enterprise_apps_state_{enterprise}.json)
        - Path to a previous JSON output file
        - Path to an enterprise state JSON file

        Args:
            resume_file: "state", "auto", or path to a previous JSON file
        """
        # Handle "state" or "auto" keywords to use enterprise state file
        if resume_file.lower() in ("state", "auto"):
            resume_path = self._enterprise_state_file
            if not resume_path.exists():
                logger.info("No enterprise state file found - starting fresh")
                return
            logger.info(f"Resuming from enterprise state file: {resume_path.name}")
        else:
            resume_path = Path(resume_file)
            if not resume_path.exists():
                raise FileNotFoundError(f"Resume file not found: {resume_file}")

        logger.info(f"Loading previous results from: {resume_path}")

        with open(resume_path, "r") as f:
            previous_data = json.load(f)

        # Detect file format: enterprise state file vs output results file
        is_state_file = "organizations" in previous_data and "apps" in previous_data

        if is_state_file:
            # Enterprise state file format - more comprehensive
            self._load_from_state_file(previous_data)
        else:
            # Legacy output results file format
            self._load_from_output_file(previous_data)

        if self.multi_app_mode:
            total_skipped = sum(len(v) for v in self.previously_completed.values())
        else:
            total_skipped = len(self.previously_completed)
        logger.info(
            f"Resuming: Will skip {total_skipped} previously completed org-app combinations"
        )

    def _load_from_state_file(self, state_data: Dict[str, Any]) -> None:
        """
        Load resume data from enterprise state file format.

        The state file tracks each org-app combination with status:
        - installed: app was successfully installed
        - already_installed: app was already installed
        - uninstalled: app was uninstalled
        - failed: installation failed

        For install mode: skip 'installed' and 'already_installed'
        For uninstall mode: skip 'uninstalled' (nothing to uninstall)
        """
        organizations = state_data.get("organizations", {})

        for org_name, org_data in organizations.items():
            apps = org_data.get("apps", {})

            for app_id, app_status in apps.items():
                status = app_status.get("status", "")

                # Determine if we should skip this org-app combo
                should_skip = False
                if self.uninstall:
                    # For uninstall: skip if already uninstalled
                    should_skip = status == "uninstalled"
                else:
                    # For install: skip if already installed (successfully or previously)
                    should_skip = status in ("installed", "already_installed")

                if should_skip:
                    if self.multi_app_mode:
                        # Only add if this app is in current run's app list
                        if app_id in self.automation_app_client_ids:
                            self.previously_completed[app_id].add(org_name)
                    else:
                        # Single-app mode: check if it matches current app
                        if app_id == self.automation_app_client_ids[0]:
                            self.previously_completed.add(org_name)

        # Log summary by status
        installed_count = sum(
            1
            for org_data in organizations.values()
            for app_status in org_data.get("apps", {}).values()
            if app_status.get("status") in ("installed", "already_installed")
        )
        uninstalled_count = sum(
            1
            for org_data in organizations.values()
            for app_status in org_data.get("apps", {}).values()
            if app_status.get("status") == "uninstalled"
        )
        failed_count = sum(
            1
            for org_data in organizations.values()
            for app_status in org_data.get("apps", {}).values()
            if app_status.get("status") == "failed"
        )

        logger.info(
            f"State file summary: {installed_count} installed, {uninstalled_count} uninstalled, {failed_count} failed"
        )

    def _load_from_output_file(self, previous_data: Dict[str, Any]) -> None:
        """
        Load resume data from legacy output results file format.

        Supports both single-app (flat lists) and multi-app (dict by app_id) formats.
        """
        # Check if previous data was multi-app format
        is_previous_multi_app = isinstance(previous_data.get("installed_orgs"), dict)

        if self.multi_app_mode:
            # Current run is multi-app
            if is_previous_multi_app:
                # Both multi-app: load per-app data
                for app_id in self.automation_app_client_ids:
                    installed = previous_data.get("installed_orgs", {}).get(app_id, [])
                    for org in installed:
                        self.previously_completed[app_id].add(org)
                        if org not in self.installed_orgs[app_id]:
                            self.installed_orgs[app_id].append(org)

                    skipped = previous_data.get("skipped_orgs", {}).get(app_id, [])
                    for org_data in skipped:
                        org_name = (
                            org_data.get("name", org_data)
                            if isinstance(org_data, dict)
                            else org_data
                        )
                        reason = (
                            org_data.get("reason", "")
                            if isinstance(org_data, dict)
                            else ""
                        )
                        if "already installed" in reason.lower():
                            self.previously_completed[app_id].add(org_name)
            else:
                # Previous was single-app, current is multi-app: apply to first app
                first_app = self.automation_app_client_ids[0]
                installed = previous_data.get("installed_orgs", [])
                for org in installed:
                    self.previously_completed[first_app].add(org)
                    if org not in self.installed_orgs[first_app]:
                        self.installed_orgs[first_app].append(org)
        else:
            # Current run is single-app
            if is_previous_multi_app:
                # Previous was multi-app: load data for current app
                current_app = self.automation_app_client_ids[0]
                installed = previous_data.get("installed_orgs", {}).get(current_app, [])
                for org in installed:
                    self.previously_completed.add(org)
                    if org not in self.installed_orgs:
                        self.installed_orgs.append(org)

                skipped = previous_data.get("skipped_orgs", {}).get(current_app, [])
                for org_data in skipped:
                    org_name = (
                        org_data.get("name", org_data)
                        if isinstance(org_data, dict)
                        else org_data
                    )
                    reason = (
                        org_data.get("reason", "") if isinstance(org_data, dict) else ""
                    )
                    if "already installed" in reason.lower():
                        self.previously_completed.add(org_name)
            else:
                # Both single-app: load flat data
                installed = previous_data.get("installed_orgs", [])
                for org in installed:
                    self.previously_completed.add(org)
                    if org not in self.installed_orgs:
                        self.installed_orgs.append(org)

                skipped = previous_data.get("skipped_orgs", [])
                for org_data in skipped:
                    org_name = (
                        org_data.get("name", org_data)
                        if isinstance(org_data, dict)
                        else org_data
                    )
                    reason = (
                        org_data.get("reason", "") if isinstance(org_data, dict) else ""
                    )
                    if "already installed" in reason.lower():
                        self.previously_completed.add(org_name)

    def _rate_limit_wait(self) -> None:
        """
        Enforce rate limiting between API calls.

        Uses a lock to ensure thread-safe rate limiting in parallel mode.
        Calculates the minimum delay needed to stay within GitHub's rate limits.
        """
        with self._api_lock:
            now = time.time()
            elapsed = now - self._last_api_call

            # Use custom delay if set, otherwise use calculated minimum
            delay = (
                self.rate_limit_delay
                if self.rate_limit_delay > 0
                else self._min_api_delay
            )

            if elapsed < delay:
                sleep_time = delay - elapsed
                if sleep_time > 0.1:  # Only log if significant delay
                    logger.debug(f"Rate limit: waiting {sleep_time:.2f}s")
                time.sleep(sleep_time)

            self._last_api_call = time.time()

    def _track_api_call(self, endpoint: str) -> None:
        """Track an API call for statistics."""
        with self._api_calls_lock:
            self._total_api_calls += 1
            if endpoint not in self._api_calls:
                self._api_calls[endpoint] = 0
            self._api_calls[endpoint] += 1

    def _get_api_stats(self) -> Dict[str, Any]:
        """Get API call statistics."""
        with self._api_calls_lock:
            return {
                "total_calls": self._total_api_calls,
                "endpoints": dict(self._api_calls),
                "unique_endpoints": len(self._api_calls),
            }

    def _update_rate_limit_info(self, response: requests.Response) -> None:
        """
        Update rate limit info from response headers.

        GitHub API returns these headers:
        - X-RateLimit-Limit: Total requests allowed per hour
        - X-RateLimit-Remaining: Requests remaining in current window
        - X-RateLimit-Reset: Unix timestamp when the rate limit resets
        - X-RateLimit-Used: Requests used in current window
        """
        with self._api_calls_lock:
            self._rate_limit_info["limit"] = response.headers.get("X-RateLimit-Limit")
            self._rate_limit_info["remaining"] = response.headers.get(
                "X-RateLimit-Remaining"
            )
            self._rate_limit_info["reset"] = response.headers.get("X-RateLimit-Reset")
            self._rate_limit_info["used"] = response.headers.get("X-RateLimit-Used")
            self._rate_limit_info["last_checked"] = datetime.now().isoformat()

            # Log rate limit status every N calls
            if (
                self._total_api_calls > 0
                and self._total_api_calls % self._rate_limit_log_interval == 0
            ):
                self._log_rate_limit_status()

    def _log_rate_limit_status(self) -> None:
        """Log current rate limit status."""
        info = self._rate_limit_info
        if info["limit"] and info["remaining"]:
            limit = int(info["limit"])
            remaining = int(info["remaining"])
            used = int(info["used"]) if info["used"] else limit - remaining
            reset_ts = int(info["reset"]) if info["reset"] else 0

            # Calculate time until reset
            now = time.time()
            reset_in = max(0, reset_ts - now)
            reset_mins = int(reset_in // 60)
            reset_secs = int(reset_in % 60)

            # Calculate usage percentage
            usage_pct = (used / limit * 100) if limit > 0 else 0

            logger.info(
                f"[STATS] Rate Limit Status (after {self._total_api_calls} API calls):"
            )
            logger.info(
                f"   Used: {used}/{limit} ({usage_pct:.1f}%) | Remaining: {remaining} | Resets in: {reset_mins}m {reset_secs}s"
            )

            # Warn if getting close to limit
            if remaining < 500:
                logger.warning(
                    f"[WARN] LOW RATE LIMIT: Only {remaining} requests remaining!"
                )
            elif usage_pct > 70:
                logger.warning(f"[WARN] Rate limit usage above 70%: {usage_pct:.1f}%")

    def _handle_rate_limit_response(
        self, response: requests.Response, attempt: int
    ) -> float:
        """
        Handle 429 Too Many Requests response with exponential backoff.

        Returns the number of seconds to wait before retrying.
        """
        # Check for Retry-After header (in seconds)
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                wait_time = int(retry_after)
                logger.warning(
                    f"[RATE LIMITED] Rate limited (429). Retry-After header suggests waiting {wait_time}s"
                )
                return wait_time
            except ValueError:
                pass

        # Check X-RateLimit-Reset for when limit resets
        reset_ts = response.headers.get("X-RateLimit-Reset")
        if reset_ts:
            try:
                reset_time = int(reset_ts)
                now = time.time()
                wait_time = max(1, reset_time - now + 1)  # Add 1 second buffer
                if wait_time < 3600:  # Only use if less than 1 hour
                    logger.warning(
                        f"[RATE LIMITED] Rate limited (429). Rate limit resets in {wait_time:.0f}s"
                    )
                    return wait_time
            except ValueError:
                pass

        # Fallback: exponential backoff with jitter
        base_wait = 60  # Start with 1 minute
        max_wait = 900  # Max 15 minutes
        wait_time = min(base_wait * (2**attempt), max_wait)
        # Add jitter (0-25% of wait time)
        jitter = wait_time * 0.25 * (hash(time.time()) % 100 / 100)
        wait_time += jitter

        logger.warning(
            f"[RATE LIMITED] Rate limited (429). Exponential backoff: waiting {wait_time:.1f}s (attempt {attempt + 1})"
        )
        return wait_time

    def _load_enterprise_state(self) -> Dict[str, Any]:
        """
        Load existing enterprise state from persistent file.

        The enterprise state tracks all apps and their installation status
        across all organizations over time.
        """
        self.output_folder.mkdir(parents=True, exist_ok=True)

        if self._enterprise_state_file.exists():
            try:
                with open(self._enterprise_state_file, "r") as f:
                    state = json.load(f)
                logger.info(
                    f"Loaded existing enterprise state from: {self._enterprise_state_file.name}"
                )
                return state
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load enterprise state: {e}. Starting fresh.")

        # Initialize new state
        return {
            "enterprise": self.enterprise,
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "apps": {},  # app_client_id -> app info
            "organizations": {},  # org_name -> org info with app statuses
            "history": [],  # list of operations with timestamps
        }

    def _update_enterprise_state(self, result: InstallationResult) -> None:
        """
        Update enterprise state with a single operation result.

        This is called after each successful operation for streaming updates.
        Thread-safe for parallel processing.
        """
        with self._enterprise_state_lock:
            now = datetime.now().isoformat()
            org_name = result.org_name
            app_id = result.app_client_id
            operation = (
                result.operation
                if hasattr(result, "operation") and result.operation
                else ("uninstall" if self.uninstall else "install")
            )

            # Update last_updated timestamp
            self._enterprise_state["last_updated"] = now

            # Initialize app entry if not exists
            if app_id not in self._enterprise_state["apps"]:
                self._enterprise_state["apps"][app_id] = {
                    "client_id": app_id,
                    "first_seen": now,
                    "installed_count": 0,
                    "uninstalled_count": 0,
                }

            # Initialize org entry if not exists
            if org_name not in self._enterprise_state["organizations"]:
                self._enterprise_state["organizations"][org_name] = {
                    "name": org_name,
                    "apps": {},  # app_id -> status info
                }

            # Determine status based on operation and result
            if result.success:
                if operation == "uninstall":
                    status = "uninstalled"
                    self._enterprise_state["apps"][app_id]["uninstalled_count"] = (
                        self._enterprise_state["apps"][app_id].get(
                            "uninstalled_count", 0
                        )
                        + 1
                    )
                elif result.error and "already" in result.error.lower():
                    status = "already_installed"
                else:
                    status = "installed"
                    self._enterprise_state["apps"][app_id]["installed_count"] = (
                        self._enterprise_state["apps"][app_id].get("installed_count", 0)
                        + 1
                    )
            else:
                status = "failed"

            # Update org's app status
            self._enterprise_state["organizations"][org_name]["apps"][app_id] = {
                "status": status,
                "installation_id": result.installation_id,
                "last_operation": operation,
                "last_updated": now,
                "error": result.error if not result.success else None,
            }

            # Add to history (keep last 1000 entries to prevent unbounded growth)
            history_entry = {
                "timestamp": now,
                "operation": operation,
                "app_client_id": app_id,
                "org_name": org_name,
                "status": status,
                "installation_id": result.installation_id,
                "error": result.error if not result.success else None,
            }
            self._enterprise_state["history"].append(history_entry)
            if len(self._enterprise_state["history"]) > 1000:
                self._enterprise_state["history"] = self._enterprise_state["history"][
                    -1000:
                ]

            # Save state to files (streaming update)
            self._save_enterprise_state()

    def _save_enterprise_state(self) -> None:
        """
        Save enterprise state to JSON and Markdown files.

        Called after each operation for streaming updates.
        Must be called within _enterprise_state_lock.
        """
        try:
            # Save JSON
            with open(self._enterprise_state_file, "w") as f:
                json.dump(self._enterprise_state, f, indent=2)

            # Save Markdown
            self._save_enterprise_state_markdown()

        except IOError as e:
            logger.warning(f"Failed to save enterprise state: {e}")

    def _save_enterprise_state_markdown(self) -> None:
        """Generate and save Markdown report for enterprise state."""
        state = self._enterprise_state

        md_content = "```markdown\n"
        md_content += f"# Enterprise Apps State: {state['enterprise']}\n\n"
        md_content += f"**Created:** {state.get('created_at', 'N/A')}  \n"
        md_content += f"**Last Updated:** {state.get('last_updated', 'N/A')}  \n\n"

        # Apps Summary
        md_content += "---\n\n## Apps Summary\n\n"
        apps = state.get("apps", {})
        if apps:
            md_content += "| App Client ID | Installed | Uninstalled | First Seen |\n"
            md_content += "|---------------|-----------|-------------|------------|\n"
            for app_id, app_info in sorted(apps.items()):
                short_id = f"{app_id[:20]}..." if len(app_id) > 20 else app_id
                installed = app_info.get("installed_count", 0)
                uninstalled = app_info.get("uninstalled_count", 0)
                first_seen = app_info.get("first_seen", "N/A")[:10]  # Just date
                md_content += (
                    f"| `{short_id}` | {installed} | {uninstalled} | {first_seen} |\n"
                )
        else:
            md_content += "_No apps tracked yet._\n"

        # Organizations Summary
        md_content += "\n---\n\n## Organizations Status\n\n"
        orgs = state.get("organizations", {})
        if orgs and apps:
            # Create header with all app IDs (shortened)
            app_ids = list(apps.keys())
            app_headers = [f"{a[:12]}..." if len(a) > 12 else a for a in app_ids]

            md_content += "| Organization |"
            for ah in app_headers:
                md_content += f" {ah} |"
            md_content += "\n"

            md_content += "|--------------|"
            for _ in app_ids:
                md_content += "-------------|"
            md_content += "\n"

            for org_name in sorted(orgs.keys()):
                org_info = orgs[org_name]
                org_apps = org_info.get("apps", {})
                md_content += f"| {org_name} |"
                for app_id in app_ids:
                    if app_id in org_apps:
                        status = org_apps[app_id].get("status", "unknown")
                        # Use ASCII indicators for status instead of emojis
                        if status == "installed":
                            md_content += " [OK] Installed |"
                        elif status == "already_installed":
                            md_content += " [OK] Already |"
                        elif status == "uninstalled":
                            md_content += " [--] Uninstalled |"
                        elif status == "failed":
                            md_content += " [ERR] Failed |"
                        else:
                            md_content += f" {status} |"
                    else:
                        md_content += " - |"
                md_content += "\n"
        else:
            md_content += "_No organizations tracked yet._\n"

        # Recent History (last 20 operations)
        md_content += "\n---\n\n## Recent Operations (Last 20)\n\n"
        history = state.get("history", [])
        if history:
            recent = history[-20:]
            md_content += "| Timestamp | Operation | App | Organization | Status |\n"
            md_content += "|-----------|-----------|-----|--------------|--------|\n"
            for entry in reversed(recent):
                ts = entry.get("timestamp", "N/A")[:19].replace("T", " ")
                op = entry.get("operation", "unknown").title()
                app = entry.get("app_client_id", "N/A")
                app_short = f"{app[:12]}..." if len(app) > 12 else app
                org = entry.get("org_name", "N/A")
                status = entry.get("status", "unknown")
                status_icon = (
                    "[OK]"
                    if status in ["installed", "already_installed", "uninstalled"]
                    else "[ERR]"
                )
                md_content += f"| {ts} | {op} | `{app_short}` | {org} | {status_icon} {status} |\n"
        else:
            md_content += "_No operations recorded yet._\n"

        md_content += (
            "\n---\n\n*This file is automatically updated by `install_github_all.py`*\n"
        )
        md_content += "```\n"

        with open(self._enterprise_state_md_file, "w") as f:
            f.write(md_content)

    def _get_headers(self, token: str) -> Dict[str, str]:
        """Get standard API headers with the given token."""
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "gh-scripts-api-installer",
        }

    def save_orgs_to_csv(
        self,
        orgs: List[Dict[str, Any]],
        output_dir: str = "data",
        use_timestamp: bool = True,
    ) -> str:
        """Save organization list to CSV file for transparency and manual editing.

        Args:
            orgs: List of organization dictionaries
            output_dir: Directory to save the CSV file
            use_timestamp: Whether to include timestamp in filename

        Returns:
            str: Path to the saved CSV file
        """
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        # Generate filename with enterprise and optionally timestamp
        if use_timestamp:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.enterprise}_organizations_{timestamp}.csv"
        else:
            filename = "organizations.csv"
        filepath = os.path.join(output_dir, filename)

        # Write to CSV with headers
        with open(filepath, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)

            # Write header
            writer.writerow(["login", "id", "name", "selected"])

            # Write organization data
            for org in orgs:
                # Skip None entries
                if org is None:
                    continue

                login = org.get("login", "")
                org_id = org.get("id", "")
                name = org.get("name", login)  # Fallback to login if name is empty
                selected = (
                    "yes"  # Default to selected, user can change to "no" to exclude
                )

                writer.writerow([login, org_id, name, selected])

        logger.info(f"Organizations exported to CSV: {filepath}")
        logger.info(
            f"Edit the 'selected' column to choose organizations for app installation"
        )
        return filepath

    def load_orgs_from_csv(self, csv_file: str) -> List[Dict[str, Any]]:
        """Load organizations from CSV file, respecting the 'selected' column.

        Args:
            csv_file: Path to the CSV file

        Returns:
            List of organization dictionaries (only selected ones)
        """
        orgs = []
        try:
            with open(csv_file, "r", encoding="utf-8") as csvfile:
                reader = csv.DictReader(csvfile)

                for row in reader:
                    # Only include organizations marked as selected
                    selected = row.get("selected", "yes").lower().strip()
                    if selected in ["yes", "y", "true", "1"]:
                        org = {
                            "login": row.get("login", "").strip(),
                            "id": row.get("id", "").strip(),
                            "name": row.get("name", "").strip(),
                        }
                        # Only add if login is not empty
                        if org["login"]:
                            orgs.append(org)

            logger.info(
                f"Loaded {len(orgs)} selected organizations from CSV: {csv_file}"
            )

        except FileNotFoundError:
            logger.error(f"CSV file not found: {csv_file}")
            logger.warning("Continuing with empty organization list")
        except Exception as e:
            logger.error(f"Error reading CSV file {csv_file}: {e}")
            logger.warning("Continuing with empty organization list")

        return orgs

    def list_enterprise_orgs(self) -> List[Dict[str, Any]]:
        """
        List all organizations in the enterprise with automatic CSV workflow.

        Workflow:
        1. Check if 'organizations.csv' exists in outputs/ folder and use it
        2. Otherwise, fetch from GraphQL API and create organizations.csv in outputs/

        This gives users full control over which organizations to process.
        """
        # Create outputs directory if it doesn't exist
        os.makedirs("outputs", exist_ok=True)

        # Check for organizations.csv file in outputs directory
        standard_csv_path = os.path.join("outputs", "organizations.csv")
        if os.path.exists(standard_csv_path):
            logger.info(f"Found existing organizations.csv file: {standard_csv_path}")
            logger.info("Using existing organizations list - no GraphQL fetch needed")
            orgs = self.load_orgs_from_csv(standard_csv_path)
            if orgs:
                logger.info(
                    f"Loaded {len(orgs)} selected organizations from existing CSV"
                )
                return orgs
            else:
                logger.warning("No organizations selected in existing CSV file")
                logger.info(
                    "You can edit organizations.csv and set 'selected' column to 'yes' for organizations you want to process"
                )
                return []

        # Fetch from GraphQL API and create organizations.csv in outputs/
        logger.info(
            "No organizations.csv found in outputs/ - fetching from GraphQL API..."
        )
        try:
            discovered_orgs = self._list_orgs_via_graphql()

            # Create organizations.csv file in outputs directory (not timestamped)
            if discovered_orgs:
                csv_file = self.save_orgs_to_csv(
                    discovered_orgs, output_dir="outputs", use_timestamp=False
                )

                # Also create a timestamped backup for audit trail
                backup_file = self.save_orgs_to_csv(
                    discovered_orgs, output_dir="outputs", use_timestamp=True
                )
                logger.info(f"Backup copy saved to: {backup_file}")

                logger.info("")
                logger.info("[TIP] Next steps:")
                logger.info(
                    f"  1. Edit {csv_file} to select specific organizations (change 'selected' column to 'yes')"
                )
                logger.info(
                    f"  2. Re-run the script - it will use your edited organizations.csv automatically"
                )
                logger.info("")

            return discovered_orgs

        except Exception as e:
            logger.error(f"Failed to list organizations via GraphQL: {e}")
            logger.warning("This could be due to:")
            logger.warning("  - Enterprise permission issues with the installer app")
            logger.warning("  - Network connectivity problems")
            logger.warning("  - Invalid enterprise slug")
            logger.warning("  - Authentication token issues")
            logger.info(
                f"Consider manually creating outputs/organizations.csv with your organization list"
            )

    def _list_orgs_via_graphql(self) -> List[Dict[str, Any]]:
        """
        List enterprise organizations using the GraphQL API.
        Uses the installer app token for authentication with robust error handling.
        Continues fetching even if individual pages fail.
        """
        logger.debug(
            "Using installer app token with GraphQL API to list enterprise organizations..."
        )

        orgs = []
        has_next_page = True
        cursor = None
        graphql_url = "https://api.github.com/graphql"
        max_retries = 3
        page_num = 0

        try:
            # Get installer app token for GraphQL API access
            token = self.installer_auth.get_installation_token(
                self.installer_install_id
            )
        except Exception as e:
            logger.error(f"Failed to get installer app token: {e}")
            raise Exception(f"Authentication failed: {e}")

        while has_next_page:
            page_num += 1
            attempts = 0
            page_success = False

            while attempts < max_retries and not page_success:
                try:
                    # Build GraphQL query with pagination
                    after_clause = f', after: "{cursor}"' if cursor else ""

                    # Use the same query structure as fetch_Orgs.py
                    query = f"""
                    query {{
                        enterprise(slug: "{self.enterprise}") {{
                            name
                            organizations(first: 100{after_clause}) {{
                                pageInfo {{
                                    hasNextPage
                                    endCursor
                                }}
                                nodes {{
                                    login
                                    id
                                    name
                                }}
                            }}
                        }}
                    }}
                    """

                    headers = {
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "User-Agent": "gh-scripts-api-installer",
                    }

                    logger.debug(
                        f"Fetching organizations page {page_num} (cursor: {cursor}, attempt {attempts + 1})..."
                    )

                    response = requests.post(
                        graphql_url,
                        json={"query": query},
                        headers=headers,
                        timeout=60,
                    )

                    # Track API call
                    self._track_api_call("POST /graphql (enterprise.organizations)")

                    # Handle HTTP errors like fetch_Orgs.py
                    if response.status_code in [401, 403]:
                        logger.warning(
                            f"HTTP {response.status_code} encountered on page {page_num}. Re-authentication may be needed."
                        )
                        attempts += 1
                        time.sleep(2)
                        continue

                    if response.status_code != 200:
                        logger.warning(
                            f"HTTP error {response.status_code} on page {page_num}: {response.text}"
                        )
                        attempts += 1
                        if attempts < max_retries:
                            time.sleep(2)
                            continue
                        else:
                            logger.error(
                                f"Failed to fetch page {page_num} after {max_retries} attempts"
                            )
                            break  # Skip this page, continue with next

                    data = response.json()

                    # Check for GraphQL errors like fetch_Orgs.py
                    if "errors" in data:
                        errors = data["errors"]

                        # Check for rate limiting
                        is_rate_limit = any(
                            e.get("type") == "RATE_LIMITED"
                            or "rate limit" in e.get("message", "").lower()
                            for e in errors
                        )

                        if is_rate_limit:
                            logger.warning(
                                f"GraphQL Rate Limit Hit on page {page_num}. Waiting..."
                            )
                            time.sleep(60)  # Wait 1 minute for rate limit
                            attempts += 1
                            continue
                        else:
                            logger.warning(
                                f"GraphQL errors on page {page_num}: {errors}"
                            )
                            # Continue with partial data if possible
                            if data.get("data"):
                                logger.info(
                                    "Continuing with partial data from this page"
                                )
                            else:
                                attempts += 1
                                if attempts < max_retries:
                                    time.sleep(2)
                                    continue
                                else:
                                    logger.error(
                                        f"Failed to get valid data from page {page_num} after {max_retries} attempts"
                                    )
                                    break  # Skip this page

                    # Extract organizations
                    enterprise_data = data.get("data", {}).get("enterprise")
                    if not enterprise_data:
                        logger.warning(
                            f"Enterprise '{self.enterprise}' not found or not accessible on page {page_num}"
                        )
                        attempts += 1
                        if attempts < max_retries:
                            time.sleep(2)
                            continue
                        else:
                            logger.error(
                                f"Enterprise data not accessible after {max_retries} attempts"
                            )
                            break  # Skip this page

                    org_data = enterprise_data.get("organizations", {})
                    nodes = org_data.get("nodes", [])

                    if nodes:
                        orgs.extend(nodes)
                        logger.debug(
                            f"Successfully fetched {len(nodes)} organizations from page {page_num}"
                        )

                    # Handle pagination
                    page_info = org_data.get("pageInfo", {})
                    has_next_page = page_info.get("hasNextPage", False)
                    cursor = page_info.get("endCursor")

                    # Mark this page as successful
                    page_success = True

                    # Show progress for large enterprises
                    total_count = org_data.get("totalCount", len(orgs))
                    if total_count > 100 or len(orgs) > 100:
                        logger.info(
                            f"Progress: Fetched {len(orgs)} organizations (page {page_num})..."
                        )

                except requests.exceptions.RequestException as e:
                    logger.warning(
                        f"Network error on page {page_num}, attempt {attempts + 1}: {e}"
                    )
                    attempts += 1
                    if attempts < max_retries:
                        time.sleep(2)
                    continue

                except Exception as e:
                    logger.warning(
                        f"Unexpected error on page {page_num}, attempt {attempts + 1}: {e}"
                    )
                    attempts += 1
                    if attempts < max_retries:
                        time.sleep(2)
                    continue

            # If we failed to get this page after all retries, continue to next page
            if not page_success:
                logger.warning(
                    f"Skipping page {page_num} after {max_retries} failed attempts. Continuing with next page..."
                )
                # Try to continue with next page if we have a cursor, otherwise break
                if cursor:
                    continue
                else:
                    break

        logger.info(
            f"Found {len(orgs)} organizations in enterprise '{self.enterprise}' (via GraphQL)"
        )
        if page_num > 1:
            logger.info(
                f"Successfully processed {page_num} pages with robust error handling"
            )

        return orgs

    def _list_orgs_via_rest_api(self) -> List[Dict[str, Any]]:
        """
        List enterprise organizations using the REST API.
        This may not work with all token types.
        """
        token = self.installer_auth.get_installation_token(self.installer_install_id)
        headers = self._get_headers(token)

        orgs = []
        page = 1
        per_page = 100

        while True:
            url = f"{self.base_url}/enterprises/{self.enterprise}/organizations"
            params = {"page": page, "per_page": per_page}

            logger.debug(f"Fetching organizations page {page}...")
            response = requests.get(url, headers=headers, params=params, timeout=30)

            # Track API call
            self._track_api_call(f"GET /enterprises/{self.enterprise}/organizations")

            if response.status_code != 200:
                error_msg = f"Failed to list organizations: {response.status_code} - {response.text}"
                error_msg += "\n\nHint: The installer app token may not have permission to list enterprise orgs."
                error_msg += "\nTry creating outputs/organizations.csv manually with your organization names."
                raise Exception(error_msg)

            page_orgs = response.json()
            if not page_orgs:
                break

            orgs.extend(page_orgs)
            logger.debug(f"Fetched {len(page_orgs)} organizations on page {page}")

            if len(page_orgs) < per_page:
                break

            page += 1

        logger.info(
            f"Found {len(orgs)} organizations in enterprise '{self.enterprise}' (via REST API)"
        )
        return orgs

    def check_app_installation(self, org_name: str, token: str) -> Optional[int]:
        """
        Check if the automation app is already installed in an organization.

        Returns the installation ID if installed, None otherwise.
        """
        headers = self._get_headers(token)

        # List installations for the automation app
        url = f"{self.base_url}/orgs/{org_name}/installations"
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            installations = response.json().get("installations", [])
            for install in installations:
                if install.get("app_slug") == self.automation_app_client_id:
                    return install.get("id")

        return None

    def install_app_on_org(
        self, org_name: str, app_client_id: str
    ) -> InstallationResult:
        """
        Install a specific automation app on a single organization.

        Uses the Enterprise Organization Installations API.
        Includes rate limiting for large enterprise support.
        Implements 429 retry with exponential backoff.

        Args:
            org_name: The organization login name
            app_client_id: The client ID of the app to install
        """
        app_short = (
            app_client_id[:15] + "..." if len(app_client_id) > 15 else app_client_id
        )
        max_retries = 5  # Maximum retry attempts for rate limiting

        # Apply rate limiting before API call
        self._rate_limit_wait()

        try:
            if self.dry_run:
                logger.info(f"[DRY RUN] Would install {app_short} on {org_name}")
                return InstallationResult(
                    org_name=org_name,
                    app_client_id=app_client_id,
                    success=True,
                    error="DRY RUN - no actual installation",
                )

            # Get installation token
            token = self.installer_auth.get_installation_token(
                self.installer_install_id
            )
            headers = self._get_headers(token)

            # Install the app with retry logic for 429
            url = f"{self.base_url}/enterprises/{self.enterprise}/apps/organizations/{org_name}/installations"
            payload = {
                "client_id": app_client_id,
                "repository_selection": self.repository_selection,
            }

            for attempt in range(max_retries):
                logger.debug(f"Installing app {app_short} on {org_name}...")
                response = requests.post(url, headers=headers, json=payload, timeout=60)

                # Track API call and update rate limit info
                self._track_api_call(
                    f"POST /enterprises/{{enterprise}}/apps/organizations/{{org}}/installations"
                )
                self._update_rate_limit_info(response)

                # Handle 429 Too Many Requests with retry
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        wait_time = self._handle_rate_limit_response(response, attempt)
                        time.sleep(wait_time)
                        # Refresh token after waiting (may have expired)
                        token = self.installer_auth.get_installation_token(
                            self.installer_install_id
                        )
                        headers = self._get_headers(token)
                        continue
                    else:
                        logger.error(
                            f"[ERR] Rate limited for {app_short} on {org_name} after {max_retries} retries"
                        )
                        return InstallationResult(
                            org_name=org_name,
                            app_client_id=app_client_id,
                            success=False,
                            error=f"Rate limited (429) after {max_retries} retries",
                        )

                # Success
                if response.status_code in (200, 201):
                    data = response.json()
                    installation_id = data.get("id")
                    logger.info(
                        f"[OK] Successfully installed {app_short} on {org_name} (installation_id: {installation_id})"
                    )
                    return InstallationResult(
                        org_name=org_name,
                        app_client_id=app_client_id,
                        success=True,
                        installation_id=installation_id,
                    )
                elif response.status_code == 422:
                    # Already installed or validation error
                    error_data = response.json()
                    message = error_data.get("message", "Unknown error")
                    if "already installed" in message.lower():
                        logger.info(
                            f"[SKIP] {app_short} already installed on {org_name}"
                        )
                        return InstallationResult(
                            org_name=org_name,
                            app_client_id=app_client_id,
                            success=True,
                            error="Already installed",
                        )
                    else:
                        logger.warning(
                            f"[ERR] Validation error for {app_short} on {org_name}: {message}"
                        )
                        return InstallationResult(
                            org_name=org_name,
                            app_client_id=app_client_id,
                            success=False,
                            error=message,
                        )
                elif response.status_code == 403:
                    # Forbidden - likely missing enterprise permission
                    error_msg = response.json().get("message", "Forbidden")
                    logger.warning(
                        f"[ERR] Forbidden for {app_short} on {org_name}: {error_msg}"
                    )
                    return InstallationResult(
                        org_name=org_name,
                        app_client_id=app_client_id,
                        success=False,
                        error=f"Forbidden: {error_msg}",
                        details={
                            "hint": 'The installer app may need the "Manage organization installations" enterprise permission. '
                            "Go to: https://github.com/enterprises/{enterprise}/settings/apps to configure."
                        },
                    )
                elif response.status_code == 503:
                    # Service unavailable - retry with backoff
                    if attempt < max_retries - 1:
                        wait_time = min(30 * (2**attempt), 300)  # Max 5 minutes
                        logger.warning(
                            f"[WARN] Service unavailable (503) for {app_short} on {org_name}. Retrying in {wait_time}s..."
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        error_msg = (
                            f"Service unavailable (503) after {max_retries} retries"
                        )
                        logger.error(f"[ERR] {error_msg} for {app_short} on {org_name}")
                        return InstallationResult(
                            org_name=org_name,
                            app_client_id=app_client_id,
                            success=False,
                            error=error_msg,
                        )
                else:
                    error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                    logger.error(
                        f"[ERR] Failed for {app_short} on {org_name}: {error_msg}"
                    )
                    return InstallationResult(
                        org_name=org_name,
                        app_client_id=app_client_id,
                        success=False,
                        error=error_msg,
                    )

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[ERR] Exception for {app_short} on {org_name}: {error_msg}")
            return InstallationResult(
                org_name=org_name,
                app_client_id=app_client_id,
                success=False,
                error=error_msg,
            )

    def get_org_installation_id(
        self, org_name: str, app_client_id: str
    ) -> Optional[int]:
        """
        Get the installation ID for an app on a specific organization.

        Uses the GitHub App Installations API authenticated as the automation app.
        This is required for uninstall operations.

        Args:
            org_name: The organization login name
            app_client_id: The client ID of the app

        Returns:
            The installation ID if found, None otherwise
        """
        if app_client_id not in self.automation_app_auth:
            logger.error(f"No authentication configured for app {app_client_id}")
            return None

        app_auth = self.automation_app_auth[app_client_id]

        try:
            # Generate JWT for the automation app
            jwt_token = app_auth.generate_jwt()
            headers = {
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "gh-scripts-api-installer",
            }

            # Get installation for this org using the automation app's JWT
            url = f"{self.base_url}/orgs/{org_name}/installation"
            response = requests.get(url, headers=headers, timeout=30)

            # Track API call
            self._track_api_call("GET /orgs/{org}/installation")

            if response.status_code == 200:
                data = response.json()
                return data.get("id")
            elif response.status_code == 404:
                # App not installed in this org
                return None
            else:
                logger.warning(
                    f"Failed to get installation for {org_name}: {response.status_code} - {response.text[:100]}"
                )
                return None

        except Exception as e:
            logger.error(f"Error getting installation ID for {org_name}: {e}")
            return None

    def uninstall_app_from_org(
        self, org_name: str, app_client_id: str
    ) -> InstallationResult:
        """
        Uninstall a specific automation app from a single organization.

        Uses the GitHub App Installations API:
        DELETE /app/installations/{installation_id}

        Note: This requires authenticating as the automation app being uninstalled,
        not the installer app. Implements 429 retry with exponential backoff.

        Args:
            org_name: The organization login name
            app_client_id: The client ID of the app to uninstall
        """
        app_short = (
            app_client_id[:15] + "..." if len(app_client_id) > 15 else app_client_id
        )
        max_retries = 5  # Maximum retry attempts for rate limiting

        # Apply rate limiting before API call
        self._rate_limit_wait()

        try:
            if self.dry_run:
                logger.info(f"[DRY RUN] Would uninstall {app_short} from {org_name}")
                return InstallationResult(
                    org_name=org_name,
                    app_client_id=app_client_id,
                    operation="uninstall",
                    success=True,
                    error="DRY RUN - no actual uninstallation",
                )

            # Validate we have auth for this app
            if app_client_id not in self.automation_app_auth:
                error_msg = f"No authentication configured for app {app_client_id}. Provide --automation-app-id and --automation-app-private-key."
                logger.error(f"[ERR] {error_msg}")
                return InstallationResult(
                    org_name=org_name,
                    app_client_id=app_client_id,
                    operation="uninstall",
                    success=False,
                    error=error_msg,
                )

            # First, get the installation ID
            installation_id = self.get_org_installation_id(org_name, app_client_id)

            if installation_id is None:
                logger.info(
                    f"[SKIP] {app_short} not installed on {org_name} (nothing to uninstall)"
                )
                return InstallationResult(
                    org_name=org_name,
                    app_client_id=app_client_id,
                    operation="uninstall",
                    success=True,
                    error="Not installed",
                )

            # Get JWT for the automation app
            app_auth = self.automation_app_auth[app_client_id]

            # Delete the installation with retry logic for 429
            url = f"{self.base_url}/app/installations/{installation_id}"

            for attempt in range(max_retries):
                jwt_token = app_auth.generate_jwt()
                headers = {
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "gh-scripts-api-installer",
                }

                logger.debug(
                    f"Uninstalling app {app_short} from {org_name} (installation_id: {installation_id})..."
                )
                response = requests.delete(url, headers=headers, timeout=60)

                # Track API call and update rate limit info
                self._track_api_call("DELETE /app/installations/{installation_id}")
                self._update_rate_limit_info(response)

                # Handle 429 Too Many Requests with retry
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        wait_time = self._handle_rate_limit_response(response, attempt)
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(
                            f"[ERR] Rate limited for {app_short} on {org_name} after {max_retries} retries"
                        )
                        return InstallationResult(
                            org_name=org_name,
                            app_client_id=app_client_id,
                            operation="uninstall",
                            success=False,
                            error=f"Rate limited (429) after {max_retries} retries",
                        )

                if response.status_code == 204:
                    logger.info(
                        f"[OK] Successfully uninstalled {app_short} from {org_name} (installation_id: {installation_id})"
                    )
                    return InstallationResult(
                        org_name=org_name,
                        app_client_id=app_client_id,
                        operation="uninstall",
                        success=True,
                        installation_id=installation_id,
                    )
                elif response.status_code == 404:
                    logger.info(
                        f"[SKIP] {app_short} installation not found on {org_name} (may already be uninstalled)"
                    )
                    return InstallationResult(
                        org_name=org_name,
                        app_client_id=app_client_id,
                        operation="uninstall",
                        success=True,
                        error="Not found (already uninstalled)",
                    )
                elif response.status_code == 403:
                    error_msg = response.json().get("message", "Forbidden")
                    logger.warning(
                        f"[ERR] Forbidden uninstall for {app_short} on {org_name}: {error_msg}"
                    )
                    return InstallationResult(
                        org_name=org_name,
                        app_client_id=app_client_id,
                        operation="uninstall",
                        success=False,
                        error=f"Forbidden: {error_msg}",
                    )
                elif response.status_code == 503:
                    # Service unavailable - retry with backoff
                    if attempt < max_retries - 1:
                        wait_time = min(30 * (2**attempt), 300)  # Max 5 minutes
                        logger.warning(
                            f"[WARN] Service unavailable (503) for {app_short} on {org_name}. Retrying in {wait_time}s..."
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        error_msg = (
                            f"Service unavailable (503) after {max_retries} retries"
                        )
                        logger.error(f"[ERR] {error_msg} for {app_short} on {org_name}")
                        return InstallationResult(
                            org_name=org_name,
                            app_client_id=app_client_id,
                            operation="uninstall",
                            success=False,
                            error=error_msg,
                        )
                else:
                    error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                    logger.error(
                        f"[ERR] Failed uninstall for {app_short} on {org_name}: {error_msg}"
                    )
                    return InstallationResult(
                        org_name=org_name,
                        app_client_id=app_client_id,
                        operation="uninstall",
                        success=False,
                        error=error_msg,
                    )

        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"[ERR] Exception during uninstall for {app_short} on {org_name}: {error_msg}"
            )
            return InstallationResult(
                org_name=org_name,
                app_client_id=app_client_id,
                operation="uninstall",
                success=False,
                error=error_msg,
            )

    def process_app_on_org(
        self, org_name: str, app_client_id: str
    ) -> InstallationResult:
        """
        Process (install or uninstall) an app on a single organization.

        This is a dispatcher method that calls the appropriate operation based on mode.

        Args:
            org_name: The organization login name
            app_client_id: The client ID of the app
        """
        if self.uninstall:
            return self.uninstall_app_from_org(org_name, app_client_id)
        else:
            return self.install_app_on_org(org_name, app_client_id)

    def _track_result(self, result: InstallationResult, app_client_id: str) -> None:
        """Track installation result in the appropriate data structure."""
        org_name = result.org_name

        # Update enterprise state with streaming save
        self._update_enterprise_state(result)

        if self.multi_app_mode:
            # Multi-app mode: track per-app
            if result.success and not result.error:
                self.installed_orgs[app_client_id].append(org_name)
            elif result.success and result.error:
                self.skipped_orgs[app_client_id].append(
                    {"name": org_name, "reason": result.error}
                )
            else:
                self.failed_orgs[app_client_id].append(
                    {"name": org_name, "reason": result.error or "Unknown"}
                )
        else:
            # Single-app mode: flat lists
            if result.success and not result.error:
                self.installed_orgs.append(org_name)
            elif result.success and result.error:
                self.skipped_orgs.append({"name": org_name, "reason": result.error})
            else:
                self.failed_orgs.append(
                    {"name": org_name, "reason": result.error or "Unknown"}
                )

    def _is_org_app_completed(self, org_name: str, app_client_id: str) -> bool:
        """Check if org-app combination was already completed in previous run."""
        if self.multi_app_mode:
            return org_name in self.previously_completed.get(app_client_id, set())
        else:
            return org_name in self.previously_completed

    def install_sequential(self, orgs: List[Dict[str, Any]]) -> None:
        """Process (install or uninstall) all apps on all organizations sequentially."""
        total_orgs = len(orgs)
        total_apps = len(self.automation_app_client_ids)
        total_combinations = total_orgs * total_apps

        logger.info(
            f"{self.operation_name}ing {total_apps} app(s) on {total_orgs} organization(s) ({total_combinations} total operations)"
        )

        current = 0
        skipped_resume = 0

        for i, org in enumerate(orgs, 1):
            org_name = org.get("login", org.get("name", "unknown"))

            for app_client_id in self.automation_app_client_ids:
                current += 1
                app_short = (
                    app_client_id[:15] + "..."
                    if len(app_client_id) > 15
                    else app_client_id
                )

                # Skip if already completed in previous run
                if self._is_org_app_completed(org_name, app_client_id):
                    skipped_resume += 1
                    logger.debug(
                        f"[{current}/{total_combinations}] Skipping {app_short} on {org_name} (already completed)"
                    )
                    continue

                if self.multi_app_mode:
                    logger.info(
                        f"[{current}/{total_combinations}] {self.operation_name}ing {app_short} on {org_name}..."
                    )
                else:
                    logger.info(f"[{i}/{total_orgs}] Processing {org_name}...")

                result = self.process_app_on_org(org_name, app_client_id)
                self.results.append(result)
                self._track_result(result, app_client_id)

            # Save progress every 10 orgs
            if i % 10 == 0:
                self.save_results()

        if skipped_resume > 0:
            logger.info(
                f"Skipped {skipped_resume} org-app combinations from previous run"
            )

    def _batch_iterator(self, items: List, batch_size: int) -> Iterator[List]:
        """
        Yield successive batches from items list.

        This is memory-efficient for large enterprises as it doesn't
        create all batches upfront.
        """
        for i in range(0, len(items), batch_size):
            yield items[i : i + batch_size]

    def install_parallel(self, orgs: List[Dict[str, Any]]) -> None:
        """
        Process (install or uninstall) all apps on all organizations in parallel with batching.

        For large enterprises (3000+ orgs), processes in batches to:
        - Control memory usage (doesn't submit all tasks at once)
        - Allow checkpointing between batches
        - Prevent overwhelming the API
        """
        # Build list of (org, app) combinations to process
        tasks = []
        skipped_resume = 0

        for org in orgs:
            org_name = org.get("login", org.get("name", "unknown"))
            for app_client_id in self.automation_app_client_ids:
                if self._is_org_app_completed(org_name, app_client_id):
                    skipped_resume += 1
                else:
                    tasks.append((org_name, app_client_id))

        if skipped_resume > 0:
            logger.info(
                f"Skipping {skipped_resume} org-app combinations from previous run"
            )

        total = len(tasks)
        if total == 0:
            logger.info("No new org-app combinations to process")
            return

        # Calculate number of batches for large enterprises
        num_batches = (total + self.batch_size - 1) // self.batch_size

        if num_batches > 1:
            logger.info(
                f"Large enterprise mode: Processing {total} {self.operation_name.lower()}s in {num_batches} batches of {self.batch_size}"
            )
            logger.info(f"Using {self.max_workers} parallel workers with rate limiting")
        else:
            logger.info(
                f"Processing {total} org-app {self.operation_name.lower()}s in parallel (max {self.max_workers} workers)"
            )

        processed = 0
        batch_num = 0

        # Process in batches for memory efficiency and checkpointing
        for batch in self._batch_iterator(tasks, self.batch_size):
            batch_num += 1
            batch_size_actual = len(batch)

            if num_batches > 1:
                logger.info(
                    f"Starting batch {batch_num}/{num_batches} ({batch_size_actual} tasks)"
                )

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit only this batch's tasks
                future_to_task = {
                    executor.submit(self.process_app_on_org, org_name, app_client_id): (
                        org_name,
                        app_client_id,
                    )
                    for org_name, app_client_id in batch
                }

                # Process completed tasks
                for future in as_completed(future_to_task):
                    org_name, app_client_id = future_to_task[future]
                    processed += 1

                    try:
                        result = future.result()
                        self.results.append(result)
                        self._track_result(result, app_client_id)

                    except Exception as e:
                        logger.error(f"Task failed for {org_name}: {e}")
                        if self.multi_app_mode:
                            self.failed_orgs[app_client_id].append(
                                {"name": org_name, "reason": str(e)}
                            )
                        else:
                            self.failed_orgs.append(
                                {"name": org_name, "reason": str(e)}
                            )

                    # Log progress every 10 tasks
                    if processed % 10 == 0:
                        logger.info(
                            f"Progress: {processed}/{total} installations processed"
                        )

            # Save checkpoint after each batch (important for large enterprises)
            if num_batches > 1:
                logger.info(
                    f"Batch {batch_num}/{num_batches} complete. Saving checkpoint..."
                )
            self.save_results()

    def save_results(self) -> tuple:
        """
        Save installation results to JSON and Markdown files.

        Thread-safe: Uses a lock to prevent concurrent writes in parallel mode.
        """
        with self._save_lock:
            self.output_folder.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = f"api_app_installation_{self.enterprise}_{timestamp}"
            json_file = self.output_folder / f"{base_name}.json"
            md_file = self.output_folder / f"{base_name}.md"

            # Calculate summary based on mode
            if self.multi_app_mode:
                total_installed = sum(len(v) for v in self.installed_orgs.values())
                total_skipped = sum(len(v) for v in self.skipped_orgs.values())
                total_failed = sum(len(v) for v in self.failed_orgs.values())
            else:
                total_installed = len(self.installed_orgs)
                total_skipped = len(self.skipped_orgs)
                total_failed = len(self.failed_orgs)

            # Get execution timing from summary
            full_summary = self.get_summary()
            execution_timing = full_summary.get("execution_timing", {})

            results_data = {
                "enterprise": self.enterprise,
                "automation_app_client_ids": self.automation_app_client_ids,
                "multi_app_mode": self.multi_app_mode,
                "repository_selection": self.repository_selection,
                "timestamp": datetime.now().isoformat(),
                "dry_run": self.dry_run,
                "summary": {
                    "installed": total_installed,
                    "skipped": total_skipped,
                    "failed": total_failed,
                    "total": len(self.results),
                    "apps_count": len(self.automation_app_client_ids),
                },
                "execution_timing": execution_timing,
                "installed_orgs": self.installed_orgs,
                "skipped_orgs": self.skipped_orgs,
                "failed_orgs": self.failed_orgs,
                "detailed_results": [r.to_dict() for r in self.results],
            }

            # Save JSON file
            with open(json_file, "w") as f:
                json.dump(results_data, f, indent=2)

            logger.info(f"Results saved to: {json_file}")

            # Save Markdown report
            self._save_markdown_report(md_file, results_data)

            return json_file, md_file

    def _save_markdown_report(
        self, md_file: Path, results_data: Dict[str, Any]
    ) -> None:
        """Generate an executive summary markdown report."""
        summary = results_data["summary"]
        timestamp = results_data["timestamp"]

        # Calculate success rate
        total = summary["total"]
        success_rate = (summary["installed"] / total * 100) if total > 0 else 0

        # Build app list for header
        if self.multi_app_mode:
            apps_str = ", ".join([f"`{a}`" for a in self.automation_app_client_ids])
        else:
            apps_str = f"`{self.automation_app_client_ids[0]}`"

        # Build markdown content
        operation_title = "Uninstallation" if self.uninstall else "Installation"
        success_label = "Uninstalled" if self.uninstall else "Installed"
        skip_reason = "Not installed" if self.uninstall else "Already Installed"

        md_content = f"""# GitHub App {operation_title} Report

**Enterprise:** {self.enterprise}  
**Automation App(s):** {apps_str}  
**Number of Apps:** {len(self.automation_app_client_ids)}  
**Generated:** {timestamp}  
**Mode:** {'Dry Run' if self.dry_run else 'Production'}  

---

## Executive Summary

| Metric | Count |
|--------|-------|
| [SUCCESS] Successfully {success_label} | {summary['installed']} |
| [SKIP] Skipped ({skip_reason}) | {summary['skipped']} |
| [FAILED] Failed | {summary['failed']} |
| **Total Operations** | **{summary['total']}** |

**Success Rate:** {success_rate:.1f}%

---

"""

        if self.multi_app_mode:
            # Multi-app mode: show per-app breakdown
            md_content += "## Per-App Results\n\n"
            for app_id in self.automation_app_client_ids:
                app_installed = len(self.installed_orgs.get(app_id, []))
                app_skipped = len(self.skipped_orgs.get(app_id, []))
                app_failed = len(self.failed_orgs.get(app_id, []))
                app_total = app_installed + app_skipped + app_failed

                md_content += f"### App: `{app_id}`\n\n"
                md_content += f"| {success_label} | Skipped | Failed | Total |\n"
                md_content += f"|-----------|---------|--------|-------|\n"
                md_content += f"| {app_installed} | {app_skipped} | {app_failed} | {app_total} |\n\n"

                # Show success orgs for this app
                if self.installed_orgs.get(app_id):
                    md_content += f"**{success_label} on:** {', '.join(sorted(self.installed_orgs[app_id]))}\n\n"

                # Show failed orgs for this app
                if self.failed_orgs.get(app_id):
                    md_content += f"**Failed:**\n"
                    for org in self.failed_orgs[app_id]:
                        md_content += f"- {org['name']}: {org['reason']}\n"
                    md_content += "\n"
        else:
            # Single-app mode: original format
            md_content += f"## Organizations with Successful {operation_title}\n\n"

            if self.installed_orgs:
                # For uninstall, we may not have installation_id, so show simpler table
                if self.uninstall:
                    md_content += "| # | Organization |\n"
                    md_content += "|---|--------------|\n"
                    for i, org_name in enumerate(sorted(self.installed_orgs), 1):
                        md_content += f"| {i} | {org_name} |\n"
                else:
                    md_content += "| # | Organization | Installation ID |\n"
                    md_content += "|---|--------------|-----------------|\n"
                    for i, org_name in enumerate(sorted(self.installed_orgs), 1):
                        install_id = "N/A"
                        for result in self.results:
                            if result.org_name == org_name and result.installation_id:
                                install_id = str(result.installation_id)
                                break
                        md_content += f"| {i} | {org_name} | {install_id} |\n"
            else:
                md_content += (
                    f"_No organizations were {self.operation_past} in this run._\n"
                )

            # Add skipped organizations
            if self.skipped_orgs:
                md_content += (
                    f"\n---\n\n## Skipped Organizations ({len(self.skipped_orgs)})\n\n"
                )
                md_content += "| Organization | Reason |\n"
                md_content += "|--------------|--------|\n"
                for org in sorted(self.skipped_orgs, key=lambda x: x["name"]):
                    md_content += f"| {org['name']} | {org['reason']} |\n"

            # Add failed organizations
            if self.failed_orgs:
                md_content += (
                    f"\n---\n\n## Failed Organizations ({len(self.failed_orgs)})\n\n"
                )
                md_content += "| Organization | Error |\n"
                md_content += "|--------------|-------|\n"
                for org in sorted(self.failed_orgs, key=lambda x: x["name"]):
                    error = org["reason"].replace("|", "\\|")
                    md_content += f"| {org['name']} | {error} |\n"

        # Add execution timing section
        execution_timing = results_data.get("execution_timing", {})
        if execution_timing:
            md_content += f"\n---\n\n## Execution Timing\n\n"
            md_content += "### Performance Metrics\n\n"
            md_content += "| Metric | Value |\n"
            md_content += "|--------|-------|\n"
            md_content += f"| Organization listing | {execution_timing.get('org_listing_seconds', 0):.2f}s |\n"
            md_content += f"| {self.operation_name}ation time | {execution_timing.get('installation_seconds', 0):.2f}s |\n"
            md_content += f"| **Total execution time** | **{execution_timing.get('total_formatted', 'N/A')}** |\n"
            md_content += f"| Est. API time per call | ~{execution_timing.get('sequential_time_per_op', 0):.2f}s |\n"
            md_content += f"| Throughput | {execution_timing.get('throughput_ops_per_sec', 0):.2f} ops/sec |\n"
            md_content += (
                f"| Processing mode | {execution_timing.get('mode', 'sequential')} |\n"
            )
            workers = execution_timing.get("workers", 1)
            if execution_timing.get("mode") == "parallel":
                md_content += f"| Workers | {workers} |\n"

            md_content += f"\n### Projections for Larger Enterprises\n\n"
            num_apps = len(self.automation_app_client_ids)

            if execution_timing.get("mode") == "parallel":
                md_content += f"Based on estimated API call time of **~{execution_timing.get('sequential_time_per_op', 0):.2f}s** per operation "
                md_content += f"with **{workers} parallel workers**:\n\n"
                md_content += f"| Enterprise Size | Apps | Parallel ({workers} workers) | Sequential |\n"
                md_content += f"|-----------------|------|------------------------|------------|\n"
                md_content += f"| 100 orgs | {num_apps} | ~{execution_timing.get('projection_100_orgs', 'N/A')} | ~{execution_timing.get('projection_100_orgs_sequential', 'N/A')} |\n"
                md_content += f"| 500 orgs | {num_apps} | ~{execution_timing.get('projection_500_orgs', 'N/A')} | ~{execution_timing.get('projection_500_orgs_sequential', 'N/A')} |\n"
                md_content += f"| 1,000 orgs | {num_apps} | ~{execution_timing.get('projection_1000_orgs', 'N/A')} | ~{execution_timing.get('projection_1000_orgs_sequential', 'N/A')} |\n"
                md_content += f"| 3,000 orgs | {num_apps} | ~{execution_timing.get('projection_3000_orgs', 'N/A')} | ~{execution_timing.get('projection_3000_orgs_sequential', 'N/A')} |\n"
            else:
                md_content += f"Based on sequential processing time of **~{execution_timing.get('sequential_time_per_op', 0):.2f}s** per operation:\n\n"
                md_content += "| Enterprise Size | Apps | Estimated Time |\n"
                md_content += "|-----------------|------|----------------|\n"
                md_content += f"| 100 orgs | {num_apps} | ~{execution_timing.get('projection_100_orgs', 'N/A')} |\n"
                md_content += f"| 500 orgs | {num_apps} | ~{execution_timing.get('projection_500_orgs', 'N/A')} |\n"
                md_content += f"| 1,000 orgs | {num_apps} | ~{execution_timing.get('projection_1000_orgs', 'N/A')} |\n"
                md_content += f"| 3,000 orgs | {num_apps} | ~{execution_timing.get('projection_3000_orgs', 'N/A')} |\n"
                md_content += f"\n> [TIP] **Tip:** Use `--parallel --workers N` to significantly reduce processing time.\n"

            md_content += f"\n> **Note:** Projections assume similar network conditions and API response times.\n"

            # Add API statistics section
            api_stats = execution_timing.get("api_stats", {})
            if api_stats:
                md_content += f"\n### API Call Statistics\n\n"
                md_content += "| Metric | Value |\n"
                md_content += "|--------|-------|\n"
                md_content += (
                    f"| Total API calls | {api_stats.get('total_calls', 0)} |\n"
                )
                md_content += (
                    f"| Unique endpoints | {api_stats.get('unique_endpoints', 0)} |\n"
                )

                md_content += f"\n**Endpoint Breakdown:**\n\n"
                md_content += "| Endpoint | Calls |\n"
                md_content += "|----------|-------|\n"
                for endpoint, count in sorted(api_stats.get("endpoints", {}).items()):
                    md_content += f"| `{endpoint}` | {count} |\n"

        # Add footer with JSON reference
        md_content += f"\n---\n\n## Data Files\n\n"
        md_content += (
            f"- **JSON Output:** `{self.output_folder / Path(md_file).stem}.json`\n"
        )
        md_content += f"- **This Report:** `{md_file.name}`\n"

        # Write markdown file
        with open(md_file, "w") as f:
            f.write(md_content)

        logger.info(f"Markdown report saved to: {md_file.name}")

    def run(self) -> Dict[str, Any]:
        """
        Main execution method.

        1. Lists all organizations in the enterprise
        2. Installs the automation app(s) on each organization
        3. Saves results to JSON and Markdown
        """
        logger.info("=" * 60)
        logger.info(f"API-Based GitHub App {self.operation_name}er")
        logger.info(f"Enterprise: {self.enterprise}")
        logger.info(f"Operation: {self.operation_name}")
        if self.multi_app_mode:
            logger.info(f"Automation Apps ({len(self.automation_app_client_ids)}):")
            for app_id in self.automation_app_client_ids:
                logger.info(f"  - {app_id}")
        else:
            logger.info(
                f"Automation App Client ID: {self.automation_app_client_ids[0]}"
            )
        if not self.uninstall:
            logger.info(f"Repository Selection: {self.repository_selection}")
        logger.info(f"Mode: {'Parallel' if self.parallel else 'Sequential'}")
        logger.info(f"Dry Run: {self.dry_run}")
        logger.info("=" * 60)

        # Start execution timing
        self._execution_start_time = time.time()

        # Get list of organizations
        logger.info("Fetching enterprise organizations...")
        org_list_start = time.time()
        try:
            orgs = self.list_enterprise_orgs()
        except Exception as e:
            logger.error(f"Critical error while listing organizations: {e}")
            logger.warning("Continuing with empty organization list")
            orgs = []
        self._org_listing_duration = time.time() - org_list_start

        if not orgs:
            logger.warning("No organizations found in enterprise")
            logger.info("This could be due to:")
            logger.info("  - Empty enterprise")
            logger.info("  - Permission issues with the installer app")
            logger.info("  - Network connectivity problems")
            logger.info("  - Invalid enterprise slug")
            logger.info(
                "Consider creating outputs/organizations.csv manually with your organizations"
            )
            return self.get_summary()

        if orgs:
            logger.info(f"\nOrganizations to process ({len(orgs)}):")
            for org in orgs[:10]:
                name = org.get("login", org.get("name", "unknown"))
                logger.info(f"  - {name}")
            if len(orgs) > 10:
                logger.info(f"  ... and {len(orgs) - 10} more")
        else:
            logger.warning("No organizations to process - continuing with empty list")

        # Perform installations/uninstallations
        install_start = time.time()
        if orgs:  # Only process if we have organizations
            if self.parallel:
                self.install_parallel(orgs)
            else:
                self.install_sequential(orgs)
        else:
            logger.info(
                "Skipping installation/uninstallation - no organizations to process"
            )
        self._installation_duration = time.time() - install_start

        # End execution timing
        self._execution_end_time = time.time()

        # Save final results
        self.save_results()

        # Print summary
        summary = self.get_summary()
        logger.info("\n" + "=" * 60)
        logger.info(f"{self.operation_name} Complete!")
        logger.info(f"  {self.operation_name}ed: {summary['installed']}")
        logger.info(f"  Skipped: {summary['skipped']}")
        logger.info(f"  Failed: {summary['failed']}")
        logger.info(f"  Total: {summary['total']}")
        if self.multi_app_mode:
            logger.info(f"  Apps: {len(self.automation_app_client_ids)}")
        logger.info("=" * 60)

        # Log failed org-app combinations with error details
        if summary["failed"] > 0:
            logger.info("")
            logger.info("FAILED OPERATIONS SUMMARY")
            logger.info("-" * 40)
            if self.multi_app_mode:
                # Multi-app mode: failed_orgs is dict keyed by app_client_id
                for app_id, failed_list in self.failed_orgs.items():
                    if failed_list:
                        app_short = app_id[:15] + "..." if len(app_id) > 15 else app_id
                        for entry in failed_list:
                            org_name = entry.get("name", "Unknown")
                            reason = entry.get("reason", "Unknown error")
                            # Truncate long error messages for log readability
                            if len(reason) > 200:
                                reason = reason[:200] + "..."
                            logger.error(f"  [ERR] {org_name} [{app_short}]: {reason}")
            else:
                # Single-app mode: failed_orgs is a flat list
                for entry in self.failed_orgs:
                    org_name = entry.get("name", "Unknown")
                    reason = entry.get("reason", "Unknown error")
                    if len(reason) > 200:
                        reason = reason[:200] + "..."
                    logger.error(f"  [ERR] {org_name}: {reason}")
            logger.info("-" * 40)

        # Log execution timing summary
        if "execution_timing" in summary:
            timing = summary["execution_timing"]
            logger.info("\n" + "=" * 60)
            logger.info("EXECUTION TIMING SUMMARY")
            logger.info("=" * 60)
            logger.info(f"  Organization listing: {timing['org_listing_seconds']:.2f}s")
            logger.info(
                f"  {self.operation_name}ation time: {timing['installation_seconds']:.2f}s"
            )
            logger.info(
                f"  Total execution time: {timing['total_seconds']:.2f}s ({timing['total_formatted']})"
            )
            logger.info(
                f"  Est. API time per call: ~{timing['sequential_time_per_op']:.2f}s"
            )
            logger.info(f"  Throughput: {timing['throughput_ops_per_sec']:.2f} ops/sec")
            logger.info("")
            num_apps = len(self.automation_app_client_ids)
            workers = timing.get("workers", 1)
            if timing.get("mode") == "parallel":
                logger.info(f"PROJECTIONS (parallel with {workers} workers):")
                logger.info(
                    f"  100 orgs x {num_apps} apps: ~{timing['projection_100_orgs']} (sequential: ~{timing['projection_100_orgs_sequential']})"
                )
                logger.info(
                    f"  500 orgs x {num_apps} apps: ~{timing['projection_500_orgs']} (sequential: ~{timing['projection_500_orgs_sequential']})"
                )
                logger.info(
                    f"  1,000 orgs x {num_apps} apps: ~{timing['projection_1000_orgs']} (sequential: ~{timing['projection_1000_orgs_sequential']})"
                )
                logger.info(
                    f"  3,000 orgs x {num_apps} apps: ~{timing['projection_3000_orgs']} (sequential: ~{timing['projection_3000_orgs_sequential']})"
                )
            else:
                logger.info("PROJECTIONS (sequential mode):")
                logger.info(
                    f"  100 orgs x {num_apps} apps: ~{timing['projection_100_orgs']}"
                )
                logger.info(
                    f"  500 orgs x {num_apps} apps: ~{timing['projection_500_orgs']}"
                )
                logger.info(
                    f"  1,000 orgs x {num_apps} apps: ~{timing['projection_1000_orgs']}"
                )
                logger.info(
                    f"  3,000 orgs x {num_apps} apps: ~{timing['projection_3000_orgs']}"
                )
                logger.info("")
                logger.info(
                    "[TIP] Tip: Use --parallel --workers N for faster processing"
                )
            logger.info("=" * 60)

            # Log API statistics
            if "api_stats" in timing:
                api_stats = timing["api_stats"]
                logger.info("")
                logger.info("API CALL STATISTICS")
                logger.info("-" * 40)
                logger.info(f"  Total API calls: {api_stats['total_calls']}")
                logger.info(f"  Unique endpoints: {api_stats['unique_endpoints']}")
                logger.info("  Endpoint breakdown:")
                for endpoint, count in sorted(api_stats["endpoints"].items()):
                    logger.info(f"    - {endpoint}: {count}")
                logger.info("=" * 60)

        # Check if all failures are due to Forbidden errors (single-app mode only for simplicity)
        if not self.multi_app_mode and not self.uninstall:
            forbidden_count = sum(
                1 for org in self.failed_orgs if "Forbidden" in org.get("reason", "")
            )
            if forbidden_count > 0 and forbidden_count == len(self.failed_orgs):
                logger.info("")
                logger.warning("All installations failed with 'Forbidden' error.")
                logger.warning("This typically means the Installer App needs the")
                logger.warning(
                    "'Manage organization installations' enterprise permission."
                )
                logger.warning("")
                logger.warning("To fix this:")
                logger.warning(
                    f"  1. Go to: https://github.com/enterprises/{self.enterprise}/settings/apps"
                )
                logger.warning("  2. Find your Installer App")
                logger.warning(
                    "  3. Configure 'Enterprise permissions' > 'Organization installations' > 'Read and write'"
                )
                logger.warning("  4. Re-run this script")

        return summary

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of installation results."""
        if self.multi_app_mode:
            total_installed = sum(len(v) for v in self.installed_orgs.values())
            total_skipped = sum(len(v) for v in self.skipped_orgs.values())
            total_failed = sum(len(v) for v in self.failed_orgs.values())
        else:
            total_installed = len(self.installed_orgs)
            total_skipped = len(self.skipped_orgs)
            total_failed = len(self.failed_orgs)

        # Calculate execution timing if available
        execution_timing = None
        if self._execution_start_time and self._execution_end_time:
            total_seconds = self._execution_end_time - self._execution_start_time
            total_operations = len(self.results) if self.results else 1

            # Calculate the observed throughput rate (ops per second)
            # For parallel mode, this reflects the combined throughput of all workers
            throughput_rate = (
                total_operations / self._installation_duration
                if self._installation_duration > 0
                else 1
            )

            # Calculate estimated sequential time per operation
            # In parallel mode, we estimate this by multiplying the observed average by the effective parallelism
            workers = self.max_workers if self.parallel else 1
            if self.parallel and total_operations > 0:
                # Estimate sequential time: total_time * workers / operations (but capped by actual concurrency)
                effective_workers = min(workers, total_operations)
                sequential_time_per_op = (
                    self._installation_duration * effective_workers
                ) / total_operations
            else:
                sequential_time_per_op = (
                    self._installation_duration / total_operations
                    if total_operations > 0
                    else 0
                )

            # Observed average (wall-clock / operations) - reflects parallelism
            observed_avg_per_op = (
                self._installation_duration / total_operations
                if total_operations > 0
                else 0
            )

            # Format total time
            hours, remainder = divmod(int(total_seconds), 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours > 0:
                total_formatted = f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                total_formatted = f"{minutes}m {seconds}s"
            else:
                total_formatted = f"{total_seconds:.1f}s"

            # Helper function to format projections
            def format_projection(
                num_orgs: int,
                num_apps: int,
                seq_time_per_op: float,
                num_workers: int = 1,
            ) -> str:
                """Calculate projected time accounting for parallelism."""
                total_ops = num_orgs * num_apps
                # With parallel workers, we divide by worker count (but can't exceed ops count)
                effective_parallelism = min(num_workers, total_ops)
                projected_seconds = (
                    total_ops * seq_time_per_op
                ) / effective_parallelism
                h, rem = divmod(int(projected_seconds), 3600)
                m, s = divmod(rem, 60)
                if h > 0:
                    return f"{h}h {m}m {s}s"
                elif m > 0:
                    return f"{m}m {s}s"
                else:
                    return f"{projected_seconds:.1f}s"

            num_apps = len(self.automation_app_client_ids)

            execution_timing = {
                "org_listing_seconds": round(self._org_listing_duration, 3),
                "installation_seconds": round(self._installation_duration, 3),
                "total_seconds": round(total_seconds, 3),
                "total_formatted": total_formatted,
                "total_operations": total_operations,
                "sequential_time_per_op": round(sequential_time_per_op, 4),
                "observed_avg_per_op": round(observed_avg_per_op, 4),
                "throughput_ops_per_sec": round(throughput_rate, 3),
                "mode": "parallel" if self.parallel else "sequential",
                "workers": workers,
                # Projections use sequential time per op, then divide by workers
                "projection_100_orgs": format_projection(
                    100, num_apps, sequential_time_per_op, workers
                ),
                "projection_500_orgs": format_projection(
                    500, num_apps, sequential_time_per_op, workers
                ),
                "projection_1000_orgs": format_projection(
                    1000, num_apps, sequential_time_per_op, workers
                ),
                "projection_3000_orgs": format_projection(
                    3000, num_apps, sequential_time_per_op, workers
                ),
                # Also provide sequential projections for comparison
                "projection_100_orgs_sequential": format_projection(
                    100, num_apps, sequential_time_per_op, 1
                ),
                "projection_500_orgs_sequential": format_projection(
                    500, num_apps, sequential_time_per_op, 1
                ),
                "projection_1000_orgs_sequential": format_projection(
                    1000, num_apps, sequential_time_per_op, 1
                ),
                "projection_3000_orgs_sequential": format_projection(
                    3000, num_apps, sequential_time_per_op, 1
                ),
            }

        # Get API call statistics
        api_stats = self._get_api_stats()

        result = {
            "installed": total_installed,
            "skipped": total_skipped,
            "failed": total_failed,
            "total": len(self.results),
            "apps_count": len(self.automation_app_client_ids),
            "installed_orgs": self.installed_orgs,
            "skipped_orgs": self.skipped_orgs,
            "failed_orgs": self.failed_orgs,
            "api_stats": api_stats,
        }

        if execution_timing:
            execution_timing["api_stats"] = api_stats
            result["execution_timing"] = execution_timing

        return result


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Install or uninstall GitHub Apps across all organizations in an enterprise using API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Single app installation
    python install_github_all.py \\
        --enterprise my-enterprise \\
        --installer-app-id 12345 \\
        --installer-private-key /path/to/installer.pem \\
        --installer-install-id 67890 \\
        --automation-app-client-id Iv1.abc123

    # Multiple apps installation (comma-separated)
    python install_github_all.py \\
        --enterprise my-enterprise \\
        --installer-app-id 12345 \\
        --installer-private-key /path/to/installer.pem \\
        --installer-install-id 67890 \\
        --automation-app-client-ids Iv1.abc123,Iv1.def456,Iv1.ghi789

    # Parallel installation with custom output
    python install_github_all.py \\
        --enterprise my-enterprise \\
        --installer-app-id 12345 \\
        --installer-private-key /path/to/installer.pem \\
        --installer-install-id 67890 \\
        --automation-app-client-ids Iv1.abc123,Iv1.def456 \\
        --parallel --workers 10 --output-folder ./results

    # With .env file only (no command line args needed)
    python install_github_all.py --resume-from state
    
    # Dry run to preview
    python install_github_all.py \\
        --enterprise my-enterprise \\
        --installer-app-id 12345 \\
        --installer-private-key /path/to/installer.pem \\
        --installer-install-id 67890 \\
        --automation-app-client-id Iv1.abc123 \\
        --dry-run
    
    # Single app UNINSTALL
    python install_github_all.py \\
        --enterprise my-enterprise \\
        --installer-app-id 12345 \\
        --installer-private-key /path/to/installer.pem \\
        --installer-install-id 67890 \\
        --automation-app-client-id Iv1.abc123 \\
        --automation-app-id 54321 \\
        --automation-app-private-key /path/to/automation.pem \\
        --uninstall

    # Multiple apps UNINSTALL (requires config file)
    python install_github_all.py \\
        --enterprise my-enterprise \\
        --installer-app-id 12345 \\
        --installer-private-key /path/to/installer.pem \\
        --installer-install-id 67890 \\
        --automation-app-client-ids Iv1.abc123,Iv1.def456 \\
        --automation-apps-config /path/to/apps_config.json \\
        --uninstall

    # apps_config.json format:
    # {
    #   "Iv1.abc123": {"app_id": "54321", "private_key": "/path/to/app1.pem"},
    #   "Iv1.def456": {"app_id": "54322", "private_key": "/path/to/app2.pem"}
    # }

Setup:
    This script requires two enterprise-owned GitHub Apps:
    
    1. INSTALLER APP - Has permission to install apps in organizations
       - Create at: Enterprise Settings > GitHub Apps > New GitHub App
       - Required permission: "Enterprise organization installations" (read/write)
       - Install on the enterprise account
       - Note the App ID, Installation ID, and download private key
    
    2. AUTOMATION APP(S) - The app(s) you want installed everywhere
       - Create with whatever permissions your automation needs
       - Note the Client ID (starts with "Iv1.")
       - You can install multiple apps in one run using --automation-app-client-ids

Documentation:
    https://docs.github.com/en/enterprise-cloud@latest/admin/managing-github-apps-for-your-enterprise/automate-installations
        """,
    )

    # Required arguments - can be overridden by environment variables
    parser.add_argument(
        "--enterprise",
        "-e",
        default=os.getenv("GH_ENTERPRISE_SLUG"),
        help="GitHub Enterprise slug (e.g., 'my-enterprise'). Env: GH_ENTERPRISE_SLUG",
    )

    parser.add_argument(
        "--installer-app-id",
        default=os.getenv("INSTALLER_APP_ID"),
        help="App ID of the installer app. Env: INSTALLER_APP_ID",
    )

    parser.add_argument(
        "--installer-private-key",
        default=os.getenv("INSTALLER_PRIVATE_KEY"),
        help="Path to the installer app's private key (.pem file). Env: INSTALLER_PRIVATE_KEY",
    )

    parser.add_argument(
        "--installer-install-id",
        default=os.getenv("INSTALLER_INSTALL_ID"),
        help="Installation ID of the installer app on the enterprise. Env: INSTALLER_INSTALL_ID",
    )

    # App client ID arguments - one of these is required (can use env vars)
    app_group = parser.add_mutually_exclusive_group(required=False)
    app_group.add_argument(
        "--automation-app-client-id",
        default=os.getenv("AUTOMATION_APP_CLIENT_ID"),
        help="Client ID of a single automation app to install. Env: AUTOMATION_APP_CLIENT_ID",
    )
    app_group.add_argument(
        "--automation-app-client-ids",
        default=os.getenv("AUTOMATION_APP_CLIENT_IDS"),
        help="Comma-separated list of Client IDs for multiple apps. Env: AUTOMATION_APP_CLIENT_IDS",
    )

    # Optional arguments
    parser.add_argument(
        "--repository-selection",
        choices=["all", "selected"],
        default="all",
        help="Repository selection for the app installation (default: all)",
    )

    parser.add_argument(
        "--output-folder",
        "-o",
        default="outputs",
        help="Output folder for results (default: outputs)",
    )

    parser.add_argument(
        "--parallel",
        "-p",
        action="store_true",
        help="Enable parallel processing for faster installation",
    )

    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=5,
        help="Number of parallel workers (default: 5)",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of org-app installations per batch for large enterprises (default: 100). "
        "Lower values use less memory but require more batches.",
    )

    parser.add_argument(
        "--rate-limit-delay",
        type=float,
        default=0.0,
        help="Minimum delay in seconds between API calls (default: auto-calculated based on rate limits). "
        "Use this to slow down requests for very large enterprises.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Uninstall apps from organizations instead of installing. "
        "Requires --automation-app-id and --automation-app-private-key for each app.",
    )

    parser.add_argument(
        "--automation-app-id",
        help="App ID of the automation app (required for uninstall mode with single app). "
        "This is the numeric App ID, not the Client ID.",
    )

    parser.add_argument(
        "--automation-app-private-key",
        help="Path to the private key file for the automation app (required for uninstall mode). "
        "The app must authenticate as itself to uninstall.",
    )

    parser.add_argument(
        "--automation-apps-config",
        default=os.getenv("AUTOMATION_APPS_CONFIG"),
        help="Path to a JSON file mapping Client IDs to their App IDs and private key paths. "
        "Required for uninstall mode with multiple apps. Env: AUTOMATION_APPS_CONFIG. Format: "
        '{"CLIENT_ID": {"app_id": "APP_ID", "private_key": "/path/to/key.pem"}, ...}',
    )

    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    parser.add_argument(
        "--base-url",
        default="https://api.github.com",
        help="GitHub API base URL (default: https://api.github.com)",
    )

    parser.add_argument(
        "--export-orgs-csv",
        action="store_true",
        help="Export discovered organizations to CSV file for review and selection. "
        "Automatically enabled when discovering organizations via API.",
    )

    parser.add_argument(
        "--resume-from",
        help="Resume from a previous run. Use 'state' or 'auto' to use the enterprise state file "
        "(data/enterprise_apps_state_{enterprise}.json), or provide a path to a previous output file. "
        "Already completed org-app combinations will be skipped.",
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    # Re-check environment variables in case .env was loaded after arg parsing
    if not args.enterprise:
        args.enterprise = os.getenv("GH_ENTERPRISE_SLUG")
    if not args.installer_app_id:
        args.installer_app_id = os.getenv("INSTALLER_APP_ID")
    if not args.installer_private_key:
        args.installer_private_key = os.getenv("INSTALLER_PRIVATE_KEY")
    if not args.installer_install_id:
        args.installer_install_id = os.getenv("INSTALLER_INSTALL_ID")
    if not args.automation_app_client_id:
        args.automation_app_client_id = os.getenv("AUTOMATION_APP_CLIENT_ID")
    if not args.automation_app_client_ids:
        args.automation_app_client_ids = os.getenv("AUTOMATION_APP_CLIENT_IDS")

    # Validate required parameters (either from args or environment)
    missing = []
    if not args.enterprise:
        missing.append("--enterprise or GH_ENTERPRISE_SLUG env var")
    if not args.installer_app_id:
        missing.append("--installer-app-id or INSTALLER_APP_ID env var")
    if not args.installer_private_key:
        missing.append("--installer-private-key or INSTALLER_PRIVATE_KEY env var")
    if not args.installer_install_id:
        missing.append("--installer-install-id or INSTALLER_INSTALL_ID env var")
    if not args.automation_app_client_id and not args.automation_app_client_ids:
        missing.append(
            "--automation-app-client-id/--automation-app-client-ids or AUTOMATION_APP_CLIENT_ID/AUTOMATION_APP_CLIENT_IDS env var"
        )

    if missing:
        logger.error("Missing required parameters:")
        for m in missing:
            logger.error(f"  - {m}")
        logger.info("Tip: Set these in .env file or pass as command-line arguments")
        logger.info("Example .env file:")
        logger.info("  GH_ENTERPRISE_SLUG=my-enterprise")
        logger.info("  INSTALLER_APP_ID=12345")
        logger.info("  INSTALLER_PRIVATE_KEY=/path/to/installer.pem")
        logger.info("  INSTALLER_INSTALL_ID=67890")
        logger.info("  AUTOMATION_APP_CLIENT_ID=Iv1.abc123")
        sys.exit(1)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")
        logger.debug(
            f"Using environment variables from: {_env_file or 'system environment'}"
        )
        logger.debug(f"Enterprise: {args.enterprise}")
        logger.debug(f"Installer App ID: {args.installer_app_id}")
        logger.debug(f"Installer Install ID: {args.installer_install_id}")
        logger.debug(f"Automation App Client ID: {args.automation_app_client_id}")
        logger.debug(f"Resume from: {args.resume_from}")

    # Setup file logging
    log_file = setup_file_logging(args.enterprise)

    # Log if .env file was loaded
    if _env_file:
        logger.info(f"Loaded environment from: {_env_file}")

    # Parse automation app client IDs
    if args.automation_app_client_ids:
        # Multiple apps: parse comma-separated list
        app_client_ids = [
            app_id.strip()
            for app_id in args.automation_app_client_ids.split(",")
            if app_id.strip()
        ]
        if not app_client_ids:
            logger.error(
                "No valid app client IDs provided in --automation-app-client-ids"
            )
            sys.exit(1)
        mode_str = "uninstalling" if args.uninstall else "installing"
        logger.info(
            f"Multi-app mode: {mode_str.capitalize()} {len(app_client_ids)} apps"
        )
    else:
        # Single app
        app_client_ids = [args.automation_app_client_id]

    # Build automation app auth dictionary for uninstall mode
    automation_app_auth: Optional[Dict[str, GitHubAppAuth]] = None

    if args.uninstall:
        automation_app_auth = {}

        if (
            len(app_client_ids) == 1
            and args.automation_app_id
            and args.automation_app_private_key
        ):
            # Single app uninstall mode
            client_id = app_client_ids[0]
            automation_app_auth[client_id] = GitHubAppAuth(
                app_id=args.automation_app_id,
                private_key_path=args.automation_app_private_key,
                base_url=args.base_url,
            )
            logger.info(f"Uninstall mode: Configured auth for app {client_id}")

        elif args.automation_apps_config:
            # Multi-app uninstall mode with config file
            try:
                with open(args.automation_apps_config, "r") as f:
                    apps_config = json.load(f)

                for client_id in app_client_ids:
                    if client_id not in apps_config:
                        logger.error(
                            f"Missing config for app {client_id} in --automation-apps-config"
                        )
                        sys.exit(1)

                    app_config = apps_config[client_id]
                    if "app_id" not in app_config or "private_key" not in app_config:
                        logger.error(
                            f"Config for {client_id} must have 'app_id' and 'private_key'"
                        )
                        sys.exit(1)

                    automation_app_auth[client_id] = GitHubAppAuth(
                        app_id=app_config["app_id"],
                        private_key_path=app_config["private_key"],
                        base_url=args.base_url,
                    )

                logger.info(
                    f"Uninstall mode: Loaded config for {len(automation_app_auth)} apps"
                )

            except FileNotFoundError:
                logger.error(f"Config file not found: {args.automation_apps_config}")
                sys.exit(1)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in config file: {e}")
                sys.exit(1)
        else:
            logger.error(
                "Uninstall mode requires either:\n"
                "  - Single app: --automation-app-id and --automation-app-private-key\n"
                "  - Multiple apps: --automation-apps-config"
            )
            sys.exit(1)

    try:
        # Initialize authentication
        installer_auth = GitHubAppAuth(
            app_id=args.installer_app_id,
            private_key_path=args.installer_private_key,
            base_url=args.base_url,
        )

        # Initialize installer
        installer = EnterpriseAppInstaller(
            enterprise=args.enterprise,
            installer_auth=installer_auth,
            installer_install_id=args.installer_install_id,
            automation_app_client_ids=app_client_ids,
            repository_selection=args.repository_selection,
            base_url=args.base_url,
            output_folder=args.output_folder,
            parallel=args.parallel,
            max_workers=args.workers,
            dry_run=args.dry_run,
            resume_from=args.resume_from,
            batch_size=args.batch_size,
            rate_limit_delay=args.rate_limit_delay,
            uninstall=args.uninstall,
            automation_app_auth=automation_app_auth,
        )

        # Log large enterprise mode settings
        total_orgs_estimate = "unknown"  # Will be known after listing
        if args.batch_size != 100 or args.rate_limit_delay > 0:
            logger.info("Large enterprise settings:")
            logger.info(f"  Batch size: {args.batch_size}")
            logger.info(f"  Rate limit delay: {args.rate_limit_delay}s")

        # Run installation/uninstallation
        summary = installer.run()

        # Exit with error code if any installations failed
        if summary["failed"] > 0:
            sys.exit(1)

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("\nInstallation interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Installation failed: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
