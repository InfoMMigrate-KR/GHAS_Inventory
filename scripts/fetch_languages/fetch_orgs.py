import os
import time
import requests
import itertools
import csv
from datetime import datetime
from dotenv import load_dotenv

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

        # Load tokens and setup iterator
        tokens_str = os.getenv("GH_PATS")
        if not tokens_str or not self.slug:
            raise ValueError("Missing GH_ENTERPRISE_SLUG or GH_PATS in .env file")

        self.tokens_list = [t.strip() for t in tokens_str.split(",") if t.strip()]
        self.token_cycle = itertools.cycle(self.tokens_list)
        self.current_token = next(self.token_cycle)

        print(f"[*] Loaded {len(self.tokens_list)} tokens for Enterprise: {self.slug}")

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.current_token}",
            "Content-Type": "application/json",
        }

    def _rotate_token(self):
        """Switches to the next token in the list."""
        print(f"[!] Rotating token...")
        self.current_token = next(self.token_cycle)

    def run_query(self, query, variables):
        """
        Executes GraphQL query with retry logic for rate limits and auth errors.
        """
        max_retries = (
            len(self.tokens_list) * 2
        )  # Allow cycling through all tokens twice
        attempts = 0

        while attempts < max_retries:
            try:
                response = requests.post(
                    self.api_url,
                    json={"query": query, "variables": variables},
                    headers=self._get_headers(),
                    timeout=10,
                )

                # Handle HTTP 401 (Unauthorized) or 403 (Forbidden/Rate Limit)
                if response.status_code in [401, 403]:
                    print(f"[!] HTTP {response.status_code} encountered.")
                    self._rotate_token()
                    attempts += 1
                    continue

                if response.status_code != 200:
                    raise Exception(
                        f"Query failed with code {response.status_code}: {response.text}"
                    )

                data = response.json()

                # Check for GraphQL specific errors (secondary rate limits)
                if "errors" in data:
                    errors = data["errors"]
                    is_rate_limit = any(
                        e.get("type") == "RATE_LIMITED"
                        or "rate limit" in e.get("message", "").lower()
                        for e in errors
                    )

                    if is_rate_limit:
                        print("[!] GraphQL Rate Limit Hit.")
                        self._rotate_token()
                        attempts += 1
                        time.sleep(1)  # Short cool-off
                        continue
                    else:
                        # Return data even if there are non-critical errors,
                        # but usually, we might want to raise here depending on strictness
                        print(f"[!] GraphQL Errors: {errors}")
                        return data

                return data

            except requests.exceptions.RequestException as e:
                print(f"[!] Network error: {e}")
                attempts += 1
                time.sleep(2)

        raise Exception(
            "Max retries exceeded. All tokens might be exhausted or invalid."
        )

    def fetch_all_organizations(self):
        all_orgs = []
        has_next_page = True
        cursor = None

        print("[*] Starting fetch...")

        while has_next_page:
            variables = {"slug": self.slug, "cursor": cursor}

            result = self.run_query(ORG_QUERY, variables)

            # Validation: Did we find the enterprise?
            if result.get("data", {}).get("enterprise") is None:
                print(
                    f"[X] Enterprise '{self.slug}' not found or token lacks permission."
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

    def save_to_csv(self, org_list, output_dir="scripts/fetch_languages/output"):
        """Save organization list to CSV file."""
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"organizations.csv"
        filepath = os.path.join(output_dir, filename)

        # Define CSV headers
        headers = ["login"]

        # Write to CSV
        with open(filepath, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=headers)
            writer.writeheader()

            for org in org_list:
                # Skip None entries
                if org is None:
                    continue

                # Handle potential None values
                row = {
                    "login": org.get("login", "") if org else "",
                }
                writer.writerow(row)

        print(f"[*] Organizations saved to: {filepath}")
        return filepath


if __name__ == "__main__":
    try:
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
