# 🚀 GitHub App Installation & Uninstallation Tool

A comprehensive Python script and GitHub Actions workflow for installing and uninstalling GitHub Apps across all organizations in a GitHub Enterprise using the GitHub API.

## ✨ Features

- **🏢 Enterprise-wide Operations**: Install/uninstall apps across all organizations in your GitHub Enterprise
- **📱 Multi-app Support**: Handle single or multiple GitHub Apps simultaneously
- **⚡ Parallel Processing**: Speed up operations with configurable parallel execution
- **🔄 Uninstall Mode**: Remove previously installed apps with automated discovery
- **🎯 Dry Run Mode**: Preview changes before making them
- **🤖 GitHub Actions Integration**: Automated workflow execution with configurable parameters
- **📊 Comprehensive Reporting**: Detailed JSON and Markdown reports with execution statistics
- **🛡️ Rate Limit Handling**: Smart rate limiting with automatic delays
- **🔧 Resume Capability**: Resume interrupted operations from where they left off

---

## 🚀 Execution Options

This tool offers two execution methods:

### 📦 Option 1: GitHub Actions Workflow (Recommended)
Automated execution in the cloud with secure secret management.

### 💻 Option 2: Manual Python Script Execution
Direct local execution with full control over parameters.

---

## 🤖 GitHub Actions Workflow

### Workflow Overview

**File**: `.github/workflows/install-github-app.yml`

**Purpose**: Automates GitHub App installation and uninstallation across enterprise organizations.

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
GH_ENTERPRISE_SLUG       # GitHub Enterprise slug (e.g., 'my-enterprise')
INSTALLER_APP_ID         # App ID of the installer app
INSTALLER_INSTALL_ID     # Installation ID of the installer app
AUTOMATION_APP_CLIENT_IDS # Comma-separated Client IDs of automation apps
```

**Required Repository Secrets**:
```bash
INSTALLER_PRIVATE_KEY    # Installer app's private key content
AUTOMATION_APPS_CONFIG   # JSON config for uninstall mode (see format below)
```

### 📝 AUTOMATION_APPS_CONFIG Format

For uninstall mode, create this JSON structure as a repository secret:

```json
{
  "CLIENT_ID_1": {
    "app_id": "APP_ID_1",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\n[KEY_CONTENT]\n-----END RSA PRIVATE KEY-----"
  },
  "CLIENT_ID_2": {
    "app_id": "APP_ID_2", 
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\n[KEY_CONTENT]\n-----END RSA PRIVATE KEY-----"
  }
}
```

### 🎯 How to Execute

#### Install Mode
1. Navigate to **Actions** → **Install GitHub Apps Across Enterprise**
2. Click **Run workflow**
3. Configure parameters:
   - Repository selection: `all` or `selected`
   - Parallel: `true` for faster execution
   - Workers: `10` for large enterprises
   - Dry run: `true` to preview first
4. Click **Run workflow**

#### Uninstall Mode
1. Ensure `AUTOMATION_APPS_CONFIG` secret is configured
2. Navigate to **Actions** → **Install GitHub Apps Across Enterprise**
3. Click **Run workflow**
4. Configure parameters:
   - **Uninstall**: ✅ `true`
   - **Dry run**: ✅ `true` (recommended first)
   - Other parameters as needed
5. Click **Run workflow**

---

## 💻 Manual Python Script Execution

### Prerequisites

- 🐍 Python 3.9+ (GitHub Actions uses 3.12)
- 🔑 GitHub Apps with proper permissions
- 🏢 Access to GitHub Enterprise

### Setup Instructions

#### 1️⃣ Install Dependencies

```bash
cd scripts/install_gitHubApp
pip install -r ../../requirements.txt
```

#### 2️⃣ Configure Environment

Create a `.env` file in the project root:

```bash
# Required: GitHub Enterprise Configuration
GH_ENTERPRISE_SLUG=your-enterprise-slug

# Required: Installer App Configuration
INSTALLER_APP_ID=123456
INSTALLER_PRIVATE_KEY=/path/to/installer-private-key.pem
INSTALLER_INSTALL_ID=789012

# Required: Automation App Configuration
AUTOMATION_APP_CLIENT_IDS=Iv1.abc123def456,Iv1.ghi789jkl012

# Optional: Automation Apps Config for Uninstall (JSON file path)
AUTOMATION_APPS_CONFIG=automation-apps-config.json
```

### 🎯 Script Execution Examples

#### Basic Installation (Single App)
```bash
python install_github_all.py \
    --enterprise my-enterprise \
    --installer-app-id 123456 \
    --installer-private-key /path/to/installer.pem \
    --installer-install-id 789012 \
    --automation-app-client-id Iv1.abc123def456 \
    --dry-run --verbose
```

#### Multi-App Installation
```bash
python install_github_all.py \
    --automation-app-client-ids Iv1.abc123,Iv1.def456,Iv1.ghi789 \
    --parallel --workers 10 \
    --dry-run --verbose
```

#### Parallel Installation with Custom Output
```bash
python install_github_all.py \
    --parallel --workers 15 \
    --batch-size 50 \
    --output-folder ./results \
    --verbose
```

#### Uninstall Single App
```bash
python install_github_all.py \
    --automation-app-client-id Iv1.abc123def456 \
    --automation-app-id 987654 \
    --automation-app-private-key /path/to/automation.pem \
    --uninstall --dry-run --verbose
```

#### Uninstall Multiple Apps
```bash
python install_github_all.py \
    --automation-app-client-ids Iv1.abc123,Iv1.def456 \
    --automation-apps-config automation-apps-config.json \
    --uninstall --parallel --workers 10 \
    --dry-run --verbose
```

#### Using .env File Only
```bash
# Configure .env file then run:
python install_github_all.py --dry-run --verbose
```

#### Resume Interrupted Operations
```bash
# Resume from enterprise state file
python install_github_all.py --resume-from state --verbose

# Resume from specific output file
python install_github_all.py --resume-from outputs/api_app_installation_enterprise_20260107_223749.json
```

#### Advanced Options
```bash
# Custom API base URL and export organizations CSV
python install_github_all.py \
    --base-url https://api.github.com \
    --export-orgs-csv \
    --batch-size 50 \
    --rate-limit-delay 0.1 \
    --verbose

# Uninstall with individual app credentials
python install_github_all.py \
    --automation-app-client-id Iv1.abc123def456 \
    --automation-app-id 987654 \
    --automation-app-private-key /path/to/automation.pem \
    --uninstall --dry-run --verbose
```

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

## 📊 Output & Reporting

### File Outputs

| File Type | Location | Description |
|-----------|----------|-------------|
| **JSON Report** | `outputs/api_app_installation_{enterprise}_{timestamp}.json` | Detailed results data |
| **Markdown Report** | `api_app_installation_{enterprise}_{timestamp}.md` | Executive summary |
| **Organizations CSV** | `outputs/organizations.csv` | List of enterprise orgs |
| **Log File** | `scripts/logs/api_app_installer_{enterprise}_{timestamp}.log` | Detailed execution log |

### Report Contents

**Executive Summary**:
- ✅ Successfully installed/uninstalled count
- ⏭️ Skipped (already installed/not installed) count
- ❌ Failed operations count
- 📊 Success rate percentage

**Detailed Results**:
- Per-organization results with status and error details
- API call statistics and rate limit information
- Execution timing and performance metrics
- Throughput projections for scaling

**Performance Metrics**:
- Organization listing time
- Installation/uninstallation time
- Total execution time
- API calls per second throughput
- Projections for 100/500/1000/3000 organizations

---

## ⚡ Performance & Scaling

### Execution Modes

| Mode | Throughput | Use Case |
|------|------------|----------|
| **Sequential** | ~1.2 ops/sec | Small enterprises (< 50 orgs) |
| **Parallel (5 workers)** | ~4-6 ops/sec | Medium enterprises (50-200 orgs) |
| **Parallel (10 workers)** | ~8-12 ops/sec | Large enterprises (200-500 orgs) |
| **Parallel (15+ workers)** | ~12+ ops/sec | Very large enterprises (500+ orgs) |

### Scaling Projections

Based on actual execution metrics:

| Organizations | Apps | Sequential | Parallel (10 workers) |
|---------------|------|------------|----------------------|
| 100 | 1 | ~1m 22s | ~17s |
| 500 | 1 | ~6m 50s | ~1m 25s |
| 1,000 | 1 | ~13m 41s | ~2m 50s |
| 3,000 | 1 | ~41m 4s | ~8m 30s |

### Optimization Tips

**For Large Enterprises**:
- Use `--parallel --workers 15` for maximum throughput
- Set `--batch-size 50` to reduce memory usage
- Use `--rate-limit-delay 0.1` if hitting rate limits
- Run during off-peak hours for better API performance

**For Multiple Apps**:
- Each additional app multiplies execution time
- Consider staggered deployments for many apps
- Monitor rate limits with high worker counts

---

## � Command Line Arguments Reference

### Required Arguments

| Argument | Environment Variable | Description | Example |
|----------|---------------------|-------------|----------|
| `--enterprise` | `GH_ENTERPRISE_SLUG` | GitHub Enterprise slug | `my-enterprise` |
| `--installer-app-id` | `INSTALLER_APP_ID` | App ID of the installer app | `123456` |
| `--installer-private-key` | `INSTALLER_PRIVATE_KEY` | Path to installer app's private key | `/path/to/key.pem` |
| `--installer-install-id` | `INSTALLER_INSTALL_ID` | Installation ID of installer app | `789012` |

### App Selection (One Required)

| Argument | Environment Variable | Description | Example |
|----------|---------------------|-------------|----------|
| `--automation-app-client-id` | `AUTOMATION_APP_CLIENT_ID` | Single app Client ID | `Iv1.abc123def456` |
| `--automation-app-client-ids` | `AUTOMATION_APP_CLIENT_IDS` | Multiple app Client IDs | `Iv1.abc123,Iv1.def456` |

### Optional Arguments

| Argument | Default | Description | Example |
|----------|---------|-------------|----------|
| `--repository-selection` | `all` | Repository selection for installation | `all`, `selected` |
| `--output-folder` | `outputs` | Output folder for results | `./results` |
| `--parallel` | `false` | Enable parallel processing | (flag) |
| `--workers` | `5` | Number of parallel workers | `10` |
| `--batch-size` | `100` | Orgs per batch (memory control) | `50` |
| `--rate-limit-delay` | `0.0` | Minimum delay between API calls | `0.1` |
| `--dry-run` | `false` | Preview without making changes | (flag) |
| `--verbose` | `false` | Enable detailed logging | (flag) |
| `--base-url` | `https://api.github.com` | GitHub API base URL | Custom GitHub instance |
| `--export-orgs-csv` | `false` | Export organizations to CSV | (flag) |
| `--resume-from` | - | Resume from previous run | `state`, file path |

### Uninstall Mode Arguments

| Argument | Environment Variable | Description | Example |
|----------|---------------------|-------------|----------|
| `--uninstall` | - | Switch to uninstall mode | (flag) |
| `--automation-app-id` | - | App ID for single app uninstall | `987654` |
| `--automation-app-private-key` | - | Private key for single app uninstall | `/path/to/key.pem` |
| `--automation-apps-config` | `AUTOMATION_APPS_CONFIG` | JSON config for multi-app uninstall | `apps-config.json` |

---

## �🛠️ Troubleshooting

### Common Issues

#### 1. JWT Token Errors
```
Error: JWT too far in future (401)
```
**Solution**: JWT timing fixed - uses 9-minute expiration instead of 10

#### 2. Permission Denied
```
Error: Forbidden (403)
```
**Causes**:
- Installer app not installed on enterprise
- Missing "Enterprise organization installations" permission
- Automation app Client ID not found

#### 3. Organization Access Issues
```
Error: No GitHub App installation found
```
**Causes**:
- Installer app not installed on specific organization
- Organization not part of the enterprise
- App installation suspended

#### 4. Rate Limiting
```
Error: API rate limit exceeded
```
**Solutions**:
- Reduce `--workers` count
- Increase `--rate-limit-delay`
- Use `--batch-size` to process in smaller chunks

### Debug Mode

Enable verbose logging for detailed troubleshooting:

```bash
python install_github_all.py --verbose --dry-run
```

Logs include:
- 🔍 JWT token generation and validation
- 🌐 API request/response details
- ⏱️ Rate limiting and retry logic
- 📊 Real-time progress and statistics

### Resume Interrupted Operations

If execution is interrupted, resume from where it left off:

```bash
python install_github_all.py --resume-from state --verbose
```

Or resume from a specific output file:

```bash
python install_github_all.py --resume-from outputs/api_app_installation_enterprise_20260107_223749.json
```

---

## 📋 Best Practices

### Security
- ✅ Store private keys as repository secrets, not in code
- ✅ Use organization-scoped GitHub Apps when possible
- ✅ Regularly rotate private keys
- ✅ Test with `--dry-run` before production runs

### Performance
- ✅ Start with small worker counts and increase gradually
- ✅ Monitor API rate limits during execution
- ✅ Use parallel mode for enterprises with 50+ organizations
- ✅ Run during off-peak hours for better performance

### Operations
- ✅ Always test with `--dry-run` first
- ✅ Keep automation apps config file secure and up-to-date
- ✅ Monitor execution logs for errors and rate limiting
- ✅ Use resume functionality for large enterprises

---

## 🔗 Related Documentation

- [GitHub Apps Documentation](https://docs.github.com/en/developers/apps)
- [Enterprise App Installation API](https://docs.github.com/en/enterprise-cloud@latest/admin/managing-github-apps-for-your-enterprise)
- [GitHub Actions Workflow Setup Guide](../../docs/GitHub-Actions-Workflow-Setup.md)
- [GitHub Actions Workflows](../../.github/workflows/)
- [Main Repository README](../../README.md)

---

## 🆘 Support

For issues or questions:

1. **Check logs**: Enable `--verbose` mode for detailed information
2. **Test with dry-run**: Use `--dry-run` to preview operations
3. **Review permissions**: Ensure GitHub Apps have proper permissions
4. **Check rate limits**: Monitor API usage and adjust worker counts
