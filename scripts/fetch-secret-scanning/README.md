# Secret Scanning Alerts Fetcher

This script fetches secret scanning alerts from GitHub organizations using GitHub App authentication.

## Overview

Since GitHub Enterprise Apps don't have direct access to enterprise-level security alerts, this script:
1. Fetches all organizations in the enterprise using GraphQL
2. Authenticates to each organization using GitHub App installation tokens
3. Fetches secret scanning alerts per organization
4. Aggregates and exports the results

## Prerequisites

### 1. GitHub App Setup

You need to create and install a GitHub App with the following permissions:
- **Repository permissions:**
  - Secret scanning alerts: Read-only
  - Metadata: Read-only
  - Contents: Read-only (if fetching commit information)

- **Organization permissions:**
  - Members: Read-only (optional, for organization access)

### 2. Install the GitHub App

Install the GitHub App to all organizations in your enterprise where you want to fetch secret scanning alerts.

### 3. Environment Variables

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

### Basic Usage

Run the script from the command line:

```bash
cd scripts/fetch-secret-scanning
python fetch_secret_scanning_alerts_githubApp.py
```

### Organization Selection

By default, the script processes **all organizations** in the enterprise. However, you can limit processing to a custom list of organizations:

**To use a custom list of organizations:**
1. Create/upload an `organizations.csv` file to `scripts/input/assign_alerts/` folder
2. The CSV should contain the list of organization names to process
3. The script will automatically detect this file and process only those organizations

**To process all organizations in the enterprise:**
1. Ensure the `organizations.csv` file is **removed** from `scripts/input/assign_alerts/` folder
2. The script will fetch and process all organizations from the enterprise

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

The script generates output files in the `output/` directory:

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

### 1. GitHub App Authentication
- Uses GitHub App installation tokens per organization
- Automatic token refresh when expired
- No need for multiple PATs

### 2. Organization Discovery
- Automatically fetches all organizations in the enterprise
- Uses GraphQL for efficient organization listing
- Skips organizations where app is not installed

### 3. Rate Limiting Handling
- Automatic rate limit detection
- Exponential backoff on retries
- Rate limit warnings when approaching limits

### 4. Error Handling
- Continues processing even if individual organizations fail
- Detailed error logging
- Summary of successful/failed organizations

### 5. Data Enrichment
- Parses organization names for Project_Code and Cost_Center
- Extracts location and commit information
- Optional commit author enrichment (disabled by default to save API calls)

## Organization Name Format

The script expects organization names in the format: `xxxxx-yyyyy-zzzzz`
- **xxxxx**: Project Code (first part)
- **zzzzz**: Cost Center (last part)

Organizations not following this format will have:
- Project_Code: "NO PROJECT CODE"
- Cost_Center: "NO COST CENTER"

## Troubleshooting

### 1. "No organizations found"
- Check that `GH_ENTERPRISE_SLUG` is correct
- Ensure `GITHUB_TOKEN` has enterprise read permissions
- Verify the PAT has access to the enterprise

### 2. "Failed to authenticate for organization"
- Ensure the GitHub App is installed in that organization
- Check that the App has the required permissions
- Verify `GH_APP_ID` and `GH_PRIVATE_KEY` are correct

### 3. Rate Limiting Issues
- The script handles rate limits automatically
- If you have many organizations, expect longer execution times
- Consider running during off-peak hours

### 4. SSL Certificate Errors
- Set `VERIFY_SSL=false` in corporate environments with self-signed certificates
- Note: This reduces security, use only when necessary

## Differences from PAT-based Version

The GitHub App version differs from the PAT-based version in:

1. **Authentication:**
   - Uses GitHub App installation tokens instead of PATs
   - Per-organization authentication instead of enterprise-wide

2. **Organization Fetching:**
   - Requires separate GraphQL query to list organizations
   - Still needs a PAT for enterprise-level GraphQL queries

3. **Alert Fetching:**
   - Fetches alerts per organization instead of enterprise-wide
   - More granular error handling per organization

4. **Permissions:**
   - App permissions are more granular and auditable
   - Can be installed selectively per organization

## Performance Considerations

- **Execution Time:** Proportional to the number of organizations
- **API Calls:** ~1-5 calls per organization (depending on alert count)
- **Rate Limits:** GitHub App has separate rate limits per installation
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
