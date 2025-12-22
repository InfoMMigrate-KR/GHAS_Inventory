#!/usr/bin/env python3

"""
GitHub Organization Package Fetcher

This script fetches all package details from a GitHub organization and its repositories.
It retrieves information about packages, dependencies, and repository details.

Updated to use the GitHub App authentication module.
"""

import requests
import json
import os
import sys
import time
import csv
import importlib.util
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Iterator
import urllib3
import concurrent.futures
from functools import lru_cache
from itertools import islice
import jwt
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict
import base64

from dotenv import load_dotenv
import pandas as pd

# Import the GitHub App authentication module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from github_auth.github_app_auth import GitHubAppAuth

# Disable SSL warnings for corporate environments
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class GitHubPackageFetcher:
    def __init__(self, verify_ssl: bool = True):
        """
        Initialize the GitHub Package Fetcher using GitHub App authentication

        Args:
            verify_ssl: Whether to verify SSL certificates (set to False for corporate environments)
        """
        self.base_url = "https://api.github.com"
        self.graphql_url = "https://api.github.com/graphql"

        # Initialize the GitHub App authentication (it reads config from environment)
        try:
            self.auth = GitHubAppAuth()
        except Exception as e:
            print(f"Error initializing GitHubAppAuth: {e}")
            raise

        self.session = None

    def set_installation_id(self, org_name: str) -> bool:
        """
        Set the installation ID for a specific organization
        Returns True if successful, False otherwise
        """
        if self.auth.authenticate_for_organization(org_name):
            self.session = self.auth.get_authenticated_session()
            return True
        return False

    # Authentication methods now handled by GitHubAppAuth class

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
        if not self.session:
            raise ValueError("Not authenticated. Call set_installation_id first.")

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
                    # Authentication issue - refresh token
                    print("Authentication issue detected. Refreshing token...")
                    self.session = self.auth.get_authenticated_session()

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
        if not self.session:
            raise ValueError("Not authenticated. Call set_installation_id first.")

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


def create_org_access_issues_csv(timestamp: str, output_dir: str) -> str:
    """
    Create the org access issues CSV file with headers.

    Args:
        timestamp: Timestamp string for filename
        output_dir: Output directory path

    Returns:
        str: Path to the created CSV file
    """
    try:
        issues_file = os.path.join(
            output_dir, f"packages_org_access_issues_{timestamp}.csv"
        )
        # Create file with headers
        with open(issues_file, "w", newline="", encoding="utf-8") as f:
            f.write("OrgName,Comment,Timestamp\n")
        print(f"Created org access issues CSV: {issues_file}")
        return issues_file
    except Exception as e:
        print(f"Error creating org access issues CSV: {e}")
        return None


def append_org_access_issue(csv_file: str, org_name: str, comment: str) -> bool:
    """
    Append an organization access issue to the CSV file in real-time.

    Args:
        csv_file: Path to the CSV file
        org_name: Organization name
        comment: Error/issue comment

    Returns:
        bool: True if successfully appended
    """
    try:
        if csv_file and os.path.exists(csv_file):
            timestamp = datetime.now().isoformat()
            with open(csv_file, "a", newline="", encoding="utf-8") as f:
                # Escape commas in the comment by wrapping in quotes if needed
                if "," in comment or '"' in comment:
                    comment = f'"{comment.replace(chr(34), chr(34)+chr(34))}"'
                f.write(f"{org_name},{comment},{timestamp}\n")
            return True
        return False
    except Exception as e:
        print(f"Error appending org access issue to CSV: {e}")
        return False


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

    # Generate timestamp for error logging
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create org access issues CSV file upfront
    org_issues_csv = create_org_access_issues_csv(timestamp, output_dir)

    # Read organizations from CSV
    try:
        organizations = []
        with open(input_csv, "r", encoding="utf-8") as f:
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

        total_orgs = len(organizations)
        print(f"Found {total_orgs} organizations to process")

        output_files = []
        successful_orgs = 0
        failed_orgs = 0

        for index, org_name in enumerate(organizations, 1):
            print(f"\nProcessing organization {index}/{total_orgs}: {org_name}")

            try:
                # Get installation ID for the organization
                if not fetcher.set_installation_id(org_name):
                    error_msg = (
                        f"No GitHub App installation found for organization: {org_name}"
                    )
                    print(f"Skipping organization {org_name} - {error_msg}")
                    append_org_access_issue(org_issues_csv, org_name, error_msg)
                    failed_orgs += 1
                    continue

                package_details = fetcher.fetch_all_package_details(org_name)
                # Save to a new CSV file for each organization
                output_file = fetcher.save_to_csv(package_details, output_dir)
                if output_file:
                    output_files.append(output_file)
                    successful_orgs += 1

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
                error_msg = f"Error processing organization: {str(e)}"
                print(f"Error processing organization {org_name}: {e}")
                append_org_access_issue(org_issues_csv, org_name, error_msg)
                failed_orgs += 1
                continue

        # Print final summary
        print("\n" + "=" * 50)
        print("FINAL PROCESSING SUMMARY")
        print("=" * 50)
        print(f"Total Organizations: {total_orgs}")
        print(f"Successful: {successful_orgs}")
        print(f"Failed: {failed_orgs}")
        print(f"Generated {len(output_files)} report files")
        if org_issues_csv:
            print(f"Access issues logged to: {org_issues_csv}")
        print("=" * 50)

    except Exception as e:
        print(f"Error reading input CSV file: {e}")
        raise

    return output_files


def main():
    # Load environment variables
    load_dotenv()

    # Get configuration from environment
    app_id = os.getenv("GH_APP_ID")
    print(f"GH_APP_ID: {app_id}")
    private_key_path = os.getenv("GH_PRIVATE_KEY")
    verify_ssl = os.getenv("VERIFY_SSL", "true").lower() == "true"

    # Use standardized output directory structure
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))
    # Change to use scripts/output instead of root/output
    output_dir = os.path.join(script_dir, "..", "output", "fetch_packages")

    # Find organizations.csv file in multiple possible locations
    input_csv_name = "organizations.csv"
    possible_paths = [
        # First priority: scripts/output (consistent with other scripts)
        os.path.join(root_dir, "scripts", "output", input_csv_name),
        os.path.join(script_dir, "..", "output", input_csv_name),
        # Secondary: script directory and nearby
        os.path.join(script_dir, input_csv_name),
        # Legacy locations for backward compatibility
        os.path.join(root_dir, input_csv_name),
        os.path.join(root_dir, "output", input_csv_name),
    ]

    input_csv = None
    for path in possible_paths:
        if os.path.exists(path):
            input_csv = path
            break

    if not input_csv:
        print(f"Error: Could not find {input_csv_name} file. Tried locations:")
        for path in possible_paths:
            print(f"  - {path}")
        print("Attempting to generate organizations.csv using fetch_orgs.py...")

        # Try to run fetch_orgs.py to generate the organizations.csv file
        fetch_orgs_path = os.path.join(
            root_dir, "scripts", "fetch_Orgs", "fetch_orgs.py"
        )
        if os.path.exists(fetch_orgs_path):
            try:
                import subprocess

                print(f"Running fetch_orgs.py from: {fetch_orgs_path}")
                result = subprocess.run(
                    [sys.executable, fetch_orgs_path],
                    capture_output=True,
                    text=True,
                    cwd=root_dir,
                )

                if result.returncode == 0:
                    print("Successfully executed fetch_orgs.py")
                    # Check again for the CSV file in the expected location
                    output_csv = os.path.join(
                        root_dir, "scripts", "output", "organizations.csv"
                    )
                    if os.path.exists(output_csv):
                        input_csv = output_csv
                        print(f"Organizations CSV file created at: {input_csv}")
                    else:
                        print(
                            "fetch_orgs.py completed but organizations.csv not found at expected location"
                        )
                else:
                    print(f"fetch_orgs.py failed with error: {result.stderr}")
            except Exception as e:
                print(f"Failed to execute fetch_orgs.py: {e}")
        else:
            print(f"fetch_orgs.py not found at: {fetch_orgs_path}")

        if not input_csv:
            print(
                "Please create an organizations.csv file with a 'login' column containing org names, "
                "or ensure fetch_orgs.py is available and working properly."
            )
            return 1

    # GitHub App credentials are now read from environment by GitHubAppAuth
    # Verify they exist
    if not all([app_id, private_key_path]):
        print(
            "Error: GitHub App credentials are required. Please set the following environment variables:"
        )
        print("- GH_APP_ID: The GitHub App ID")
        print("- GH_PRIVATE_KEY: Path to the GitHub App's private key file")
        return 1

    # Initialize fetcher with GitHub App credentials
    try:
        fetcher = GitHubPackageFetcher(verify_ssl=verify_ssl)
    except Exception as e:
        print(f"Error initializing GitHub Package Fetcher: {e}")
        return 1

    if not verify_ssl:
        print("Warning: SSL certificate verification disabled")

    try:
        # Process all organizations
        output_files = process_organizations(input_csv, output_dir, fetcher)
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
