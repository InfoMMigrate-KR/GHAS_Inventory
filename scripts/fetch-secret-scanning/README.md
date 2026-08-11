# Secret Scanning Alerts Fetcher

This directory contains scripts to fetch secret scanning alerts from GitHub organizations.

## Available Scripts

### 1. fetch_secret_scanning_alerts.py (PAT-based)
Uses Personal Access Tokens (PAT) for authentication. Simpler setup but requires proper PAT permissions.

### 2. fetch_secret_scanning_alerts_githubApp.py (GitHub App-based)
Uses GitHub App authentication. More secure and better for enterprise environments with multiple organizations.

## Overview

These scripts fetch secret scanning alerts from GitHub organizations. Since GitHub Enterprise Apps don't have direct access to enterprise-level security alerts, the scripts:
1. Fetch all organizations in the enterprise using GraphQL (or use a provided list)
2. Authenticate to each organization
3. Fetch secret scanning alerts per organization
4. Aggregate and export the results

## Which Script to Use?

- **Use PAT-based script** if:
  - You have a PAT with appropriate permissions
  - You're working with a smaller number of organizations
  - You want simpler, faster setup

- **Use GitHub App script** if:
  - You have a GitHub App configured and installed
  - You're working in an enterprise environment
  - You need more granular permissions and better auditability

## Prerequisites

### Option 1: PAT-based Authentication (fetch_secret_scanning_alerts.py)

Environment variables needed:
```env
# Personal Access Token with appropriate permissions
GH_PATS=your_pat_token_here
# Or use comma-separated list for multiple tokens
GH_PATS=token1,token2,token3

# Enterprise slug (optional, for enterprise-wide queries)
GH_ENTERPRISE_SLUG=your-enterprise-slug

# Optional: Alert Configuration
ALERT_STATE=all                    # Options: open, resolved, all (default: all)
OUTPUT_FILENAME=secret_scanning_report  # Default output filename
OUTPUT_FORMAT=csv                  # Options: csv, xlsx, both (default: csv)
ENABLE_COMMIT_ENRICHMENT=false     # Set to true to fetch commit author info (uses more API calls)
CUSTOM_SECRET_TYPES=               # Optional comma-separated custom pattern slugs
```

### Option 2: GitHub App Authentication (fetch_secret_scanning_alerts_githubApp.py)

#### 1. GitHub App Setup

You need to create and install a GitHub App with the following permissions:
- **Repository permissions:**
  - Secret scanning alerts: Read-only
  - Metadata: Read-only
  - Contents: Read-only (if fetching commit information)

- **Organization permissions:**
  - Members: Read-only (optional, for organization access)
   - Administration: Read-only (required for automatic custom-pattern discovery)

#### 2. Install the GitHub App

Install the GitHub App to all organizations in your enterprise where you want to fetch secret scanning alerts.

**💡 Pro Tip**: Use the automated [GitHub App Installation Tool](../install_gitHubApp/README.md) to install your app across all enterprise organizations at once!

#### 3. Environment Variables

Create a `.env` file in the project root with the following variables:

```env
# GitHub App Configuration
GH_APP_ID=your_app_id
GH_PRIVATE_KEY=/path/to/your/private-key.pem

# Enterprise Configuration
GH_ENTERPRISE_SLUG=your-enterprise-slug

# For fetching organizations (GraphQL query requires PAT with enterprise access)
GITHUB_TOKEN=your_personal_access_token_with_enterprise_read

# Optional: Alert Configuration
ALERT_STATE=all                    # Options: open, resolved, all (default: all)
OUTPUT_FILENAME=secret_scanning_report  # Default output filename
OUTPUT_FORMAT=csv                  # Options: csv, xlsx, both (default: csv)
CUSTOM_SECRET_TYPES=               # Custom pattern slugs (optional)

# Optional: SSL Configuration (for corporate environments)
VERIFY_SSL=true                    # Set to false if using self-signed certificates
```

## Installation

1. Install required Python packages:
```bash
pip install -r requirements.txt
```

Required packages:
- requests
- pandas
- python-dotenv
- PyJWT
- openpyxl (for Excel export)

2. Ensure the GitHub App authentication module is available:
```
scripts/
├── github_auth/
│   ├── __init__.py
│   ├── github_app_auth.py
│   └── README.md
└── fetch-secret-scanning/
    ├── fetch_secret_scanning_alerts_githubApp.py
    └── README.md
```

## Usage

### PAT-based Script

Run the script from the command line:

```bash
cd scripts/fetch-secret-scanning
python fetch_secret_scanning_alerts.py
```

### GitHub App Script

Run the script from the command line:

```bash
cd scripts/fetch-secret-scanning
python fetch_secret_scanning_alerts_githubApp.py
```

### Configuration Options

You can configure the script behavior using environment variables:

1. **Alert State Filter:**
```env
ALERT_STATE=open        # Fetch only open alerts
ALERT_STATE=resolved    # Fetch only resolved alerts
ALERT_STATE=all         # Fetch all alerts (default)
```

2. **Output Format:**
```env
OUTPUT_FORMAT=csv       # CSV files only (default)
OUTPUT_FORMAT=xlsx      # Excel file only
OUTPUT_FORMAT=both      # Both CSV and Excel
```

3. **Custom Output Filename:**
```env
OUTPUT_FILENAME=my_custom_report
```

## Output

The scripts generate output files in the `output/` directory (relative to the script location, typically `scripts/fetch-secret-scanning/output/` or `scripts/output/fetch_secret_scanning/`):

### 1. Secret Scanning Report
- **File:** `secret_scanning_report.csv` or `.xlsx`
- **Contains:** All secret scanning alerts with the following fields:
  - Alert_Number
  - Organization_Name
  - Project_Code (parsed from org name)
  - Cost_Center (parsed from org name)
  - Repository_Name
  - Secret_Type
  - Secret_Type_ID
  - State
  - Created_At
  - Updated_At
  - URL
  - Validity
  - Resolution
  - Resolved_By
  - Resolved_At
  - Publicly_Leaked
  - Push_Protection_Bypassed
  - Location_Path
  - Location_Start_Line
  - Location_End_Line
  - Location_Blob_SHA
  - Location_Blob_URL

### 2. Excel Summary Sheet
When using Excel format, the file includes a "Summary" sheet with:
- Query timestamp
- Alert state filter used
- Total counts by validity status
- Publicly leaked secrets count

### 3. Logs
- **Directory:** `output/logs/`
- **File:** `security_alerts_YYYYMMDD_HHMMSS.log`
- **Contains:** Detailed execution logs including:
  - API calls and responses
  - Rate limiting information
  - Error messages
  - Processing statistics

## Features

### Common Features (Both Scripts)

1. **Organization Discovery**
   - Automatically fetches all organizations in the enterprise (if enterprise slug provided)
   - Can also read from organizations.csv file
   - Skips organizations where authentication fails

2. **Rate Limiting Handling**
   - Automatic rate limit detection
   - Exponential backoff on retries
   - Rate limit warnings when approaching limits

3. **Error Handling**
   - Continues processing even if individual organizations fail
   - Detailed error logging
   - Summary of successful/failed organizations

4. **Data Enrichment**
   - Parses organization names for Project_Code and Cost_Center
   - Extracts location and commit information
   - Optional commit author enrichment (configurable via ENABLE_COMMIT_ENRICHMENT)

### GitHub App Specific Features

1. **GitHub App Authentication**
   - Uses GitHub App installation tokens per organization
   - Automatic token refresh when expired
   - No need for multiple PATs

2. **SSL Flexibility**
   - Configurable SSL verification for corporate environments

### PAT-based Specific Features

1. **Multi-token Support**
   - Can use multiple PATs for better rate limit handling
   - Automatic token rotation

2. **Simpler Setup**
   - No need for GitHub App configuration
   - Faster to get started

## Organization Name Format

The script expects organization names in the format: `xxxxx-yyyyy-zzzzz`
- **xxxxx**: Project Code (first part)
- **zzzzz**: Cost Center (last part)

Organizations not following this format will have:
- Project_Code: "NO PROJECT CODE"
- Cost_Center: "NO COST CENTER"

## Troubleshooting

### Common Issues

### 1. "No organizations found"
- Check that `GH_ENTERPRISE_SLUG` is correct
- Ensure your token (PAT or GitHub App) has enterprise read permissions
- Verify the PAT/token has access to the enterprise

### 2. "Failed to authenticate for organization" (GitHub App)
- Ensure the GitHub App is installed in that organization
- Check that the App has the required permissions
- Verify `GH_APP_ID` and `GH_PRIVATE_KEY` are correct

### 3. Authentication failures (PAT-based)
- Verify `GH_PATS` environment variable is set correctly
- Ensure the PAT has `repo` and `security_events` scopes
- Check that the PAT hasn't expired

### 4. Rate Limiting Issues
- Both scripts handle rate limits automatically
- If you have many organizations, expect longer execution times
- Consider running during off-peak hours
- For PAT-based script: Use multiple PATs in comma-separated format

### 5. SSL Certificate Errors
- Set `VERIFY_SSL=false` in corporate environments with self-signed certificates
- Note: This reduces security, use only when necessary

## Differences Between Scripts

| Feature | PAT-based | GitHub App |
|---------|-----------|------------|
| Authentication | Personal Access Token | GitHub App installation tokens |
| Setup Complexity | Simple | Requires App creation and installation |
| Rate Limits | Standard PAT limits | Higher App limits |
| Token Management | Manual rotation supported | Automatic refresh |
| Security | Tied to user account | App-level permissions |
| Auditability | User actions | App actions (better audit trail) |
| Multi-org Support | Single PAT for all orgs | Per-org installation required |

## Performance Considerations

- **Execution Time:** Proportional to the number of organizations and alerts
- **API Calls:** ~1-10 calls per organization (depending on alert count and pagination)
- **Rate Limits:** 
  - PAT-based: Standard GitHub API rate limits (5,000 requests/hour)
  - GitHub App: Separate rate limits per installation (typically higher)
- **Memory:** Processes all alerts in memory before export

For large enterprises (100+ organizations), expect execution times of 5-30 minutes depending on alert volumes.

## Security Best Practices

1. Keep your GitHub App private key secure
2. Use appropriate file permissions for the private key (600)
3. Store credentials in `.env` file, never commit them
4. Regularly rotate your tokens and keys
5. Use the minimum required permissions for the GitHub App

## ⚠️ IMPORTANT: Generic vs Default Secret Patterns

### The Problem

GitHub's Secret Scanning API returns default/provider patterns by default. Generic
and AI-detected patterns must be explicitly included in the `secret_type` query
parameter. Organization and enterprise custom patterns also require their slugs.

**This means:**
- If you see alerts in the GitHub UI with the filter `is:open results:generic`
- But the script returns **0 results**
- ✅ **Check that generic retrieval is enabled and custom slugs are configured when applicable**

### The Solution

#### Step 1: Find Your Custom Pattern Names (if applicable)

**Option A: Check Enterprise/Organization Settings**
1. Go to GitHub Enterprise Settings (or Organization Settings)
2. Navigate to: Security > Code security and analysis > Secret scanning
3. Click on "Custom patterns"
4. Note the pattern names/slugs (e.g., `password`, `internal_api_key`, etc.)

**Option B: Check an Individual Alert**
1. Open any generic alert in the GitHub UI
2. Look at the alert details
3. The pattern name is shown in the alert type

**Option C: Let the App discover them**

The App script calls `GET /orgs/{org}/secret-scanning/custom-patterns` for each
organization and adds all published pattern slugs automatically. This requires
the GitHub App's **Administration: Read** organization permission.

#### Step 2: Configure Generic Pattern Fetching

The GitHub App script includes GitHub's built-in generic and AI-detected pattern
slugs automatically. It also includes all default/provider patterns. The
supported built-in generic types are:

`ec_private_key`, `generic_private_key`, `http_basic_authentication_header`,
`http_bearer_authentication_header`, `mongodb_connection_string`,
`mysql_connection_url`, `openssh_private_key`, `password`, `pgp_private_key`,
`postgres_connection_string`, and `rsa_private_key`.

To include organization or enterprise custom pattern slugs, add them to the
project `.env` file:

```env
# Built-in generic patterns are included automatically by the App script
INCLUDE_GENERIC_PATTERNS=true

# Automatically discover published organization custom patterns
AUTO_DISCOVER_CUSTOM_PATTERNS=true

# Optional fallback/additional custom pattern slugs
# CUSTOM_SECRET_TYPES=internal_api_key,custom_token
```

Set `INCLUDE_GENERIC_PATTERNS=false` only when you intentionally want the
default/provider patterns alone. Set `AUTO_DISCOVER_CUSTOM_PATTERNS=false` only
when discovery is unavailable or undesired. `CUSTOM_SECRET_TYPES` can still provide
additional custom slugs manually.

#### Step 3: Run the Script

```bash
python scripts/fetch-secret-scanning/fetch_secret_scanning_alerts_githubApp.py
```

### Output with Pattern Categories

The script now automatically classifies each alert:
- Adds a **`Pattern_Category`** column with values: `default` or `generic`
- Summary statistics show counts for each category

Example output:
```
Data Processing Complete:
  - Secret Scanning: 150 alerts
    • Default Patterns: 120
    • Generic Patterns: 30
```

## Troubleshooting

### "Fetched 0 alerts" but I see alerts in the UI

**Cause**: The API requires a separate request for generic patterns. The App
script performs that request automatically. If dynamic discovery is disabled or
the App lacks Administration: Read, custom pattern slugs must be supplied in
`CUSTOM_SECRET_TYPES`.

**Solution**: 
1. Confirm `INCLUDE_GENERIC_PATTERNS=true` in `.env`
2. Confirm `AUTO_DISCOVER_CUSTOM_PATTERNS=true` and the App has Administration: Read
3. Otherwise add custom pattern slugs to `CUSTOM_SECRET_TYPES`

### How do I get ALL alerts (default, generic, and custom)?

1. Leave `INCLUDE_GENERIC_PATTERNS=true` (the default)
2. Leave `AUTO_DISCOVER_CUSTOM_PATTERNS=true` and grant Administration: Read
3. Use `CUSTOM_SECRET_TYPES` only for additional/manual slugs
4. The script will then return all default/provider alerts, built-in generic and
   AI-detected alerts, and the configured custom-pattern alerts.

### The UI shows "results:generic" filter - what does that mean?

The `results:generic` filter in the GitHub UI is **not an API parameter**. The
App script maps it to the supported generic pattern slugs, discovers published
organization custom patterns, and adds any slugs configured in `CUSTOM_SECRET_TYPES`.

## Support

For issues or questions:
1. Check the log files in `output/logs/`
2. Verify your GitHub App configuration
3. Ensure all environment variables are set correctly
4. Check that the app is installed in target organizations
5. **If getting 0 results**: Verify `CUSTOM_SECRET_TYPES` is configured with your custom pattern names

## GitHub Actions Integration

This directory is automated by two workflows:
- 'Fetch Secret Alerts (App)' (.github/workflows/fetch-secret-scanning-alerts.yml)
- 'Fetch Secret Alerts (PAT)' (.github/workflows/fetch-secret-scanning-alerts-pat.yml)
