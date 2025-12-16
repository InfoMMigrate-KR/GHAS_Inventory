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
GITHUB_APP_ID=your_app_id
GITHUB_PRIVATE_KEY_PATH=/path/to/your/private-key.pem

# Enterprise Configuration
GH_ENTERPRISE_SLUG=your-enterprise-slug

# For fetching organizations (GraphQL query requires PAT with enterprise access)
GITHUB_TOKEN=your_personal_access_token_with_enterprise_read

# Optional: Alert Configuration
ALERT_STATE=all                    # Options: open, resolved, all (default: all)
OUTPUT_FILENAME=secret_scanning_report  # Default output filename
OUTPUT_FORMAT=csv                  # Options: csv, xlsx, both (default: csv)

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
- Verify `GITHUB_APP_ID` and `GITHUB_PRIVATE_KEY_PATH` are correct

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

## Security Notes

1. Keep your GitHub App private key secure
2. Use appropriate file permissions for the private key (600)
3. Store credentials in `.env` file, never commit them
4. Regularly rotate your tokens and keys
5. Use the minimum required permissions for the GitHub App

## Support

For issues or questions:
1. Check the log files in `output/logs/`
2. Verify your GitHub App configuration
3. Ensure all environment variables are set correctly
4. Check that the app is installed in target organizations
