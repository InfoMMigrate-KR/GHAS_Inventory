# Alert Assignment Script

This script processes secret scanning alerts from CSV files and **automatically assigns them via GitHub API** to the committer who introduced the secret.

## Features

- **Automatic Assignment**: Assigns secret scanning alerts to committers via GitHub's Secret Scanning API
- **Committer Identification**: Uses the `Commit_Author` field to identify who introduced the secret
- **Assignment Summary**: Provides detailed statistics about alert distribution across committers
- **Flexible Output**: Supports both console display and CSV export to `scripts/output/assign_alerts/`
- **Dry-run Mode**: Preview assignments without making actual API calls
- **Error Handling**: Robust retry logic with exponential backoff for API failures
- **Rate Limiting**: Built-in delays to respect GitHub API rate limits

## Prerequisites

1. **GitHub Token**: Set either `GH_PATS` (comma-separated list) or `GITHUB_TOKEN` (single token) environment variable with a token that has `repo` and `security_events` scopes
   - If using `GH_PATS`, the script will use the first token from the comma-separated list
   - Both token formats are supported for compatibility with other scripts

2. **Commit Enrichment Enabled**: Ensure that the `fetch_secret_scanning_alerts.py` script is configured to collect committer information:
   ```bash
   export ENABLE_COMMIT_ENRICHMENT=true
   ```

3. **Updated CSV Data**: Run the fetch script to generate CSV data with committer information:
   ```bash
   cd scripts/fetch-secret-scanning
   python fetch_secret_scanning_alerts.py
   ```

## Usage

### Basic Usage (Dry-run Mode)
Preview assignments without making API calls:
```bash
cd scripts/assign_alerts
python assign_alerts.py --csv-file ../fetch-secret-scanning/output/secret_scanning_20251219_163836.csv --dry-run
```

### Assign Alerts via GitHub API
Actually assign alerts to committers:
```bash
python assign_alerts.py --csv-file ../fetch-secret-scanning/output/secret_scanning_20251219_163836.csv
```

### With Custom Output File
```bash
python assign_alerts.py --csv-file ../fetch-secret-scanning/output/secret_scanning_20251219_163836.csv --output custom_report.csv
```

## Command Line Arguments

- `--csv-file`: Path to the secret scanning CSV file (required)
- `--dry-run`: Show assignments without making API calls (optional)
- `--output`: Custom output file path for assignment report (optional, default: `scripts/output/assign_alerts/alert_assignments_<timestamp>.csv`)

## Environment Variables

The script requires one of the following environment variables:

- `GH_PATS`: Comma-separated list of GitHub Personal Access Tokens (uses first token)
- `GITHUB_TOKEN`: Single GitHub Personal Access Token

Token requirements:
- `repo` scope (for repository access)
- `security_events` scope (for secret scanning alert management)

## Output

The script generates:

1. **Console Summary**: Shows assignment statistics and sample alerts for each committer
2. **CSV Report**: Detailed assignment data saved to `scripts/output/assign_alerts/alert_assignments_<timestamp>.csv`
3. **API Results**: Success/failure count for actual assignments (when not in dry-run mode)

## Output

The script generates:

1. **Console Summary**: Shows assignment statistics and sample alerts for each committer
2. **CSV Report**: Detailed assignment data that can be used for bulk processing

### Sample Console Output
```
================================================================================
SECRET SCANNING ALERT ASSIGNMENT SUMMARY
================================================================================
Total committers with alerts: 5
Total alerts to assign: 23
Open alerts: 15
Resolved alerts: 8

--------------------------------------------------------------------------------
ASSIGNMENTS BY COMMITTER:
--------------------------------------------------------------------------------

Committer: john-doe
  Total alerts: 8
  Open alerts: 5
  Repositories: repo1, repo2, repo3
  Secret types: AWS Access Key, Google API Key
  Sample open alerts:
    - #123 in repo1 (AWS Access Key)
    - #124 in repo2 (Google API Key)

2025-12-21 20:11:34,880 - INFO - Successfully assigned alert #123 in org/repo1 to @john-doe
2025-12-21 20:11:35,120 - INFO - Successfully assigned alert #124 in org/repo2 to @john-doe
2025-12-21 20:11:35,350 - INFO - Assignment complete: 15 succeeded, 0 failed

================================================================================
NEXT STEPS:
================================================================================
✓ Successfully assigned 15 alert(s) via GitHub API
Review the generated CSV file for complete assignment details.
```

### CSV Report Columns

| Column | Description |
|--------|-------------|
| `Assignee` | GitHub username of the committer (assigned user) |
| `Alert_Number` | Secret scanning alert number |
| `Repository_Name` | Repository where secret was found |
| `Secret_Type` | Type of secret detected |
| `State` | Alert state (open/resolved) |
| `URL` | Direct link to the alert |
| `Total_Alerts_For_Assignee` | Total alerts for this assignee |
| `Open_Alerts_For_Assignee` | Number of open alerts for this assignee |

## How It Works

### GitHub API Integration

The script uses the [GitHub Secret Scanning API](https://docs.github.com/en/rest/secret-scanning/secret-scanning#update-a-secret-scanning-alert) to assign alerts:

**API Endpoint:**
```
PATCH /repos/{owner}/{repo}/secret-scanning/alerts/{alert_number}
```

**Payload:**
```json
{
  "assignee": "username"
}
```

### Assignment Process

1. **Load CSV Data**: Reads secret scanning alerts from the provided CSV file
2. **Filter Alerts**: Filters alerts that have a valid `Commit_Author` value
3. **Generate Summary**: Creates assignment statistics grouped by committer
4. **Assign via API** (if not dry-run):
   - Authenticates with GitHub using provided token
   - Iterates through each alert
   - Makes PATCH request to assign alert to the committer
   - Implements retry logic with exponential backoff
   - Adds 0.1s delay between requests for rate limiting
5. **Save Report**: Exports detailed assignment data to CSV
6. **Display Results**: Shows success/failure statistics

### Error Handling

The script handles various scenarios:

- **404 Not Found**: Alert doesn't exist or was deleted
- **422 Unprocessable Entity**: Invalid assignee (user doesn't exist or lacks repository access)
- **403 Forbidden**: Token lacks required permissions
- **Network Errors**: Automatic retry with exponential backoff (up to 3 attempts)
- **Missing Data**: Alerts without `Commit_Author` are filtered out with clear warnings

## Troubleshooting

### No Committer Information Found
If the script shows no alerts with committer information:

1. Ensure `ENABLE_COMMIT_ENRICHMENT=true` in your environment
2. Re-run `fetch_secret_scanning_alerts.py` to collect the data
3. Check that your GitHub PAT has sufficient permissions to access commit information

### Assignment Failures

**422 Error - Invalid Assignee:**
- The GitHub username may not exist
- The user may not have access to the repository
- Verify the username in the `Commit_Author` column is correct

**403 Error - Permission Denied:**
- Your token needs `repo` and `security_events` scopes
- Generate a new token with proper permissions at https://github.com/settings/tokens

**404 Error - Alert Not Found:**
- The alert may have been deleted
- Verify the alert number and repository name are correct

### Rate Limiting
The script includes built-in rate limiting (0.1s delay between requests). If you still encounter rate limit errors:

1. Use multiple GitHub PATs in the `GH_PATS` environment variable
2. Increase the delay in the code (modify `time.sleep(0.1)` to a higher value)
3. Process alerts in smaller batches

## Performance Considerations

- **API Rate Limits**: The script respects GitHub API rate limits with built-in delays
- **Commit Enrichment**: Can be disabled via `ENABLE_COMMIT_ENRICHMENT=false` to save API quota
- **Batch Processing**: Processes all alerts in sequence with retry logic
- **Output Location**: Reports are saved to `scripts/output/assign_alerts/` directory

## Example Workflow

1. **Fetch Alerts with Commit Information:**
   ```bash
   cd scripts/fetch-secret-scanning
   export ENABLE_COMMIT_ENRICHMENT=true
   python fetch_secret_scanning_alerts.py
   ```

2. **Preview Assignments (Dry-run):**
   ```bash
   cd ../assign_alerts
   python assign_alerts.py --csv-file ../fetch-secret-scanning/output/secret_scanning_20251219_163836.csv --dry-run
   ```

3. **Assign Alerts via API:**
   ```bash
   python assign_alerts.py --csv-file ../fetch-secret-scanning/output/secret_scanning_20251219_163836.csv
   ```

4. **Review Results:**
   - Check console output for success/failure statistics
   - Review the CSV report in `scripts/output/assign_alerts/`
   - Verify assignments in GitHub UI

## GitHub Actions Integration

This script is automated by the 'Assign Secret Alerts' workflow in .github/workflows/assign-secret-scanning-alerts.yml.

## API Documentation

For more details on the GitHub Secret Scanning API:
- [Update a secret scanning alert](https://docs.github.com/en/rest/secret-scanning/secret-scanning#update-a-secret-scanning-alert)
- [Secret Scanning API Parameters](https://docs.github.com/en/rest/secret-scanning/secret-scanning?apiVersion=2022-11-28#update-a-secret-scanning-alert--parameters)
