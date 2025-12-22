import os
import sys
import time
import requests
import itertools
import csv
from datetime import datetime
from dotenv import load_dotenv

# Add the parent directory to the path to import github_auth
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from github_auth.github_app_auth import GitHubAppAuth

# Load environment variables
load_dotenv()

# GraphQL Query
ORG_QUERY = """
query($slug: String!, $cursor: String) {
  enterprise(slug: $slug) {
    name
    organizations(first: 100, after: $cursor) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        login       
      }
    }
  }
}
"""


class EnterpriseFetcher:
    def __init__(self):
        self.api_url = "https://api.github.com/graphql"
        self.slug = os.getenv("GH_ENTERPRISE_SLUG")

        if not self.slug:
            raise ValueError("Missing GH_ENTERPRISE_SLUG in .env file")

        # Initialize GitHub App Authentication
        self.github_app = GitHubAppAuth()
        self.authenticated_orgs = set()

        print(f"[*] Initialized GitHub App authentication for Enterprise: {self.slug}")

    def _ensure_authentication(self, org_login):
        """
        Ensure we have a valid authentication session for the given organization.
        """
        if org_login not in self.authenticated_orgs:
            success = self.github_app.authenticate_for_organization(org_login)
            if not success:
                raise Exception(f"Failed to authenticate for organization: {org_login}")
            self.authenticated_orgs.add(org_login)

        return self.github_app.get_authenticated_session()

    def _get_headers(self):
        """Get headers for GraphQL requests"""
        return {
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        }

    def run_query(self, query, variables):
        """
        Executes GraphQL query with GitHub App authentication and retry logic.
        """
        max_retries = 3
        attempts = 0

        while attempts < max_retries:
            try:
                # Get authenticated session
                session = self.github_app.get_authenticated_session()

                response = session.post(
                    self.api_url,
                    json={"query": query, "variables": variables},
                    headers=self._get_headers(),
                    timeout=30,
                )

                # Handle HTTP errors
                if response.status_code in [401, 403]:
                    print(
                        f"[!] HTTP {response.status_code} encountered. Re-authenticating..."
                    )
                    # Clear authentication cache and retry
                    self.authenticated_orgs.clear()
                    attempts += 1
                    continue

                if response.status_code != 200:
                    raise Exception(
                        f"Query failed with code {response.status_code}: {response.text}"
                    )

                data = response.json()

                # Check for GraphQL specific errors
                if "errors" in data:
                    errors = data["errors"]
                    is_rate_limit = any(
                        e.get("type") == "RATE_LIMITED"
                        or "rate limit" in e.get("message", "").lower()
                        for e in errors
                    )

                    if is_rate_limit:
                        print("[!] GraphQL Rate Limit Hit. Waiting...")
                        time.sleep(60)  # Wait 1 minute for rate limit
                        attempts += 1
                        continue
                    else:
                        print(f"[!] GraphQL Errors: {errors}")
                        return data

                return data

            except requests.exceptions.RequestException as e:
                print(f"[!] Network error: {e}")
                attempts += 1
                time.sleep(2)

        raise Exception("Max retries exceeded. Authentication or API issues.")

    def get_first_accessible_org(self):
        """
        Get the first organization where the GitHub App is installed.
        This can be used to authenticate for enterprise queries.
        
        Returns:
            str: Organization login name, or None if none found
        """
        jwt_token = self.github_app._generate_jwt()
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        try:
            # List all installations for this GitHub App
            response = requests.get(
                f"{self.github_app.base_url}/app/installations",
                headers=headers,
                verify=self.github_app.verify_ssl,
                timeout=30,
            )

            if response.status_code == 200:
                installations = response.json()
                
                for installation in installations:
                    account = installation.get("account", {})
                    account_login = account.get("login")
                    
                    # Prefer Organization accounts, but accept User accounts too
                    if account_login:
                        print(f"[*] Using GitHub App installation: {account_login}")
                        return account_login
                
                print("[!] No valid GitHub App installations found with login names")
                return None
            else:
                print(f"[!] Failed to list installations: HTTP {response.status_code}")
                print(f"[!] Response: {response.text}")
                return None

        except Exception as e:
            print(f"[!] Error getting installations: {e}")
            import traceback
            traceback.print_exc()
            return None

    def fetch_all_organizations(self, initial_org: str = None):
        """
        Fetch all organizations from the enterprise.
        
        Args:
            initial_org: An organization to authenticate with. If not provided,
                        will try to auto-detect from GitHub App installations.
        """
        all_orgs = []
        has_next_page = True
        cursor = None

        print("[*] Starting fetch...")
        
        # Need to authenticate with at least one org to query enterprise
        auth_org = initial_org or os.getenv("GH_INITIAL_ORG")
        
        # If no org specified, try to auto-detect from GitHub App installations
        if not auth_org:
            print("[*] No initial organization specified, auto-detecting from GitHub App installations...")
            auth_org = self.get_first_accessible_org()
        
        if not auth_org:
            print("[!] Could not find an organization to authenticate with.")
            print("[!] Please either:")
            print("    1. Set GH_INITIAL_ORG in your .env file, OR")
            print("    2. Ensure the GitHub App is installed in at least one organization")
            return []
        
        print(f"[*] Authenticating with organization: {auth_org}")
        if not self.github_app.authenticate_for_organization(auth_org):
            print(f"[X] Failed to authenticate with organization: {auth_org}")
            print("[!] Make sure the GitHub App is installed in this organization.")
            return []

        while has_next_page:
            variables = {"slug": self.slug, "cursor": cursor}

            result = self.run_query(ORG_QUERY, variables)

            # Validation: Did we find the enterprise?
            if result.get("data", {}).get("enterprise") is None:
                print(
                    f"[X] Enterprise '{self.slug}' not found or authentication lacks permission."
                )
                return []

            org_data = result["data"]["enterprise"]["organizations"]
            nodes = org_data["nodes"]

            all_orgs.extend(nodes)
            print(f"    Fetched {len(nodes)} organizations (Total: {len(all_orgs)})...")

            # Pagination logic
            page_info = org_data["pageInfo"]
            has_next_page = page_info["hasNextPage"]
            cursor = page_info["endCursor"]

        return all_orgs

    def save_to_csv(self, org_list, output_dir="scripts/output"):
        """Save organization list to CSV file."""
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"organizations.csv"
        filepath = os.path.join(output_dir, filename)

        # Write to CSV
        with open(filepath, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)

            for org in org_list:
                # Skip None entries
                if org is None:
                    continue

                # Write organization login directly
                login = org.get("login", "") if org else ""
                writer.writerow([login])

        print(f"[*] Organizations saved to: {filepath}")
        return filepath


if __name__ == "__main__":
    try:
        # Check if required environment variables are set
        required_env_vars = [
            "GH_ENTERPRISE_SLUG",
            "GH_APP_ID",
            "GH_PRIVATE_KEY",
        ]
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]

        if missing_vars:
            print(
                f"[X] Missing required environment variables: {', '.join(missing_vars)}"
            )
            print("Please set the following in your .env file:")
            print("- GH_ENTERPRISE_SLUG: Your GitHub enterprise slug")
            print("- GH_APP_ID: Your GitHub App ID")
            print("- GH_PRIVATE_KEY: Path to your GitHub App private key file")
            print("\nOptional:")
            print("- GH_INITIAL_ORG: An organization where the GitHub App is installed")
            print("  (if not set, will auto-detect from GitHub App installations)")
            exit(1)

        fetcher = EnterpriseFetcher()
        org_list = fetcher.fetch_all_organizations()

        print("\n" + "=" * 40)
        print(f"Total Organizations Found: {len(org_list)}")
        print("=" * 40)

        # Display first 5 as sample
        for org in org_list[:5]:
            print(f"- {org['login']}")

        if len(org_list) > 5:
            print(f"... and {len(org_list) - 5} more.")

        # Save to CSV
        if org_list:
            csv_file = fetcher.save_to_csv(org_list)
            print(f"[✓] CSV report generated successfully!")
        else:
            print("[!] No organizations found to save.")

    except Exception as e:
        print(f"\n[X] Fatal Error: {e}")
        import traceback

        traceback.print_exc()
