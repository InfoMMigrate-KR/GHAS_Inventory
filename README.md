# 🔐 Secret Scanning Alerts Inventory

A comprehensive Python tool for fetching, analyzing, and managing GitHub Enterprise security alerts. This tool provides enterprise-wide visibility into secret scanning findings, repository languages, package dependencies, and automated alert assignment capabilities.

## ✨ Features

- **🏢 Enterprise-wide Coverage**: Fetches data from all repositories within your GitHub Enterprise
- **🎯 Flexible Filtering**: Support for different alert states (open, resolved, all)
- **📊 Multiple Output Formats**: Export results as Excel (.xlsx) or CSV files
- **📈 Detailed Analytics**: Includes summary statistics and validity analysis
- **⚡ Rate Limit Handling**: Smart retry logic with exponential backoff
- **🔄 Multi-token Support**: Uses multiple GitHub tokens in round-robin for better rate limits
- **🤖 GitHub Actions Automation**: Automated scheduled or manual runs for comprehensive security analysis

---

## 🚀 Execution Options

This tool offers two execution methods to suit your workflow:

### 📦 Option 1: GitHub Actions Workflows (Recommended)
Automated, scheduled, or manual execution in the cloud without local setup.

### 💻 Option 2: Manual Python Script Execution
Direct local execution with full control over parameters and environment.

---

## 🤖 GitHub Actions Workflows

### Workflow Files Overview

| Workflow File | Purpose | Trigger Options |
|--------------|---------|-----------------|
| [install-github-app.yml](.github/workflows/install-github-app.yml) | Install/uninstall GitHub Apps across enterprise | Manual |
| [fetch-secret-scanning-alerts.yml](.github/workflows/fetch-secret-scanning-alerts.yml) | Fetch secret alerts using GitHub App | Manual / Scheduled |
| [fetch-secret-scanning-alerts-pat.yml](.github/workflows/fetch-secret-scanning-alerts-pat.yml) | Fetch secret alerts using PAT | Manual / Scheduled (Weekly) |
| [fetch-language-analysis.yml](.github/workflows/fetch-language-analysis.yml) | Analyze repository languages | Manual |
| [fetch-packages-analysis.yml](.github/workflows/fetch-packages-analysis.yml) | Analyze package dependencies | Manual |
| [assign-secret-scanning-alerts.yml](.github/workflows/assign-secret-scanning-alerts.yml) | Assign alerts to committers | Manual |

---

### � 0. Install GitHub Apps Across Enterprise

**Workflow File**: `.github/workflows/install-github-app.yml`

**Purpose**: Automates installation and uninstallation of GitHub Apps across all organizations in the enterprise.

**Triggers**:
- ✅ Manual (`workflow_dispatch`)

**Input Parameters**:
| Parameter | Type | Default | Options | Description |
|-----------|------|---------|---------|-------------|
| `repository_selection` | choice | `all` | `all`, `selected` | Repository selection for app installation |
| `parallel` | boolean | `false` | - | Enable parallel processing |
| `workers` | string | `5` | - | Number of parallel workers |
| `dry_run` | boolean | `false` | - | Preview changes without making them |
| `uninstall` | boolean | `false` | - | Uninstall apps instead of installing |

**Required Repository Variables**:
```bash
GH_ENTERPRISE_SLUG       # GitHub Enterprise slug
INSTALLER_APP_ID         # App ID of the installer app
INSTALLER_INSTALL_ID     # Installation ID of the installer app
AUTOMATION_APP_CLIENT_IDS # Comma-separated Client IDs of automation apps
```

**Required Repository Secrets**:
```bash
INSTALLER_PRIVATE_KEY    # Installer app's private key content
AUTOMATION_APPS_CONFIG   # JSON config for uninstall mode
```

**Output**: 
- Artifacts: `github-app-installation-results`
- Location: `outputs/` and `scripts/install_gitHubApp/logs/`
- Retention: 30 days

**How to Execute**:

**Install Mode**:
1. Navigate to **Actions** → **Install GitHub Apps Across Enterprise**
2. Click **Run workflow**
3. Configure parameters (leave `uninstall` as `false`)
4. Set `dry_run` to `true` to preview first
5. Click **Run workflow**

**Uninstall Mode**:
1. Ensure `AUTOMATION_APPS_CONFIG` secret is configured with app credentials
2. Navigate to **Actions** → **Install GitHub Apps Across Enterprise**
3. Click **Run workflow**
4. Set `uninstall` to `true`
5. Set `dry_run` to `true` to preview first
6. Click **Run workflow**

**Use Cases**:
- 🔧 Bulk installation of automation apps across enterprise organizations
- 🗑️ Clean removal of apps from all organizations
- 📊 Enterprise-wide app deployment management
- ⚡ High-performance parallel operations for large enterprises

**Documentation**: See [scripts/install_gitHubApp/README.md](scripts/install_gitHubApp/README.md) for detailed setup and usage instructions, or the [GitHub Actions Setup Guide](docs/GitHub-Actions-Workflow-Setup.md) for workflow configuration.

---

### �🔍 1. Fetch Secret Alerts (GitHub App)

**Workflow File**: `.github/workflows/fetch-secret-scanning-alerts.yml`

**Purpose**: Automates fetching secret scanning alerts using GitHub App authentication.

**Triggers**:
- ✅ Manual (`workflow_dispatch`)
- 🔄 Scheduled (Daily at 6 AM UTC - currently commented)

**Input Parameters**:
| Parameter | Type | Default | Options | Description |
|-----------|------|---------|---------|-------------|
| `alert_state` | choice | `open` | `all`, `open`, `resolved` | Alert state filter |
| `output_format` | choice | `xlsx` | `csv`, `xlsx`, `both` | Output file format |

**Required Secrets/Variables**:
```bash
GH_ENTERPRISE_SLUG   # Repository variable
GH_APP_ID            # Repository variable
GH_PRIVATE_KEY       # Repository secret (GitHub App private key content)
GH_PATS              # Repository secret (comma-separated tokens)
```

**Output**: 
- Artifacts: `secret-scanning-alerts-{run_id}`
- Location: `scripts/output/`
- Retention: 30 days

**How to Execute**:
1. Navigate to **Actions** → **Fetch Secret Alerts (App)**
2. Click **Run workflow**
3. Select alert state and output format
4. Click **Run workflow** button

---

### 🔐 2. Fetch Secret Alerts (PAT)

**Workflow File**: `.github/workflows/fetch-secret-scanning-alerts-pat.yml`

**Purpose**: Fetches secret scanning alerts using Personal Access Token authentication with advanced options.

**Triggers**:
- ✅ Manual (`workflow_dispatch`)
- 🔄 Scheduled (Every Monday at 00:00 UTC)

**Input Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `alert_state` | choice | `all` | Alert state filter (all/open/resolved) |
| `output_format` | choice | `csv` | Output format (csv/xlsx/both) |
| `enable_commit_enrichment` | boolean | `false` | Fetch committer information |
| `enable_repo_admin_enrichment` | boolean | `false` | Fetch repository admin details |
| `test_mode` | boolean | `false` | Limit results for testing |
| `test_limit` | string | `20` | Number of alerts in test mode |
| `secret_types` | string | `all` | Comma-separated secret types |

**Required Secrets**:
```bash
GH_ENTERPRISE_SLUG   # Repository secret
GH_PATS              # Repository secret (comma-separated PATs)
```

**Output**: 
- Artifacts: `secret-scanning-reports-{run_number}`
- Location: `scripts/fetch-secret-scanning/output/`
- Retention: 90 days

**How to Execute**:
1. Navigate to **Actions** → **Fetch Secret Alerts (PAT)**
2. Click **Run workflow**
3. Configure input parameters as needed
4. Click **Run workflow** button

---

### 📦 3. Analyze Package Dependencies

**Workflow File**: `.github/workflows/fetch-packages-analysis.yml`

**Purpose**: Analyzes package dependencies across all enterprise repositories.

**Triggers**:
- ✅ Manual (`workflow_dispatch`)
- 🔄 Scheduled (Monthly on the 15th at 3:00 AM UTC - currently commented)

**Input Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enterprise_slug` | string | `infomagnus-partner-demo` | GitHub Enterprise slug |
| `cleanup_old_files` | boolean | `true` | Clean files older than 7 days |

**Required Secrets/Variables**:
```bash
GH_ENTERPRISE_SLUG   # Repository variable
GH_APP_ID            # Repository variable
GH_PRIVATE_KEY       # Repository secret
```

**What It Does**:
1. Fetches all organizations in the enterprise
2. Scans repositories for package manager files:
   - `requirements.txt` (Python)
   - `package.json` (Node.js)
   - `pom.xml` (Maven)
   - `build.gradle` (Gradle)
   - And more...
3. Inventories all dependencies

**Output**: Package dependency reports in `scripts/output/fetch_packages/`

**Use Cases**:
- 📊 Software inventory management
- ⚖️ License compliance analysis
- 🔍 Dependency risk assessment
- 📉 Technology debt tracking

---

### 🌐 4. Analyze Repository Languages

**Workflow File**: `.github/workflows/fetch-language-analysis.yml`

**Purpose**: Analyzes programming language usage across all enterprise repositories.

**Triggers**:
- ✅ Manual (`workflow_dispatch`)
- 🔄 Scheduled (Monthly on the 1st at 2:00 AM UTC - currently commented)

**Input Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enterprise_slug` | string | `infomagnus-partner-demo` | GitHub Enterprise slug |
| `cleanup_old_files` | boolean | `true` | Clean files older than 7 days |

**Required Secrets/Variables**:
```bash
GH_ENTERPRISE_SLUG   # Repository variable
GH_APP_ID            # Repository variable
GH_PRIVATE_KEY       # Repository secret
```

**What It Does**:
1. Fetches all organizations in the enterprise
2. Uses GitHub GraphQL API to collect language statistics
3. Generates comprehensive language usage reports

**Output**: Language analysis reports in `scripts/output/fetch_languages/`

**Use Cases**:
- 📊 Technology stack reporting
- 🔄 Modernization planning
- ⚠️ Language risk analysis
- 📈 Developer skill gap analysis

---

### 👤 5. Assign Secret Alerts

**Workflow File**: `.github/workflows/assign-secret-scanning-alerts.yml`

**Purpose**: Assigns secret scanning alerts to repository committers or specified users.

**Triggers**:
- ✅ Manual (`workflow_dispatch`)

**Input Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `csv_file` | string | `scripts/output/fetch_secret_scanning/secret_scanning_YYYYMMDD_HHMMSS.csv` | Path to CSV file (relative to repo root) |
| `dry_run` | boolean | `true` | Preview assignments without making API calls |

**Required Secrets**:
```bash
GH_PATS   # Repository secret with 'repo' and 'security_events' scopes
```

**Output**: 
- Artifacts: `alert-assignments-{run_id}`
- Location: `scripts/output/assign_alerts/`
- Retention: 30 days

**How to Execute**:
1. First, run **Fetch Secret Alerts** workflow to generate CSV
2. Note the CSV filename from the artifacts
3. Navigate to **Actions** → **Assign Secret Alerts**
4. Click **Run workflow**
5. Enter the CSV file path
6. Set `dry_run` to `true` to preview (recommended first)
7. After preview, set `dry_run` to `false` to assign alerts
8. Click **Run workflow** button

**Use Cases**:
- 🎯 Automated alert remediation workflow
- 👥 Developer accountability
- 📊 Preview assignments before applying

---

## 💻 Manual Python Script Execution

For direct local execution with full control over parameters and environment.

### Prerequisites

- 🐍 Python 3.9+ (GitHub Actions uses 3.12)
- 🔑 GitHub Personal Access Tokens with `repo` scope
- 🏢 Access to GitHub Enterprise organization

---

### Setup Instructions

#### 1️⃣ Clone the Repository

```bash
git clone <repository-url>
cd GHAS_Inventory
```

#### 2️⃣ Install Dependencies

```bash
pip install -r requirements.txt
```

#### 3️⃣ Configure Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```bash
# Required: Your GitHub Enterprise slug
GH_ENTERPRISE_SLUG=your-enterprise-slug

# Required: GitHub Personal Access Tokens (comma-separated)
GH_PATS=ghp_token1,ghp_token2,ghp_token3

# Optional: Alert state to fetch (default: open)
ALERT_STATE=open

# Optional: Output format (default: xlsx)
OUTPUT_FORMAT=xlsx

# Optional: Custom output filename
OUTPUT_FILENAME=secret_scanning_report
```

---

### 🎯 Script Execution Guide

#### 🔍 1. Fetch Secret Scanning Alerts (GitHub App)

**Script**: `scripts/fetch-secret-scanning/fetch_secret_scanning_alerts_githubApp.py`

```bash
cd scripts/fetch-secret-scanning
python fetch_secret_scanning_alerts_githubApp.py
```

**Environment Variables**:
```bash
GH_ENTERPRISE_SLUG=your-enterprise
GH_APP_ID=123456
GH_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----..."
ALERT_STATE=open              # Options: open, resolved, all
OUTPUT_FORMAT=xlsx            # Options: xlsx, csv, both
```

**Output**: `scripts/output/` directory

---

#### 🔐 2. Fetch Secret Scanning Alerts (PAT)

**Script**: `scripts/fetch-secret-scanning/fetch_secret_scanning_alerts.py`

```bash
cd scripts/fetch-secret-scanning
python fetch_secret_scanning_alerts.py
```

**Environment Variables**:
```bash
GH_ENTERPRISE_SLUG=your-enterprise
GH_PATS=ghp_token1,ghp_token2
ALERT_STATE=all
OUTPUT_FORMAT=csv
ENABLE_COMMIT_ENRICHMENT=true
ENABLE_REPO_ADMIN_ENRICHMENT=false
TEST_MODE=false
TEST_LIMIT=20
SECRET_TYPES=all
```

**Output**: `scripts/fetch-secret-scanning/output/` directory

---

#### 🌐 3. Analyze Repository Languages (GitHub App)

**Script**: `scripts/fetch_languages/fetch_languages_githubAPP.py`

```bash
cd scripts/fetch_languages
python fetch_languages_githubAPP.py
```

**Environment Variables**:
```bash
GH_ENTERPRISE_SLUG=your-enterprise
GH_APP_ID=123456
GH_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----..."
```

**Prerequisites**: 
- First run `scripts/fetch_Orgs/fetch_orgs.py` to generate `organizations.csv`

**Output**: `scripts/output/fetch_languages/` directory

**What It Generates**:
- Language usage statistics per repository
- Aggregated language data across the enterprise
- Language trend analysis

---

#### 🌐 4. Analyze Repository Languages (PAT)

**Script**: `scripts/fetch_languages/fetch_languages.py`

```bash
cd scripts/fetch_languages
python fetch_languages.py
```

**Environment Variables**:
```bash
GH_ENTERPRISE_SLUG=your-enterprise
GH_PATS=ghp_token1,ghp_token2
```

**Output**: `scripts/output/fetch_languages/` directory

---

#### 📦 5. Analyze Package Dependencies

**Script**: `scripts/ORG-Fetch-Packages/fetch-packages-org.py`

```bash
cd scripts/ORG-Fetch-Packages
python fetch-packages-org.py
```

**Environment Variables**:
```bash
GH_ENTERPRISE_SLUG=your-enterprise
GH_APP_ID=123456
GH_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----..."
```

**Prerequisites**: 
- First run `scripts/fetch_Orgs/fetch_orgs.py` to generate `organizations.csv`

**Output**: `scripts/output/fetch_packages/` directory

**What It Detects**:
- 📄 `requirements.txt`, `Pipfile`, `poetry.lock` (Python)
- 📄 `package.json`, `package-lock.json`, `yarn.lock` (Node.js)
- 📄 `pom.xml`, `build.gradle`, `build.gradle.kts` (Java)
- 📄 `Gemfile`, `Gemfile.lock` (Ruby)
- 📄 `composer.json`, `composer.lock` (PHP)
- 📄 `go.mod`, `go.sum` (Go)
- 📄 And many more...

---

#### 👤 6. Assign Secret Scanning Alerts

**Script**: `scripts/assign_alerts/assign_alerts.py`

```bash
cd scripts/assign_alerts

# Dry-run mode (preview only)
python assign_alerts.py --csv-file ../output/fetch_secret_scanning/secret_scanning_20251229_142616.csv --dry-run

# Production mode (actual assignment)
python assign_alerts.py --csv-file ../output/fetch_secret_scanning/secret_scanning_20251229_142616.csv
```

**Arguments**:
- `--csv-file`: Path to secret scanning CSV file (required)
- `--dry-run`: Preview assignments without making API calls (optional)

**Environment Variables**:
```bash
GH_PATS=ghp_token_with_security_events_scope
```

**Output**: `scripts/output/assign_alerts/` directory

**⚠️ Important**: Always run with `--dry-run` first to preview assignments!

---

#### 🏢 7. Fetch Organizations

**Script**: `scripts/fetch_Orgs/fetch_orgs.py`

```bash
cd scripts/fetch_Orgs
python fetch_orgs.py
```

**Environment Variables**:
```bash
GH_ENTERPRISE_SLUG=your-enterprise
GH_APP_ID=123456
GH_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----..."
```

**Output**: 
- `scripts/output/organizations.csv`
- `scripts/output/users.csv`

**Purpose**: 
- Generates organization list required by other scripts
- Must be run before language or package analysis

---

## 🔧 Required GitHub Apps Setup

### 1️⃣ Installer App
**Purpose**: Has permission to install apps in organizations

**Creation**:
1. Enterprise Settings → GitHub Apps → New GitHub App
2. **Required Permission**: "Enterprise permissions" > "Enterprise organization installations" (read/write)
3. Install the App on the Enterprise account
4. Note: App ID, Installation ID, download private key

### 2️⃣ Automation App(s)
**Purpose**: The app(s) you want installed everywhere

**Creation**:
1. Create with whatever permissions your automation needs
2. **Required Permission**: 
  "Repository permissions" > "Actions" (read/write), "Secret scanning alerts" (read/write), "Workflows" (read/write)
  "Organization permissions" > "Secrets" (read/write), "Variables" (read/write)
3. Note the Client ID (starts with "Iv1.")
4. For uninstall: Note App ID and download private key

---

#### 🚀 8. Install/Uninstall GitHub Apps Enterprise-wide

**Script**: `scripts/install_gitHubApp/install_github_all.py`

```bash
cd scripts/install_gitHubApp

# Basic installation (single app)
python install_github_all.py \
    --enterprise my-enterprise \
    --installer-app-id 123456 \
    --installer-private-key /path/to/installer.pem \
    --installer-install-id 789012 \
    --automation-app-client-id Iv1.abc123def456 \
    --dry-run --verbose

# Multi-app installation
python install_github_all.py \
    --automation-app-client-ids Iv1.abc123,Iv1.def456 \
    --parallel --workers 10 \
    --dry-run --verbose

# Uninstall apps
python install_github_all.py \
    --automation-app-client-ids Iv1.abc123,Iv1.def456 \
    --automation-apps-config automation-apps-config.json \
    --uninstall --dry-run --verbose
```

**Environment Variables**:
```bash
GH_ENTERPRISE_SLUG=your-enterprise
INSTALLER_APP_ID=123456
INSTALLER_PRIVATE_KEY=/path/to/installer-private-key.pem
INSTALLER_INSTALL_ID=789012
AUTOMATION_APP_CLIENT_IDS=Iv1.abc123,Iv1.def456
AUTOMATION_APPS_CONFIG=automation-apps-config.json  # For uninstall
```

**Key Arguments**:
- `--parallel --workers N`: Enable parallel processing with N workers
- `--dry-run`: Preview changes without making them
- `--uninstall`: Switch to uninstall mode
- `--batch-size N`: Control memory usage for large enterprises
- `--resume-from state`: Resume interrupted operations

**Output**: 
- `outputs/api_app_installation_{enterprise}_{timestamp}.json`
- `scripts/logs/api_app_installer_{enterprise}_{timestamp}.log`
- Comprehensive installation/uninstallation reports

**Purpose**: 
- Bulk install automation apps across all enterprise organizations
- Remove previously installed apps enterprise-wide
- High-performance operations for large enterprises (500+ orgs)

**⚠️ Important**: Always run with `--dry-run` first to preview operations!

**Documentation**: See [scripts/install_gitHubApp/README.md](scripts/install_gitHubApp/README.md) for comprehensive setup instructions and advanced usage.

---

## 📊 Output Files

### Secret Scanning Alerts

**Location**: `scripts/output/` or `scripts/fetch-secret-scanning/output/`

**Excel file** (`secret_scanning_alerts_TIMESTAMP.xlsx`):
- **Summary** sheet: Query metadata and statistics
- **Secret_Scanning** sheet: Detailed alert data

**CSV files** (when CSV format is selected):
- `summary_TIMESTAMP.csv`: Summary statistics
- `secret_scanning_TIMESTAMP.csv`: Detailed alert data

**Alert Data Includes**:
- 🔢 Alert number and URLs
- 📁 Repository and organization information
- 🔐 Secret type and validity status
- ⏰ Creation and update timestamps
- ✅ Resolution information
- 📍 Location details
- 🌐 Public leak status

### Language Analysis

**Location**: `scripts/output/fetch_languages/`

**Files Generated**:
- Language usage by repository
- Aggregated language statistics
- Language trends and distributions

### Package Dependencies

**Location**: `scripts/output/fetch_packages/`

**Files Generated**:
- Package inventory by repository
- Dependency tree analysis
- Package version tracking

### Alert Assignments

**Location**: `scripts/output/assign_alerts/`

**Files Generated**:
- Assignment report
- Success/failure log
- Unassigned alerts list

---

## 🔑 GitHub Token Setup

### Creating Personal Access Tokens

1. **Navigate to GitHub Settings**:
   - Go to [GitHub Settings](https://github.com/settings/tokens) → Developer settings → Personal access tokens → Tokens (classic)

2. **Generate New Token**:
   - Click "Generate new token (classic)"
   - Give it a descriptive name (e.g., "GHAS Inventory Tool")
   - Set expiration as needed

3. **Select Required Scopes**:
   - ✅ `repo` (Full control of private repositories)
   - ✅ `security_events` (For alert assignment)
   - ✅ `read:org` (Read organization data)

4. **Generate and Save**:
   - Click "Generate token"
   - **Important**: Copy the token immediately (you won't see it again!)
   - Store it securely in a password manager

### Multiple Token Benefits

Using multiple tokens provides:
- ⚡ **Higher Rate Limits**: Round-robin usage across tokens
- 🔄 **Better Reliability**: Continues working if one token is rate-limited
- 📈 **Improved Performance**: Parallel requests with different tokens
- ⏱️ **Automatic Recovery**: Handles rate limit resets intelligently

**Example Configuration**:
```bash
GH_PATS=ghp_abc123...,ghp_def456...,ghp_ghi789...
```

### GitHub App Setup (Recommended)

For enterprise-scale operations, GitHub Apps provide better security and higher rate limits:

1. **Create GitHub App**:
   - Go to Organization Settings → Developer settings → GitHub Apps
   - Click "New GitHub App"

2. **Configure Permissions**:
   - **Repository permissions**:
     - Contents: Read
     - Metadata: Read
     - Secret scanning alerts: Read and write
   - **Organization permissions**:
     - Members: Read

3. **Generate Private Key**:
   - After creating the app, click "Generate a private key"
   - Save the downloaded `.pem` file securely

4. **Install App**:
   - Install the app to your enterprise organization
   - Note the App ID from the app settings

5. **Configure in Repository**:
   ```bash
   GH_APP_ID=123456
   GH_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----
   MIIEpAIBAAKCAQEA...
   -----END RSA PRIVATE KEY-----"
   ```

---

## 📋 Configuration Reference

### Environment Variables

| Variable | Required | Default | Description | Valid Values |
|----------|----------|---------|-------------|--------------|
| `GH_ENTERPRISE_SLUG` | ✅ Yes | - | GitHub Enterprise slug | String |
| `GH_PATS` | ✅ Yes* | - | Comma-separated PATs | String (comma-separated) |
| `GH_APP_ID` | ✅ Yes* | - | GitHub App ID | Integer |
| `GH_PRIVATE_KEY` | ✅ Yes* | - | GitHub App private key | PEM format string |
| `ALERT_STATE` | ❌ No | `open` | Alert state filter | `open`, `resolved`, `all` |
| `OUTPUT_FORMAT` | ❌ No | `xlsx` | Export format | `xlsx`, `csv`, `both` |
| `OUTPUT_FILENAME` | ❌ No | Auto | Custom filename | String (no extension) |
| `ENABLE_COMMIT_ENRICHMENT` | ❌ No | `false` | Fetch committer info | `true`, `false` |
| `ENABLE_REPO_ADMIN_ENRICHMENT` | ❌ No | `false` | Fetch admin info | `true`, `false` |
| `TEST_MODE` | ❌ No | `false` | Limit results for testing | `true`, `false` |
| `TEST_LIMIT` | ❌ No | `20` | Number of test alerts | Integer |
| `SECRET_TYPES` | ❌ No | `all` | Secret type filter | Comma-separated or `all` |

*Note: Either `GH_PATS` OR (`GH_APP_ID` + `GH_PRIVATE_KEY`) is required, not both.

---

## 🔍 Troubleshooting

### Common Issues and Solutions

#### ❌ Authentication Error

**Symptom**: `401 Unauthorized` or `403 Forbidden`

**Solutions**:
- ✅ Verify tokens have the correct scopes (`repo`, `security_events`)
- ✅ Check token hasn't expired
- ✅ For GitHub App, verify private key is correctly formatted
- ✅ Ensure the app is installed on the organization

```bash
# Test token validity
curl -H "Authorization: token YOUR_TOKEN" https://api.github.com/user
```

#### ⏱️ Rate Limit Issues

**Symptom**: `403 rate limit exceeded`

**Solutions**:
- ✅ Add more tokens to `GH_PATS` (comma-separated)
- ✅ Switch to GitHub App authentication (5000 req/hour)
- ✅ Enable scheduled runs instead of frequent manual runs
- ✅ Use `TEST_MODE=true` for testing

```bash
# Check rate limit status
curl -H "Authorization: token YOUR_TOKEN" https://api.github.com/rate_limit
```

#### 📁 Permission Errors

**Symptom**: Cannot write to output directory

**Solutions**:
- ✅ Ensure output directory exists: `mkdir -p scripts/output`
- ✅ Check write permissions: `ls -la scripts/`
- ✅ On Windows, run as administrator if needed

#### 🌐 Network Timeouts

**Symptom**: Request timeout or connection errors

**Solutions**:
- ✅ Check network connectivity
- ✅ Verify GitHub API status: https://www.githubstatus.com/
- ✅ Check firewall/proxy settings
- ✅ Increase timeout values in script configuration

#### 📊 No Data Retrieved

**Symptom**: Empty reports or no alerts found

**Solutions**:
- ✅ Verify `GH_ENTERPRISE_SLUG` is correct
- ✅ Check `ALERT_STATE` filter setting
- ✅ Ensure repositories have secret scanning enabled
- ✅ Verify token has access to the enterprise

#### 🐍 Python Import Errors

**Symptom**: `ModuleNotFoundError` or import failures

**Solutions**:
- ✅ Install dependencies: `pip install -r requirements.txt`
- ✅ Check Python version: `python --version` (need 3.9+)
- ✅ Use virtual environment:
  ```bash
  python -m venv venv
  source venv/bin/activate  # On Windows: venv\Scripts\activate
  pip install -r requirements.txt
  ```

---

## 📝 Logging

### Log Levels and Locations

All scripts provide comprehensive logging:

**Console Output**:
- ✅ Real-time progress monitoring
- ⚠️ Warning and error messages
- 📊 Summary statistics

**Log Files**:
- 📍 Location: `scripts/output/logs/`
- 📝 Format: `script_name_TIMESTAMP.log`
- 🔍 Contains: Detailed debugging information

**Log Levels**:
- `INFO`: General operation progress
- `WARNING`: Non-critical issues
- `ERROR`: Failed operations
- `DEBUG`: Detailed technical information

**Example Log File Locations**:
```
scripts/output/logs/secret_scanning_20251229_142616.log
scripts/output/fetch_languages/logs/language_analysis_20251229_143000.log
scripts/output/fetch_packages/logs/package_analysis_20251229_144500.log
```

---

## 🔒 Security Considerations

### Best Practices

1. **Token Management**:
   - ✅ Store tokens in environment variables or GitHub Secrets
   - ✅ Never commit tokens to version control
   - ✅ Regularly rotate access tokens (every 90 days recommended)
   - ✅ Use GitHub Apps for production environments
   - ✅ Implement least-privilege access (only required scopes)

2. **Report Security**:
   - ⚠️ Reports contain sensitive security information
   - ✅ Restrict access to output directories
   - ✅ Use secure file transfer methods
   - ✅ Implement retention policies (auto-cleanup)
   - ✅ Encrypt reports at rest if storing long-term

3. **Network Security**:
   - ✅ Use HTTPS for all API communications
   - ✅ Verify SSL certificates
   - ✅ Consider using VPN for enterprise access
   - ✅ Implement IP allowlisting if possible

4. **Audit Trail**:
   - ✅ Enable logging for all executions
   - ✅ Monitor token usage patterns
   - ✅ Review access logs regularly
   - ✅ Track who runs workflows and when

5. **GitHub Actions Security**:
   - ✅ Use repository secrets for sensitive data
   - ✅ Limit workflow permissions to minimum required
   - ✅ Review workflow run history regularly
   - ✅ Enable branch protection for workflow files

---

## 📚 Additional Resources

### Documentation

- 📖 [GitHub REST API Documentation](https://docs.github.com/en/rest)
- 📖 [Secret Scanning API Reference](https://docs.github.com/en/rest/secret-scanning)
- 📖 [GitHub Apps Documentation](https://docs.github.com/en/apps)
- 📖 [GitHub Actions Documentation](https://docs.github.com/en/actions)

### Related Projects

- [GitHub Advanced Security](https://github.com/features/security)
- [Secret Scanning Partner Program](https://docs.github.com/en/code-security/secret-scanning/secret-scanning-partner-program)

### Support

For issues or questions:
1. Check the [Troubleshooting](#-troubleshooting) section
2. Review workflow logs in GitHub Actions
3. Check Python script logs in `scripts/output/logs/`
4. Open an issue in this repository

---
## Development Setup

```bash
# Clone the repository
git clone <repository-url>
cd GHAS_Inventory

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run tests
python -m pytest tests/
```

---

## 📊 Project Structure

```
GHAS_Inventory/
├── .github/
│   └── workflows/              # GitHub Actions workflow files
│       ├── fetch-secret-scanning-alerts.yml
│       ├── fetch-secret-scanning-alerts-pat.yml
│       ├── fetch-language-analysis.yml
│       ├── fetch-packages-analysis.yml
│       └── assign-secret-scanning-alerts.yml
├── docs/
│   ├── agents/                 # GitHub Copilot custom agent definitions
│   │   ├── README.md          # Agent deployment guide
│   │   └── jenkins-migrator.agent.md  # Jenkins to GitHub Actions migration agent
│   └── Secret_Scanning/        # Secret scanning documentation
├── scripts/
│   ├── fetch-secret-scanning/  # Secret scanning scripts
│   ├── fetch_languages/        # Language analysis scripts
│   ├── ORG-Fetch-Packages/     # Package dependency scripts
│   ├── assign_alerts/          # Alert assignment scripts
│   ├── fetch_Orgs/             # Organization fetching scripts
│   └── output/                 # Generated reports and logs
├── requirements.txt            # Python dependencies
└── README.md                   # This file
```

---

## 🤖 GitHub Copilot Custom Agents

This repository includes specialized GitHub Copilot custom agents for CI/CD migration tasks.

### Jenkins to GitHub Actions Migration Agent

**Location**: `docs/agents/jenkins-migrator.agent.md`

**Purpose**: Specialized agent for migrating existing Jenkins pipelines to GitHub Actions workflows, supporting declarative, scripted, and YAML-based pipeline configurations.

**Key Features**:
- ✅ Converts Jenkins declarative pipelines to GitHub Actions workflows
- ✅ Handles Jenkins scripted pipelines (Groovy-based imperative style)
- ✅ Supports YAML-based Jenkins configurations
- ✅ Expands Jenkins shared library calls inline
- ✅ Migrates credential bindings to GitHub Secrets
- ✅ Validates converted workflows with actionlint
- ✅ Creates comprehensive migration documentation

**Documentation**: See [`docs/agents/README.md`](docs/agents/README.md) for detailed information about agent deployment and usage.

**Note**: Custom agents are documented in `docs/agents/` and deployed to `.github/agents/` when ready for production use. The `.github/agents/` directory is protected by repository rules to ensure proper review of agent configurations.
