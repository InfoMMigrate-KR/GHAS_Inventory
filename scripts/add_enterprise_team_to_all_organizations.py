#!/usr/bin/env python3
"""
Fetch all organizations from a GitHub Enterprise using GraphQL API,
then add the enterprise security team to each organization.
"""

import os
import sys
import json
from typing import List, Dict, Any
import requests

# GitHub GraphQL API endpoint
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

# GraphQL query to fetch organizations from enterprise
QUERY = """
query listOrgInEnterprise($enterprise_slug: String!, $after: String) {
  enterprise(slug: $enterprise_slug) {
    organizations(first: 100, after: $after) {
      nodes {
        login
        id
        name
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""


def get_github_token() -> str:
    """
    Get GitHub token from environment variable.
    
    Returns:
        str: GitHub personal access token
        
    Raises:
        ValueError: If GITHUB_TOKEN environment variable is not set
    """
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError(
            "GITHUB_TOKEN environment variable not set. "
            "Please set it with a valid GitHub personal access token."
        )
    return token


def fetch_enterprise_organizations(enterprise_slug: str) -> List[Dict[str, Any]]:
    """
    Fetch all organizations from a GitHub Enterprise with pagination.
    
    Args:
        enterprise_slug (str): The slug of the enterprise
        
    Returns:
        List[Dict[str, Any]]: List of organization objects containing login, id, and name
        
    Raises:
        requests.RequestException: If the API request fails
        ValueError: If the response contains errors
    """
    token = get_github_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    
    organizations = []
    after_cursor = None
    
    while True:
        variables = {
            "enterprise_slug": enterprise_slug,
            "after": after_cursor,
        }
        
        payload = {
            "query": QUERY,
            "variables": variables,
        }
        
        print(f"Fetching organizations (after: {after_cursor or 'start'})...")
        
        response = requests.post(
            GITHUB_GRAPHQL_URL,
            json=payload,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        
        data = response.json()
        
        # Check for GraphQL errors
        if "errors" in data:
            error_messages = [error.get("message", str(error)) for error in data["errors"]]
            raise ValueError(f"GraphQL errors: {', '.join(error_messages)}")
        
        # Extract organizations
        enterprise = data.get("data", {}).get("enterprise")
        if not enterprise:
            raise ValueError("Enterprise not found or not accessible")
        
        org_data = enterprise.get("organizations", {})
        nodes = org_data.get("nodes", [])
        organizations.extend(nodes)
        
        print(f"  Fetched {len(nodes)} organizations")
        
        # Check if there are more pages
        page_info = org_data.get("pageInfo", {})
        if not page_info.get("hasNextPage", False):
            break
        
        after_cursor = page_info.get("endCursor")
    
    return organizations


def add_security_team_to_org(org_login: str, token: str) -> Dict[str, Any]:
    """
    Add the enterprise security team to an organization.
    
    This associates the 'ent:security-maannngers' team (ID: 8134) with the organization,
    giving the security team organization-level access.
    
    Args:
        org_login (str): The organization login/slug
        token (str): GitHub API token
        
    Returns:
        Dict[str, Any]: Result of the operation (success/error status)
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    
    url = f"https://api.github.com/orgs/{org_login}/organization-roles/teams/ent:security-maannngers/8134"
    
    print(f"  Adding security team to org: {org_login}")
    
    try:
        response = requests.put(
            url,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        return {"status": "success", "org_login": org_login}
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return {"status": "not_found", "org_login": org_login}
        return {"status": "error", "code": e.response.status_code, "org_login": org_login, "message": e.response.text}
    except Exception as e:
        return {"status": "error", "message": str(e), "org_login": org_login}


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python fetch_enterprise_orgs.py <enterprise_slug>")
        print("\nExample: python fetch_enterprise_orgs.py my-enterprise")
        sys.exit(1)
    
    enterprise_slug = sys.argv[1]
    
    try:
        print(f"Fetching organizations from enterprise: {enterprise_slug}\n")
        organizations = fetch_enterprise_organizations(enterprise_slug)
        
        print(f"\nTotal organizations found: {len(organizations)}\n")
        print("Organizations:")
        print(json.dumps(organizations, indent=2))
        
        # Add security team to each organization
        print(f"\n{'='*60}")
        print("Adding enterprise security team to each organization...")
        print(f"{'='*60}\n")
        
        token = get_github_token()
        add_security_team_results = {}
        for org in organizations:
            org_login = org.get("login")
            if org_login:
                result = add_security_team_to_org(org_login, token)
                add_security_team_results[org_login] = result
        
        print(f"\nSecurity team addition results:")
        print(json.dumps(add_security_team_results, indent=2))
        
        return 0
        
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except requests.RequestException as e:
        print(f"Request error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
