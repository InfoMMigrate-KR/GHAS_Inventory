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

#### 2. Install the GitHub App

Install the GitHub App to all organizations in your enterprise where you want to fetch secret scanning alerts.

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
SECRET_TYPES=                      # Custom pattern names (see "Generic Patterns" section below)

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

GitHub's Secret Scanning API has a **critical limitation**:

- **By default**: The API returns **ONLY default patterns** (GitHub's built-in patterns like AWS keys, GitHub tokens, etc.)
- **Generic/Custom patterns**: Are **NOT returned** unless you explicitly specify their names in the `SECRET_TYPES` parameter

**This means:**
- If you see alerts in the GitHub UI with the filter `is:open results:generic`
- But the script returns **0 results**
- ✅ **You need to configure custom pattern names in `SECRET_TYPES`**

### The Solution

#### Step 1: Find Your Custom Pattern Names

**Option A: Check Enterprise/Organization Settings**
1. Go to GitHub Enterprise Settings (or Organization Settings)
2. Navigate to: Security > Code security and analysis > Secret scanning
3. Click on "Custom patterns"
4. Note the pattern names/slugs (e.g., `password`, `internal_api_key`, etc.)

**Option B: Check an Individual Alert**
1. Open any generic alert in the GitHub UI
2. Look at the alert details
3. The pattern name is shown in the alert type

**Option C: Use the Discovery Script**
```bash
python scripts/fetch-secret-scanning/discover_custom_patterns.py
```
(Note: This script will guide you on finding the names, as the API doesn't provide a discovery endpoint)

#### Step 2: Configure SECRET_TYPES

Add your custom pattern names to the `.env` file:

```env
# To fetch ONLY default patterns (omit or leave empty)
SECRET_TYPES=

# To fetch ONLY custom patterns
SECRET_TYPES=password,internal_api_key,custom_token

# To fetch both default AND custom (list all custom pattern names)
SECRET_TYPES=password,internal_api_key,custom_token
```

**Note**: Setting `SECRET_TYPES=all` does **NOT** magically fetch all patterns - it still only gets default patterns!

#### Step 3: Run the Script

```bash
python scripts/fetch-secret-scanning/fetch_secret_scanning_alerts.py
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

**Cause**: You're viewing generic/custom pattern alerts in the UI (filtered by `results:generic`), but the API only returns default patterns by default.

**Solution**: 
1. Find your custom pattern names from Enterprise/Org settings
2. Add them to `SECRET_TYPES` in `.env` file
3. Example: `SECRET_TYPES=password,api_key,internal_token`

### How do I get ALL alerts (both default and custom)?

1. Find all your custom pattern names
2. List them in `SECRET_TYPES`
3. The script will then return:
   - All default pattern alerts (always included)
   - All custom pattern alerts (because you specified them)

### The UI shows "results:generic" filter - what does that mean?

The `results:generic` filter in the GitHub UI is **NOT an API parameter**. It's a UI-only filter that shows custom patterns. To get these via API, you must specify the pattern names explicitly.

## Support

For issues or questions:
1. Check the log files in `output/logs/`
2. Verify your GitHub App configuration
3. Ensure all environment variables are set correctly
4. Check that the app is installed in target organizations
5. **If getting 0 results**: Verify `SECRET_TYPES` is configured with your custom pattern names

## GitHub Actions Integration

This directory is automated by two workflows:
- 'Fetch Secret Alerts (App)' (.github/workflows/fetch-secret-scanning-alerts.yml)
- 'Fetch Secret Alerts (PAT)' (.github/workflows/fetch-secret-scanning-alerts-pat.yml)
