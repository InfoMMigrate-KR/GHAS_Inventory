#!/usr/bin/env python3

"""
Set Organization Owner Script

This script sets a member user as owner of a GitHub organization using the
GitHub REST API endpoint for organization membership.

Usage:
    python set_org_owner.py --org <org-name> --username <username>
    
    or interactively:
    python set_org_owner.py

Requirements:
    - GitHub App with organization administration permissions
    - GH_APP_ID and GH_PRIVATE_KEY environment variables configured
    
API Reference:
    https://docs.github.com/en/enterprise-cloud@latest/rest/orgs/members?apiVersion=2022-11-28#set-organization-membership-for-a-user
"""

import sys
import os
import argparse
import logging
from datetime import datetime

# Add parent directory to path to import github_auth
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from github_auth import GitHubAppAuth


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def set_organization_owner(session, org_name: str, username: str) -> bool:
    """
    Set a user as owner (admin) of an organization.
    
    Args:
        session: Authenticated requests session
        org_name: Name of the organization
        username: GitHub username to set as owner
        
    Returns:
        bool: True if successful, False otherwise
    """
    url = f"https://api.github.com/orgs/{org_name}/memberships/{username}"
    
    # Set role to "admin" to make the user an owner
    payload = {
        "role": "admin"
    }
    
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    logger.info(f"Setting {username} as owner of {org_name}...")
    
    try:
        response = session.put(url, json=payload, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"✓ Successfully set {username} as owner of {org_name}")
            logger.info(f"  State: {data.get('state', 'N/A')}")
            logger.info(f"  Role: {data.get('role', 'N/A')}")
            return True
            
        elif response.status_code == 422:
            logger.error(f"✗ Validation failed. The user might not exist or already has pending invitation")
            logger.error(f"  Response: {response.json()}")
            return False
            
        elif response.status_code == 403:
            logger.error(f"✗ Forbidden. Check if the GitHub App has sufficient permissions")
            logger.error(f"  Response: {response.json()}")
            return False
            
        elif response.status_code == 404:
            logger.error(f"✗ Organization '{org_name}' or user '{username}' not found")
            return False
            
        else:
            logger.error(f"✗ Failed with status code: {response.status_code}")
            logger.error(f"  Response: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"✗ Error setting organization owner: {str(e)}")
        return False


def get_current_membership(session, org_name: str, username: str) -> dict:
    """
    Get the current membership status of a user in an organization.
    
    Args:
        session: Authenticated requests session
        org_name: Name of the organization
        username: GitHub username
        
    Returns:
        dict: Membership information or None if not found
    """
    url = f"https://api.github.com/orgs/{org_name}/memberships/{username}"
    
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    try:
        response = session.get(url, headers=headers)
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            logger.info(f"User {username} is not currently a member of {org_name}")
            return None
        else:
            logger.warning(f"Could not retrieve membership status: {response.status_code}")
            return None
            
    except Exception as e:
        logger.warning(f"Error retrieving membership status: {str(e)}")
        return None


def main():
    """Main function to execute the script."""
    parser = argparse.ArgumentParser(
        description="Set a user as owner (admin) of a GitHub organization"
    )
    parser.add_argument(
        "--org",
        help="GitHub organization name"
    )
    parser.add_argument(
        "--username",
        help="GitHub username to set as owner"
    )
    parser.add_argument(
        "--verify-ssl",
        action="store_true",
        default=True,
        help="Verify SSL certificates (default: True)"
    )
    parser.add_argument(
        "--no-verify-ssl",
        action="store_false",
        dest="verify_ssl",
        help="Disable SSL certificate verification"
    )
    
    args = parser.parse_args()
    
    # Get organization name
    org_name = args.org
    if not org_name:
        org_name = input("Enter the organization name: ").strip()
        if not org_name:
            logger.error("Organization name is required")
            sys.exit(1)
    
    # Get username
    username = args.username
    if not username:
        username = input("Enter the GitHub username to set as owner: ").strip()
        if not username:
            logger.error("Username is required")
            sys.exit(1)
    
    # Initialize authentication
    logger.info("Initializing GitHub App authentication...")
    auth = GitHubAppAuth(verify_ssl=args.verify_ssl)
    
    # Authenticate for the organization
    if not auth.authenticate_for_organization(org_name):
        logger.error(f"Failed to authenticate for organization: {org_name}")
        sys.exit(1)
    
    session = auth.get_authenticated_session()
    
    # Check current membership status
    logger.info(f"Checking current membership status for {username}...")
    current_membership = get_current_membership(session, org_name, username)
    
    if current_membership:
        current_role = current_membership.get('role', 'unknown')
        current_state = current_membership.get('state', 'unknown')
        logger.info(f"Current status - Role: {current_role}, State: {current_state}")
        
        if current_role == 'admin':
            logger.info(f"{username} is already an owner of {org_name}")
            response = input("Do you want to continue anyway? (y/n): ").strip().lower()
            if response != 'y':
                logger.info("Operation cancelled")
                sys.exit(0)
    
    # Set the user as owner
    success = set_organization_owner(session, org_name, username)
    
    if success:
        logger.info("✓ Operation completed successfully")
        sys.exit(0)
    else:
        logger.error("✗ Operation failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
