#!/usr/bin/env python3

"""
Set Organization Owner Script

This script sets member users as owners of GitHub organizations using the
GitHub REST API with Personal Access Token authentication.

Configuration:
    All settings are configured via .env file:

    # Personal Access Token (Required)
    GH_PATS=token1,token2,token3

    # CSV File Configuration
    USERS_CSV_PATH=scripts/output/users.csv
    ORGS_CSV_PATH=scripts/output/organizations.csv

    # Optional settings
    VERIFY_SSL=true
    MAX_WORKERS=5

CSV Format:
    users.csv:
    username,role,email
    john_doe,admin,john.doe@example.com
    jane_smith,member,jane.smith@example.com

    organizations.csv:
    automated-test-org-1
    byron-github-school
    cigbe-training-demo
    ...

Requirements:
    - Personal Access Token with admin:org scope
    - .env file with authentication configuration
    - Each user will be assigned to ALL organizations with their specified role

API References:
    - REST API: https://docs.github.com/en/enterprise-cloud@latest/rest/orgs/members
"""

import sys
import os
import logging
import csv
import json
import requests
import itertools
from datetime import datetime
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global round robin iterator for PAT tokens
pat_cycle = None

# Load environment variables from root directory
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
env_path = os.path.join(root_dir, ".env")

if os.path.exists(env_path):
    load_dotenv(env_path)
    logger.info(f"Loaded environment from: {env_path}")
else:
    logger.warning(f".env file not found at: {env_path}")


def validate_environment_config() -> bool:
    """Validate that required environment variables are set."""
    # Check if GH_PATS is set and contains valid tokens
    pat_tokens_str = os.getenv("GH_PATS")
    if not pat_tokens_str:
        logger.error("Missing required environment variable: GH_PATS")
        logger.error("Please check your .env file configuration")
        return False

    # Validate that we have at least one valid token
    pat_tokens = [token.strip() for token in pat_tokens_str.split(",") if token.strip()]
    if not pat_tokens:
        logger.error("No valid PAT tokens found in GH_PATS")
        logger.error("Please provide comma-separated tokens in GH_PATS")
        return False

    logger.info(f"Found {len(pat_tokens)} PAT tokens for round robin")

    # Validate CSV path
    csv_path = os.getenv("USERS_CSV_PATH")
    if csv_path:
        full_csv_path = os.path.join(root_dir, csv_path)
        if not os.path.exists(full_csv_path):
            logger.error(f"CSV file not found: {full_csv_path}")
            return False

    return True


def get_env_config() -> Dict[str, any]:
    """Get configuration from environment variables."""
    # Parse comma-separated PATs for round robin
    pat_tokens_str = os.getenv("GH_PATS", "")
    pat_tokens = [token.strip() for token in pat_tokens_str.split(",") if token.strip()]

    return {
        "csv_path": os.path.join(
            root_dir, os.getenv("USERS_CSV_PATH", "scripts/output/users.csv")
        ),
        "orgs_csv_path": os.path.join(
            root_dir, os.getenv("ORGS_CSV_PATH", "scripts/output/organizations.csv")
        ),
        "pat_tokens": pat_tokens,
        "verify_ssl": os.getenv("VERIFY_SSL", "true").lower() in ("true", "1", "yes"),
        "max_workers": int(os.getenv("MAX_WORKERS", "5")),
    }


def create_pat_session() -> requests.Session:
    """Create authenticated session using Personal Access Token with round robin."""
    global pat_cycle
    config = get_env_config()

    if not config["pat_tokens"]:
        raise ValueError("No PAT tokens found in GH_PATS environment variable")

    # Initialize round robin cycle if not already done
    if pat_cycle is None:
        pat_cycle = itertools.cycle(config["pat_tokens"])
        logger.info(
            f"Initialized round robin with {len(config['pat_tokens'])} PAT tokens"
        )

    # Get next token in round robin
    current_token = next(pat_cycle)

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"token {current_token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "GitHub-Org-Owner-Script/1.0",
        }
    )
    session.verify = config["verify_ssl"]

    logger.info(f"Created PAT authenticated session (token: ...{current_token[-4:]})")
    return session


def set_organization_owner(
    session: requests.Session, org_name: str, username: str, role: str = "admin"
) -> bool:
    """
    Set a user as an organization owner using REST API.

    Args:
        session: Authenticated requests session
        org_name: Organization name
        username: Username to set as owner
        role: Role to assign (admin or member)

    Returns:
        bool: True if successful, False otherwise
    """
    # GitHub REST API endpoint for organization membership
    url = f"https://api.github.com/orgs/{org_name}/memberships/{username}"

    payload = {"role": role}

    try:
        response = session.put(url, json=payload)

        if response.status_code == 200:
            logger.info(f"✓ Successfully set {username} as {role} in {org_name}")
            return True
        elif response.status_code == 422:
            error_data = response.json()
            error_message = error_data.get("message", "Unknown error")
            logger.error(
                f"✗ Failed to set {username} as {role} in {org_name}: {error_message}"
            )
            return False
        elif response.status_code == 404:
            logger.error(f"✗ Organization '{org_name}' or user '{username}' not found")
            return False
        elif response.status_code == 403:
            logger.error(
                f"✗ Insufficient permissions to modify {org_name} organization"
            )
            return False
        else:
            logger.error(
                f"✗ Unexpected response {response.status_code} for {username} in {org_name}: {response.text}"
            )
            return False

    except requests.exceptions.RequestException as e:
        logger.error(
            f"✗ Network error setting {username} as {role} in {org_name}: {str(e)}"
        )
        return False


def read_users_csv(csv_path: str) -> List[Dict[str, str]]:
    """
    Read users from CSV file.

    Args:
        csv_path: Path to CSV file

    Returns:
        List of user dictionaries
    """
    users = []

    if not os.path.exists(csv_path):
        logger.error(f"CSV file not found: {csv_path}")
        return users

    try:
        with open(csv_path, "r", encoding="utf-8") as csvfile:
            # Auto-detect delimiter
            sample = csvfile.read(1024)
            csvfile.seek(0)
            delimiter = "," if "," in sample else ";"

            reader = csv.DictReader(csvfile, delimiter=delimiter)

            for row_num, row in enumerate(reader, start=2):
                # Clean whitespace from values
                row = {k.strip(): v.strip() for k, v in row.items()}

                # Validate required fields
                required_fields = ["username"]
                missing_fields = [
                    field for field in required_fields if not row.get(field)
                ]

                if missing_fields:
                    logger.warning(
                        f"Row {row_num}: Missing required fields: {missing_fields}. Skipping."
                    )
                    continue

                # Set default role if not provided
                if not row.get("role"):
                    row["role"] = "member"

                # Validate role
                if row["role"] not in ["admin", "member"]:
                    logger.warning(
                        f"Row {row_num}: Invalid role '{row['role']}'. Using 'member' instead."
                    )
                    row["role"] = "member"

                # Only keep username and role
                users.append(
                    {
                        "username": row["username"],
                        "role": row["role"],
                        "email": row.get("email", ""),
                    }
                )

        logger.info(f"Successfully read {len(users)} users from CSV file")

    except Exception as e:
        logger.error(f"Error reading CSV file: {str(e)}")

    return users


def read_organizations_csv(csv_path: str) -> List[str]:
    """
    Read organizations from CSV file.

    Args:
        csv_path: Path to CSV file

    Returns:
        List of organization names
    """
    organizations = []

    if not os.path.exists(csv_path):
        logger.error(f"Organizations CSV file not found: {csv_path}")
        return organizations

    try:
        with open(csv_path, "r", encoding="utf-8") as csvfile:
            # Check if file has headers
            first_line = csvfile.readline().strip()
            csvfile.seek(0)

            # Skip header if it looks like a header
            if first_line.lower() in ["login", "organization", "org", "name"]:
                next(csvfile)

            for line_num, line in enumerate(csvfile, start=1):
                org_name = line.strip()
                if org_name and not org_name.startswith("#"):
                    organizations.append(org_name)

        logger.info(
            f"Successfully read {len(organizations)} organizations from CSV file"
        )

    except Exception as e:
        logger.error(f"Error reading organizations CSV file: {str(e)}")

    return organizations


def create_user_org_assignments(
    users: List[Dict[str, str]], organizations: List[str]
) -> List[Dict[str, str]]:
    """
    Create all user-organization assignment combinations.

    Args:
        users: List of user dictionaries
        organizations: List of organization names

    Returns:
        List of assignment dictionaries
    """
    assignments = []

    for user in users:
        for org in organizations:
            assignment = {
                "username": user["username"],
                "organization": org,
                "role": user["role"],
                "email": user.get("email", ""),
            }
            assignments.append(assignment)

    logger.info(
        f"Created {len(assignments)} user-organization assignments ({len(users)} users × {len(organizations)} orgs)"
    )
    return assignments


def process_user_assignment(
    session: requests.Session, user: Dict[str, str]
) -> Dict[str, any]:
    """
    Process a single user assignment.

    Args:
        session: Authenticated requests session
        user: User data dictionary

    Returns:
        Dictionary with result data
    """
    username = user["username"]
    organization = user["organization"]
    role = user.get("role", "member")

    logger.info(f"Processing: {username} -> {organization} (role: {role})")

    try:
        success = set_organization_owner(session, organization, username, role)

        result = {
            "username": username,
            "organization": organization,
            "role": role,
            "success": success,
            "timestamp": datetime.now().isoformat(),
        }

        if not success:
            result["error"] = "Failed to set organization membership"

        return result

    except Exception as e:
        logger.error(f"Error processing {username} -> {organization}: {str(e)}")
        return {
            "username": username,
            "organization": organization,
            "role": role,
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }


def process_bulk_assignments(
    users: List[Dict[str, str]], max_workers: int = 5
) -> List[Dict[str, any]]:
    """
    Process multiple user assignments in parallel using round robin PAT tokens.

    Args:
        users: List of user data dictionaries
        max_workers: Maximum number of concurrent workers

    Returns:
        List of result dictionaries
    """
    results = []

    try:
        config = get_env_config()
        logger.info(
            f"Using Personal Access Token authentication with {len(config['pat_tokens'])} tokens (round robin)"
        )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_user = {}

            for user in users:
                # Create a new session for each user (round robin)
                session = create_pat_session()
                future = executor.submit(process_user_assignment, session, user)
                future_to_user[future] = user

            for future in as_completed(future_to_user):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    user = future_to_user[future]
                    logger.error(f"Task failed for {user['username']}: {str(e)}")
                    results.append(
                        {
                            "username": user["username"],
                            "organization": user["organization"],
                            "success": False,
                            "error": str(e),
                            "timestamp": datetime.now().isoformat(),
                        }
                    )

    except Exception as e:
        logger.error(f"Failed to process assignments: {str(e)}")
        for user in users:
            results.append(
                {
                    "username": user["username"],
                    "organization": user["organization"],
                    "success": False,
                    "error": "PAT authentication failed",
                    "timestamp": datetime.now().isoformat(),
                }
            )

    return results


def main():
    """Main function to execute the script."""
    # Validate environment configuration
    if not validate_environment_config():
        logger.error("Environment configuration validation failed")
        sys.exit(1)

    # Get configuration from .env file
    config = get_env_config()

    logger.info("Starting organization owner assignment script")
    logger.info(f"Reading users from: {config['csv_path']}")
    logger.info(f"Reading organizations from: {config['orgs_csv_path']}")
    logger.info("Using Personal Access Token (PAT) authentication")

    # Read users from CSV
    users = read_users_csv(config["csv_path"])
    if not users:
        logger.error("No valid users found in CSV file")
        sys.exit(1)

    # Read organizations from CSV
    organizations = read_organizations_csv(config["orgs_csv_path"])
    if not organizations:
        logger.error("No valid organizations found in CSV file")
        sys.exit(1)

    logger.info(f"Found {len(users)} users and {len(organizations)} organizations")

    # Create all user-organization assignments
    assignments = create_user_org_assignments(users, organizations)

    logger.info(f"Processing {len(assignments)} total assignments")

    # Process bulk assignments
    results = process_bulk_assignments(assignments, config["max_workers"])

    # Summary report
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    logger.info(f"\n=== BULK ASSIGNMENT SUMMARY ===")
    logger.info(f"Total assignments processed: {len(results)}")
    logger.info(f"Successful: {len(successful)}")
    logger.info(f"Failed: {len(failed)}")

    if failed:
        logger.error("\nFailed assignments:")
        for fail in failed[:10]:  # Show first 10 failures
            logger.error(
                f"  {fail['username']} -> {fail['organization']}: {fail.get('error', 'Unknown error')}"
            )
        if len(failed) > 10:
            logger.error(f"  ... and {len(failed) - 10} more failures")

    if successful:
        logger.info("\nSuccessful assignments:")
        for success in successful[:10]:  # Show first 10 successes
            logger.info(
                f"  ✓ {success['username']} -> {success['organization']} ({success['role']})"
            )
        if len(successful) > 10:
            logger.info(f"  ... and {len(successful) - 10} more successful assignments")

    # Save detailed results to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = f"org_owner_results_{timestamp}.json"

    try:
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2)
        logger.info(f"\nDetailed results saved to: {results_file}")
    except Exception as e:
        logger.warning(f"Could not save results file: {str(e)}")

    sys.exit(0 if len(failed) == 0 else 1)


if __name__ == "__main__":
    main()
