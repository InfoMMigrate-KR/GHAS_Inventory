#!/usr/bin/env python3

"""
GitHub Organization Package Fetcher

This script fetches all package details from a GitHub organization and its repositories.
It retrieves information about packages, dependencies, and repository details.

"""

import requests
import json
import os
import time
import csv
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Iterator
import urllib3
import concurrent.futures
from functools import lru_cache
from itertools import islice
import jwt

from dotenv import load_dotenv
import pandas as pd

# Disable SSL warnings for corporate environments
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class GitHubPackageFetcher:
    def __init__(
        self, app_id: str = None, private_key_path: str = None, verify_ssl: bool = True
    ):
        """
        Initialize the GitHub Package Fetcher using GitHub App authentication

        Args:
            app_id: The GitHub App ID
            private_key_path: Path to the GitHub App's private key file
            verify_ssl: Whether to verify SSL certificates (set to False for corporate environments)
        """
        self.base_url = "https://api.github.com"
        self.graphql_url = "https://api.github.com/graphql"
        self.app_id = app_id
        self.private_key_path = private_key_path
        self.installation_id = None
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self.access_token = None
        self.token_expires_at = None

        # Set SSL verification
        self.session.verify = verify_ssl

    def set_installation_id(self, org_name: str) -> bool:
        """
        Set the installation ID for a specific organization
        Returns True if successful, False otherwise
        """
        installation_id = self._get_installation_id(org_name)
        if installation_id:
            self.installation_id = installation_id
            self._update_session_headers()
            return True
        return False

    def _generate_jwt(self) -> str:
        """Generate a JWT for GitHub App authentication"""
        if not (self.app_id and self.private_key_path):
            raise ValueError("GitHub App ID and private key path are required")

        with open(self.private_key_path, "rb") as key_file:
            private_key = key_file.read()

        now = datetime.utcnow()
        payload = {"iat": now, "exp": now + timedelta(minutes=2), "iss": self.app_id}

        return jwt.encode(payload, private_key, algorithm="RS256")

    def _get_installation_id(self, org_name: str) -> Optional[str]:
        """Get the installation ID for a specific organization"""
        jwt_token = self._generate_jwt()
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        # First, try to get the installation for the organization directly
        response = requests.get(
            f"{self.base_url}/orgs/{org_name}/installation",
            headers=headers,
            verify=self.verify_ssl,
        )

        if response.status_code == 200:
            return str(response.json()["id"])

        # If org installation not found, list all installations and search for the org
        response = requests.get(
            f"{self.base_url}/app/installations",
            headers=headers,
            verify=self.verify_ssl,
        )

        if response.status_code == 200:
            installations = response.json()
            for installation in installations:
                if (
                    installation.get("account", {}).get("login", "").lower()
                    == org_name.lower()
                ):
                    return str(installation["id"])

        print(f"Warning: No GitHub App installation found for organization: {org_name}")
        return None

    def _get_installation_token(self) -> str:
        """Get an installation access token for the GitHub App"""
        if not self.installation_id:
            raise ValueError("Installation ID is required")

        jwt_token = self._generate_jwt()
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        response = requests.post(
            f"{self.base_url}/app/installations/{self.installation_id}/access_tokens",
            headers=headers,
            verify=self.verify_ssl,
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

    def _update_session_headers(self):
        """Update session headers with current installation token"""
        # Check if we need a new token
        if (
            not self.access_token
            or not self.token_expires_at
            or datetime.utcnow() + timedelta(minutes=5) >= self.token_expires_at
        ):
            self.access_token = self._get_installation_token()

        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/vnd.github.v3+json",
            }
        )

    def _convert_dict_to_tuple(self, d: Optional[Dict]) -> Optional[tuple]:
        """Convert dictionary to tuple for caching"""
        if d is None:
            return None
        return tuple(sorted(d.items()))

    @lru_cache(maxsize=1000)
    def _make_request_cached(
        self, url: str, params_tuple: Optional[tuple] = None
    ) -> Optional[Dict]:
        """Cached version of the request"""
        params = dict(params_tuple) if params_tuple else None
        return self._make_request_uncached(url, params)

    def _make_request(self, url: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make a request to GitHub API with rate limiting handling and caching"""
        params_tuple = self._convert_dict_to_tuple(params)
        return self._make_request_cached(url, params_tuple)

    def _make_request_uncached(
        self, url: str, params: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Actual request implementation"""

        try:
            response = self.session.get(url, params=params, timeout=30)
            if response.status_code == 404:
                # File not found; return None to skip missing files
                return None
            # Handle rate limiting or authentication issues
            if response.status_code in [401, 403]:
                if "rate limit" in response.text.lower():
                    # Handle rate limit
                    reset_time = int(
                        response.headers.get("X-RateLimit-Reset", time.time() + 60)
                    )
                    wait_time = reset_time - int(time.time()) + 1
                    print(f"Rate limit exceeded. Waiting {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    # Handle expired token
                    print("Token may have expired, refreshing...")
                    self._update_session_headers()

                # Retry the request with new/refreshed token
                response = self.session.get(url, params=params, timeout=30)

                if response.status_code == 404:
                    return None
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Error fetching {url}: {response.status_code} - {response.text}")
                return None

        except requests.exceptions.SSLError as e:
            print(f"SSL Error for {url}. Retrying without SSL verification...")
            try:
                # Retry without SSL verification
                old_verify = self.session.verify
                self.session.verify = False
                response = self.session.get(url, params=params, timeout=30)
                self.session.verify = old_verify
                if response.status_code == 404:
                    return None
                if response.status_code == 200:
                    return response.json()
                else:
                    print(f"Error fetching {url}: {response.status_code}")
                    return None
            except Exception as retry_e:
                print(f"Retry failed for {url}: {retry_e}")
                return None

        except requests.exceptions.RequestException as e:
            print(f"Request failed for {url}: {e}")
            return None

    def _make_graphql_request(
        self, query: str, variables: Optional[Dict] = None
    ) -> Optional[Dict]:
        # GraphQL request helper - Use the session headers which already have the current token
        payload = {"query": query, "variables": variables}
        try:
            response = self.session.post(self.graphql_url, json=payload, timeout=30)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"GraphQL error: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"GraphQL request failed: {e}")
            return None

    def get_organization_repos(self, org_name: str) -> List[Dict]:
        # Use GraphQL to fetch repositories from the organization
        repos = []
        cursor = None
        while True:
            query = """
            query($org: String!, $cursor: String) {
              organization(login: $org) {
                repositories(first: 100, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
                  nodes {
                    name
                    nameWithOwner
                    description
                    createdAt
                    updatedAt
                    stargazerCount
                    forkCount
                    url
                  }
                  pageInfo {
                    hasNextPage
                    endCursor
                  }
                }
              }
            }
            """
            variables = {"org": org_name, "cursor": cursor}
            data = self._make_graphql_request(query, variables)
            if not data:
                break
            nodes = (
                data.get("data", {})
                .get("organization", {})
                .get("repositories", {})
                .get("nodes", [])
            )
            for repo in nodes:
                # Rename field for consistency
                repo["full_name"] = repo.pop("nameWithOwner")
                repos.append(repo)
            page_info = (
                data.get("data", {})
                .get("organization", {})
                .get("repositories", {})
                .get("pageInfo", {})
            )
            if page_info.get("hasNextPage"):
                cursor = page_info.get("endCursor")
            else:
                break
        return repos

    def _get_repository_languages(self, owner: str, repo: str) -> Dict[str, int]:
        # Use GraphQL to fetch languages with size
        query = """
        query($owner: String!, $name: String!) {
          repository(owner: $owner, name: $name) {
            languages(first: 100) {
              edges {
                node {
                  name
                }
                size
              }
            }
          }
        }
        """
        variables = {"owner": owner, "name": repo}
        data = self._make_graphql_request(query, variables)
        languages = {}
        if data:
            edges = (
                data.get("data", {})
                .get("repository", {})
                .get("languages", {})
                .get("edges", [])
            )
            for edge in edges:
                languages[edge["node"]["name"]] = edge["size"]
        return languages

    def get_repository_packages(self, owner: str, repo: str) -> Dict[str, Any]:
        package_info = {
            "repository": f"{owner}/{repo}",
            "package_files": [],
            "dependencies": {},
            "languages": {},
        }

        # Fetch languages using GraphQL
        package_info["languages"] = self._get_repository_languages(owner, repo)

        # Check for common package files via existing REST approach
        package_files = [
            "package.json",  # Node.js
            "requirements.txt",  # Python
            "Pipfile",  # Python (Pipenv)
            "pyproject.toml",  # Python (Poetry/Modern)
            "pom.xml",  # Java (Maven)
            "build.gradle",  # Java (Gradle)
            "Cargo.toml",  # Rust
            "go.mod",  # Go
            "composer.json",  # PHP
            "Gemfile",  # Ruby
            "packages.config",  # .NET (NuGet)
            "*.csproj",  # .NET
            "pubspec.yaml",  # Dart/Flutter
        ]

        def process_package_file(file_name: str) -> Optional[Dict]:
            file_content = self.get_file_content(owner, repo, file_name)
            if file_content:
                deps = self.parse_dependencies(file_name, file_content)
                return {
                    "file_info": {"name": file_name, "content": file_content},
                    "deps": deps,
                }
            return None

        # Process package files concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_file = {
                executor.submit(process_package_file, file_name): file_name
                for file_name in package_files
            }

            for future in concurrent.futures.as_completed(future_to_file):
                result = future.result()
                if result:
                    package_info["package_files"].append(result["file_info"])
                    if result["deps"]:
                        package_info["dependencies"][result["file_info"]["name"]] = (
                            result["deps"]
                        )
        return package_info

    def get_file_content(self, owner: str, repo: str, file_path: str) -> Optional[str]:
        """Get content of a specific file from repository"""

        url = f"{self.base_url}/repos/{owner}/{repo}/contents/{file_path}"
        data = self._make_request(url)
        if data and data.get("type") == "file":

            try:
                import base64

                content = base64.b64decode(data["content"]).decode("utf-8")
                return content
            except Exception as e:
                print(f"Error decoding file {file_path}: {e}")

        return None

    def parse_dependencies(self, file_name: str, content: str) -> Dict[str, Any]:
        """Parse dependencies from package files"""

        dependencies = {}

        try:
            if file_name == "package.json":
                data = json.loads(content)
                dependencies.update(
                    {
                        "dependencies": data.get("dependencies", {}),
                        "devDependencies": data.get("devDependencies", {}),
                        "peerDependencies": data.get("peerDependencies", {}),
                    }
                )

            elif file_name == "requirements.txt":

                deps = {}
                for line in content.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        # Store the full dependency string (with version specifiers) as the key
                        # This preserves the complete package specification
                        deps[line] = "dependency"

                dependencies["dependencies"] = deps

            elif file_name == "pyproject.toml":
                # Basic TOML parsing for dependencies
                lines = content.split("\n")
                in_dependencies = False
                deps = {}
                for line in lines:
                    line = line.strip()
                    if (
                        line == "[tool.poetry.dependencies]"
                        or line == "[project.dependencies]"
                    ):

                        in_dependencies = True
                        continue

                    elif line.startswith("[") and in_dependencies:
                        in_dependencies = False
                        continue

                    elif in_dependencies and "=" in line:
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            name = parts[0].strip()
                            version = parts[1].strip().strip("\"'")
                            deps[name] = version

                dependencies["dependencies"] = deps

            elif file_name == "composer.json":
                data = json.loads(content)
                dependencies.update(
                    {
                        "require": data.get("require", {}),
                        "require-dev": data.get("require-dev", {}),
                    }
                )

            elif file_name == "pom.xml":
                # Basic XML parsing for Maven dependencies
                try:
                    import xml.etree.ElementTree as ET

                    root = ET.fromstring(content)

                    deps = {}
                    # Maven XML uses namespaces, so we need to be careful
                    # Find all dependency elements
                    for dependency in root.iter():
                        if (
                            dependency.tag.endswith("}dependency")
                            or dependency.tag == "dependency"
                        ):
                            group_id = ""
                            artifact_id = ""
                            version = ""
                            scope = ""

                            for child in dependency:
                                tag = child.tag
                                if tag.endswith("}groupId") or tag == "groupId":
                                    group_id = child.text or ""
                                elif tag.endswith("}artifactId") or tag == "artifactId":
                                    artifact_id = child.text or ""
                                elif tag.endswith("}version") or tag == "version":
                                    version = child.text or ""
                                elif tag.endswith("}scope") or tag == "scope":
                                    scope = child.text or ""

                            if group_id and artifact_id:
                                dep_name = f"{group_id}:{artifact_id}"
                                dep_version = version or "N/A"
                                deps[dep_name] = dep_version

                    dependencies["dependencies"] = deps

                except ET.ParseError as e:
                    print(f"Error parsing XML in {file_name}: {e}")
                except Exception as e:
                    print(f"Error processing {file_name}: {e}")

            elif file_name == "build.gradle":
                # Basic Gradle dependency parsing
                deps = {}
                lines = content.split("\n")
                in_dependencies_block = False

                for line in lines:
                    line = line.strip()

                    # Look for dependencies block
                    if line.startswith("dependencies") and "{" in line:
                        in_dependencies_block = True
                        continue
                    elif in_dependencies_block and line == "}":
                        in_dependencies_block = False
                        continue

                    # Parse dependency lines in the dependencies block
                    if in_dependencies_block and (
                        line.startswith("implementation")
                        or line.startswith("compile")
                        or line.startswith("api")
                        or line.startswith("testImplementation")
                        or line.startswith("runtimeOnly")
                    ):
                        # Extract dependency from lines like: implementation 'group:name:version'
                        if "'" in line:
                            dep_part = line.split("'")[1]
                            if ":" in dep_part:
                                parts = dep_part.split(":")
                                if len(parts) >= 2:
                                    dep_name = f"{parts[0]}:{parts[1]}"
                                    dep_version = parts[2] if len(parts) > 2 else "N/A"
                                    deps[dep_name] = dep_version
                        elif '"' in line:
                            dep_part = line.split('"')[1]
                            if ":" in dep_part:
                                parts = dep_part.split(":")
                                if len(parts) >= 2:
                                    dep_name = f"{parts[0]}:{parts[1]}"
                                    dep_version = parts[2] if len(parts) > 2 else "N/A"
                                    deps[dep_name] = dep_version

                dependencies["dependencies"] = deps

        except Exception as e:

            print(f"Error parsing {file_name}: {e}")

        return dependencies

    def get_organization_packages(self, org_name: str) -> Dict[str, Any]:
        """Get packages from GitHub Packages for the organization"""

        packages = []

        # Get packages for the organization

        url = f"{self.base_url}/orgs/{org_name}/packages"
        params = {"package_type": "npm"}  # You can modify this for other package types
        data = self._make_request(url, params)
        if data:
            packages.extend(data)

        # Also try other package types

        for package_type in ["docker", "maven", "rubygems", "nuget"]:
            params = {"package_type": package_type}
            data = self._make_request(url, params)
            if data:
                packages.extend(data)

        return packages

    def fetch_all_package_details(self, org_name: str) -> Dict[str, Any]:
        """Fetch comprehensive package details from organization"""

        print(f"Fetching package details for organization: {org_name}")
        start_time = time.time()

        result = {
            "organization": org_name,
            "timestamp": datetime.now().isoformat(),
            "repositories": [],
            "github_packages": [],
            "summary": {
                "total_repositories": 0,
                "repositories_with_packages": 0,
                "package_types": {},
                "total_dependencies": 0,
                "time_taken_seconds": 0,
            },
        }

        # Get all repositories

        repos = self.get_organization_repos(org_name)
        result["summary"]["total_repositories"] = len(repos)
        print(f"Found {len(repos)} repositories")

        # Process repositories in parallel batches
        def process_repository(repo_data):
            repo = repo_data[1]
            i = repo_data[0]
            print(f"Processing repository {i}/{len(repos)}: {repo['name']}")

            repo_packages = self.get_repository_packages(org_name, repo["name"])

            repo_info = {
                "name": repo["name"],
                "full_name": repo["full_name"],
                "description": repo.get("description", ""),
                "language": repo.get("language", ""),
                "created_at": repo["createdAt"],
                "updated_at": repo["updatedAt"],
                "stars": repo["stargazerCount"],
                "forks": repo["forkCount"],
                "url": repo["url"],
                "packages": repo_packages,
            }

            # Count total dependencies more accurately
            total_deps = 0
            for file_deps in repo_packages["dependencies"].values():
                for dep_type, dep_list in file_deps.items():
                    if isinstance(dep_list, dict):
                        total_deps += len(dep_list)
                    elif isinstance(dep_list, list):
                        total_deps += len(dep_list)

            summary_update = {
                "has_packages": bool(
                    repo_packages["dependencies"]
                ),  # Check if any dependencies found
                "lang_types": list(repo_packages["languages"].keys()),
                "dep_count": total_deps,
            }

            return repo_info, summary_update

        # Process repositories in parallel with a reasonable number of workers
        processed_repos = []
        summary_updates = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_to_repo = {
                executor.submit(process_repository, (i, repo)): repo
                for i, repo in enumerate(repos, 1)
            }

            for future in concurrent.futures.as_completed(future_to_repo):
                repo_info, summary_update = future.result()
                processed_repos.append(repo_info)
                summary_updates.append(summary_update)

        # Update result with processed repositories
        result["repositories"] = processed_repos

        # Update summary
        result["summary"]["repositories_with_packages"] = sum(
            1 for update in summary_updates if update["has_packages"]
        )

        # Aggregate language types
        for update in summary_updates:
            for lang in update["lang_types"]:
                result["summary"]["package_types"][lang] = (
                    result["summary"]["package_types"].get(lang, 0) + 1
                )

        # Sum up total dependencies
        result["summary"]["total_dependencies"] = sum(
            update["dep_count"] for update in summary_updates
        )

        # Get GitHub Packages

        print("Fetching GitHub Packages...")
        github_packages = self.get_organization_packages(org_name)
        result["github_packages"] = github_packages

        # Calculate and add time taken
        end_time = time.time()
        time_taken = round(end_time - start_time, 2)
        result["summary"]["time_taken_seconds"] = time_taken
        print(f"Time taken: {time_taken} seconds")
        return result

    def _extract_package_name(self, full_package_name: str) -> str:
        """Extract just the package name from a full dependency string with version specifiers.

        Args:
            full_package_name: Full package name with version (e.g., 'numpy==1.21.0', 'requests>=2.25.1')

        Returns:
            str: Just the package name without version specifiers
        """
        # Remove version specifiers from package name for license checking
        package_name = full_package_name

        # Handle common version specifiers in order of specificity
        version_patterns = ["==", ">=", "<=", "~=", "!=", ">", "<", "^", "@"]
        for specifier in version_patterns:
            if specifier in package_name:
                package_name = package_name.split(specifier)[0].strip()
                break

        return package_name

    def _extract_package_version(self, full_package_name: str) -> str:
        """Extract version from a full dependency string with version specifiers.

        Args:
            full_package_name: Full package name with version (e.g., 'numpy==1.21.0', 'requests>=2.25.1')

        Returns:
            str: Version specifier or 'N/A' if no version found
        """
        # Handle common version specifiers
        version_patterns = ["==", ">=", "<=", "~=", "!=", ">", "<", "^", "@"]
        for specifier in version_patterns:
            if specifier in full_package_name:
                return specifier + full_package_name.split(specifier, 1)[1].strip()

        return "N/A"

    def _check_package_license(self, package_name: str, package_type: str) -> bool:
        """Check if a package has an open source license using various package registries.

        Args:
            package_name: Name of the package to check
            package_type: Type of package (requirements.txt, package.json, etc.)

        Returns:
            bool: True if package has an open source license, False otherwise
        """

        def is_proprietary_license(license_str: str) -> bool:
            """Helper function to check if a license string indicates proprietary software"""
            if not license_str:
                return False
            proprietary_indicators = [
                "proprietary",
                "commercial",
                "all rights reserved",
                "business source license",
                "enterprise",
                "oracle",
            ]
            return any(x in license_str.lower() for x in proprietary_indicators)

        try:
            # Extract just the package name for license checking
            clean_package_name = self._extract_package_name(package_name)

            # Python packages (PyPI)
            if package_type in ["requirements.txt", "pyproject.toml"]:
                url = f"https://pypi.org/pypi/{clean_package_name}/json"
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    info = data.get("info", {})
                    classifiers = info.get("classifiers", [])
                    license_field = info.get("license", "")

                    # Check classifiers first
                    for classifier in classifiers:
                        if classifier.startswith("License :: "):
                            return not is_proprietary_license(classifier)

                    # Then check license field
                    if license_field:
                        return not is_proprietary_license(license_field)

            # Node.js packages (NPM)
            elif package_type == "package.json":
                url = f"https://registry.npmjs.org/{clean_package_name}"
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    license_info = data.get("license", "")
                    if isinstance(license_info, dict):
                        license_info = license_info.get("type", "")
                    return not is_proprietary_license(license_info)

            # Java packages (Maven Central)
            elif package_type in ["pom.xml", "build.gradle"]:
                if ":" in clean_package_name:
                    group_id, artifact_id = clean_package_name.split(":", 1)
                    url = f"https://search.maven.org/solrsearch/select?q=g:{group_id}+AND+a:{artifact_id}"
                    response = requests.get(url, timeout=5)
                    if response.status_code == 200:
                        data = response.json()
                        docs = data.get("response", {}).get("docs", [])
                        if docs:
                            license_info = docs[0].get("license", [])
                            if isinstance(license_info, list):
                                license_info = " ".join(license_info)
                            return not is_proprietary_license(license_info)

            # .NET packages (NuGet)
            elif package_type in ["packages.config", "*.csproj"]:
                url = f"https://api.nuget.org/v3/registration5-semver1/{clean_package_name.lower()}/index.json"
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("items"):
                        latest = data["items"][-1]
                        license_info = latest.get("catalogEntry", {}).get("license", "")
                        return not is_proprietary_license(license_info)

            # Rust packages (Crates.io)
            elif package_type == "Cargo.toml":
                url = f"https://crates.io/api/v1/crates/{clean_package_name}"
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("versions"):
                        license_info = data["versions"][0].get("license", "")
                        return not is_proprietary_license(license_info)

            return True  # Default to True if we can't determine
        except Exception as e:
            print(
                f"Error checking license for {clean_package_name} ({package_type}): {e}"
            )
            return True  # Default to True on error

    def save_to_csv(self, data: Dict[str, Any], output_dir: str) -> str:
        """Save the package dependencies to a CSV file with timestamp.

        Columns:
        - org_name: Name of the organization
        - repo_name: Name of the repository
        - package_name: Name of the package file (e.g., package.json, requirements.txt)
        - dependency_name: Name of the dependency
        - dependency_version: Version of the dependency (if available)
        - is_open_source: Whether the dependency is from a public registry
        """
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        # Generate timestamp for the filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(
            output_dir, f"github_dependencies_{data['organization']}_{timestamp}.csv"
        )

        # Prepare rows for CSV
        rows = []
        for repo in data["repositories"]:
            # Check if this repo has any dependencies
            if repo["packages"]["dependencies"]:
                # Process all dependency files for this repo
                for file_name, deps in repo["packages"]["dependencies"].items():
                    # Handle different dependency types
                    if file_name == "package.json":
                        for dep_type in [
                            "dependencies",
                            "devDependencies",
                            "peerDependencies",
                        ]:
                            for dep_name, dep_version in deps.get(dep_type, {}).items():
                                rows.append(
                                    {
                                        "org_name": data["organization"],
                                        "repo_name": repo["name"],
                                        "package_name": file_name,
                                        "dependency_name": dep_name,
                                        "dependency_version": dep_version or "N/A",
                                        "is_open_source": "true",  # Assuming npm packages are open source
                                    }
                                )
                    elif file_name == "requirements.txt":
                        # For requirements.txt, the key contains both name and version
                        for dep_line in deps.get("dependencies", {}):
                            # Split dependency name and version from the full line
                            dep_name = self._extract_package_name(dep_line)
                            dep_version = self._extract_package_version(dep_line)

                            # Skip license checking for now to avoid network timeouts
                            is_open_source = "true"  # Default to true
                            # if self._check_package_license(dep_name, file_name) == False:
                            #     is_open_source = "false"

                            rows.append(
                                {
                                    "org_name": data["organization"],
                                    "repo_name": repo["name"],
                                    "package_name": file_name,
                                    "dependency_name": dep_name,
                                    "dependency_version": dep_version,
                                    "is_open_source": is_open_source,
                                }
                            )
                    else:
                        # Handle other package types (where version might be in the value)
                        deps_dict = deps.get("dependencies", {})
                        if isinstance(deps_dict, dict):
                            for dep_name, dep_version in deps_dict.items():
                                # Skip license checking for now to avoid network timeouts
                                is_open_source = "true"  # Default to true
                                # if self._check_package_license(dep_name, file_name) == False:
                                #     is_open_source = "false"

                                rows.append(
                                    {
                                        "org_name": data["organization"],
                                        "repo_name": repo["name"],
                                        "package_name": file_name,
                                        "dependency_name": dep_name,
                                        "dependency_version": dep_version or "N/A",
                                        "is_open_source": is_open_source,
                                    }
                                )
                        else:
                            # Fallback for simple list format
                            for dep_name in deps_dict:
                                # if self._check_package_license(dep_name, file_name) == False:
                                is_open_source = "false"

                                rows.append(
                                    {
                                        "org_name": data["organization"],
                                        "repo_name": repo["name"],
                                        "package_name": file_name,
                                        "dependency_name": dep_name,
                                        "dependency_version": "N/A",
                                        "is_open_source": is_open_source,
                                    }
                                )

        # Write to CSV
        if rows:
            df = pd.DataFrame(rows)
            df.to_csv(filename, index=False)
            print(f"Package dependencies saved to: {filename}")
            return filename
        else:
            print(f"No dependencies found for organization: {data['organization']}")
            return ""


def process_organizations(
    input_csv: str, output_dir: str, fetcher: GitHubPackageFetcher
) -> List[str]:
    """Process multiple organizations from CSV file and save to CSV files

    Args:
        input_csv: Path to CSV file containing organization names
        output_dir: Directory where CSV files will be saved
        fetcher: GitHubPackageFetcher instance

    Returns:
        List[str]: List of paths to the generated CSV files
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Read organizations from CSV
    try:
        with open(input_csv, "r") as f:
            organizations = [org.strip() for org in f.read().strip().split(",")]
        total_orgs = len(organizations)
        print(f"Found {total_orgs} organizations to process")

        output_files = []
        for index, org_name in enumerate(organizations, 1):
            print(f"\nProcessing organization {index}/{total_orgs}: {org_name}")

            try:
                # Get installation ID for the organization
                if not fetcher.set_installation_id(org_name):
                    print(
                        f"Skipping organization {org_name} - No GitHub App installation found"
                    )
                    continue

                package_details = fetcher.fetch_all_package_details(org_name)
                # Save to a new CSV file for each organization
                output_file = fetcher.save_to_csv(package_details, output_dir)
                if output_file:
                    output_files.append(output_file)

                # Print summary for this organization
                summary = package_details["summary"]
                print("\n" + "=" * 30)
                print(f"SUMMARY: {org_name}")
                print("=" * 30)
                print(f"Total Repositories: {summary['total_repositories']}")
                print(
                    f"Repositories with Packages: {summary['repositories_with_packages']}"
                )
                print(f"Total Dependencies: {summary['total_dependencies']}")
                print(
                    f"Package Types Found: {', '.join(summary['package_types'].keys())}"
                )
                print(f"Time Taken: {summary['time_taken_seconds']} seconds")

            except Exception as e:
                print(f"Error processing organization {org_name}: {e}")
                continue

    except Exception as e:
        print(f"Error reading input CSV file: {e}")
        raise

    return output_files


def main():
    # Load environment variables
    load_dotenv()

    # Get configuration from environment
    app_id = os.getenv("GITHUB_APP_ID")
    private_key_path = os.getenv("GITHUB_PRIVATE_KEY_PATH")
    verify_ssl = os.getenv("VERIFY_SSL", "true").lower() == "true"
    input_csv = os.getenv("INPUT_CSV_PATH", "organizations.csv")
    reports_dir = os.getenv("REPORTS_DIR", "reports")

    if not all([app_id, private_key_path]):
        print(
            "Error: GitHub App credentials are required. Please set the following environment variables:"
        )
        print("- GITHUB_APP_ID: The GitHub App ID")
        print("- GITHUB_PRIVATE_KEY_PATH: Path to the GitHub App's private key file")
        return 1

    # Initialize fetcher with GitHub App credentials
    try:
        fetcher = GitHubPackageFetcher(
            app_id=app_id, private_key_path=private_key_path, verify_ssl=verify_ssl
        )
    except Exception as e:
        print(f"Error initializing GitHub Package Fetcher: {e}")
        return 1

    if not verify_ssl:
        print("Warning: SSL certificate verification disabled")

    try:
        # Process all organizations
        output_files = process_organizations(input_csv, reports_dir, fetcher)
        if output_files:
            print("\nGenerated report files:")
            for file in output_files:
                print(f"- {file}")
            return 0
        else:
            print("\nNo report files were generated")
            return 1

    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":

    exit(main())
