#!/usr/bin/env python3

"""
GitHub App Authentication Module

This module provides a reusable GitHubAppAuth class for authenticating with GitHub
using GitHub App credentials instead of Personal Access Tokens (PATs).

Features:
- JWT token generation for GitHub App authentication
- Installation ID management for organizations
- Automatic access token generation and refresh
- Session management with proper headers
- Rate limiting and error handling

Usage:
    from github_auth import GitHubAppAuth

    auth = GitHubAppAuth(
        app_id="your_app_id",
        private_key_path="path/to/private/key.pem",
        verify_ssl=True
    )

    # Set up authentication for an organization
    if auth.authenticate_for_organization("your-org"):
        session = auth.get_authenticated_session()
        # Use session for API calls
"""

import os
import jwt
import time
import requests
import urllib3
from datetime import datetime, timedelta
from typing import Optional, Dict
from dotenv import load_dotenv

# Disable SSL warnings for corporate environments
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class GitHubAppAuth:
    """
    GitHub App Authentication handler

    This class manages GitHub App authentication including JWT generation,
    installation token management, and session handling.
    """

    def __init__(
        self,
        app_id: str = None,
        private_key_path: str = None,
        verify_ssl: bool = True,
        base_url: str = "https://api.github.com",
    ):
        """
        Initialize the GitHub App Authentication handler

        Args:
            app_id: The GitHub App ID (can be loaded from environment)
            private_key_path: Path to the GitHub App's private key file
            verify_ssl: Whether to verify SSL certificates
            base_url: GitHub API base URL
        """
        load_dotenv()

        self.app_id = app_id or os.getenv("GH_APP_ID")

        # Get private key content directly from environment variable
        self.private_key_content = os.getenv("GH_PRIVATE_KEY")

        if not self.private_key_content:
            # If not in environment, check if a file path was passed as parameter
            if private_key_path and os.path.exists(private_key_path):
                with open(private_key_path, "r") as f:
                    self.private_key_content = f.read()
            else:
                self.private_key_content = None

        self.verify_ssl = (
            verify_ssl
            if verify_ssl is not None
            else os.getenv("VERIFY_SSL", "true").lower() == "true"
        )

        self.base_url = base_url

        self.installation_id = None
        self.access_token = None
        self.token_expires_at = None
        self.session = requests.Session()

        # Set SSL verification
        self.session.verify = self.verify_ssl

        # Validate required credentials
        self._validate_credentials()

    def _validate_credentials(self):
        """Validate that required credentials are available"""
        if not self.app_id:
            raise ValueError(
                "GitHub App ID is required. Set GH_APP_ID environment variable "
                "or pass app_id parameter"
            )

        if not self.private_key_content:
            raise ValueError(
                "GitHub App private key is required. Set GH_PRIVATE_KEY environment variable "
                "with the private key content, or pass private_key_path parameter"
            )

    def _generate_jwt(self) -> str:
        """
        Generate a JWT for GitHub App authentication

        Returns:
            str: JWT token for authenticating as GitHub App
        """
        try:
            # Use private key content directly from environment variable
            private_key = self.private_key_content.encode("utf-8")

            now = datetime.utcnow()
            payload = {
                "iat": now,
                "exp": now + timedelta(minutes=2),  # JWT expires in 2 minutes
                "iss": self.app_id,
            }

            return jwt.encode(payload, private_key, algorithm="RS256")

        except Exception as e:
            raise Exception(f"Failed to generate JWT: {e}")

    def get_installation_id(self, org_name: str) -> Optional[str]:
        """
        Get the installation ID for a specific organization

        Args:
            org_name: The organization name

        Returns:
            Optional[str]: Installation ID if found, None otherwise
        """
        jwt_token = self._generate_jwt()
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        try:
            # Try to get the installation for the organization directly
            response = requests.get(
                f"{self.base_url}/orgs/{org_name}/installation",
                headers=headers,
                verify=self.verify_ssl,
                timeout=30,
            )

            if response.status_code == 200:
                return str(response.json()["id"])

            # If org installation not found, list all installations
            response = requests.get(
                f"{self.base_url}/app/installations",
                headers=headers,
                verify=self.verify_ssl,
                timeout=30,
            )

            if response.status_code == 200:
                installations = response.json()
                for installation in installations:
                    if (
                        installation.get("account", {}).get("login", "").lower()
                        == org_name.lower()
                    ):
                        return str(installation["id"])

            print(
                f"Warning: No GitHub App installation found for organization: {org_name}"
            )
            return None

        except Exception as e:
            print(f"Error getting installation ID for {org_name}: {e}")
            return None

    def _get_installation_token(self) -> str:
        """
        Get an installation access token for the GitHub App

        Returns:
            str: Access token for the installation
        """
        if not self.installation_id:
            raise ValueError(
                "Installation ID is required. Call authenticate_for_organization first."
            )

        jwt_token = self._generate_jwt()
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        try:
            response = requests.post(
                f"{self.base_url}/app/installations/{self.installation_id}/access_tokens",
                headers=headers,
                verify=self.verify_ssl,
                timeout=30,
            )

            if response.status_code == 201:
                data = response.json()
                self.access_token = data["token"]
                # Convert expires_at string to datetime
                self.token_expires_at = datetime.strptime(
                    data["expires_at"], "%Y-%m-%dT%H:%M:%SZ"
                )
                return self.access_token
            else:
                raise Exception(
                    f"Failed to get installation token: {response.status_code} - {response.text}"
                )

        except Exception as e:
            raise Exception(f"Error getting installation token: {e}")

    def _refresh_token_if_needed(self):
        """Refresh the access token if it's expired or about to expire"""
        if (
            not self.access_token
            or not self.token_expires_at
            or datetime.utcnow() + timedelta(minutes=5) >= self.token_expires_at
        ):
            print("Refreshing access token...")
            self.access_token = self._get_installation_token()
            self._update_session_headers()

    def _update_session_headers(self):
        """Update session headers with current access token"""
        if not self.access_token:
            raise ValueError(
                "Access token is required. Call authenticate_for_organization first."
            )

        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/vnd.github.v3+json",
            }
        )

    def authenticate_for_organization(self, org_name: str) -> bool:
        """
        Authenticate for a specific organization

        Args:
            org_name: The organization name

        Returns:
            bool: True if authentication successful, False otherwise
        """
        try:
            print(f"Authenticating for organization: {org_name}")

            # Get installation ID
            installation_id = self.get_installation_id(org_name)
            if not installation_id:
                print(f"Failed to get installation ID for organization: {org_name}")
                return False

            self.installation_id = installation_id
            print(f"Found installation ID: {installation_id}")

            # Get access token
            self._get_installation_token()
            self._update_session_headers()

            print("Authentication successful!")
            return True

        except Exception as e:
            print(f"Authentication failed for organization {org_name}: {e}")
            return False

    def get_authenticated_session(self) -> requests.Session:
        """
        Get an authenticated requests session

        Returns:
            requests.Session: Session with proper authentication headers
        """
        if not self.access_token:
            raise ValueError(
                "Not authenticated. Call authenticate_for_organization first."
            )

        self._refresh_token_if_needed()
        return self.session

    def is_authenticated(self) -> bool:
        """
        Check if currently authenticated with a valid token

        Returns:
            bool: True if authenticated with valid token, False otherwise
        """
        return (
            self.access_token is not None
            and self.token_expires_at is not None
            and datetime.utcnow() < self.token_expires_at
        )

    def get_token_info(self) -> Dict:
        """
        Get information about the current token

        Returns:
            Dict: Token information including expiry time and remaining time
        """
        if not self.access_token:
            return {"authenticated": False}

        remaining_time = None
        if self.token_expires_at:
            remaining_time = (self.token_expires_at - datetime.utcnow()).total_seconds()

        return {
            "authenticated": True,
            "installation_id": self.installation_id,
            "expires_at": (
                self.token_expires_at.isoformat() if self.token_expires_at else None
            ),
            "remaining_seconds": max(0, remaining_time) if remaining_time else None,
            "needs_refresh": (
                remaining_time < 300 if remaining_time else True
            ),  # Refresh if < 5 minutes
        }
