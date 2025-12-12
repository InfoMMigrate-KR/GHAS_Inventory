# Alert Assignment Script

This script processes secret scanning alerts and provides functionality to assign them to the committer who introduced the secret.

## Features

- **Committer Identification**: Identifies the GitHub handle of the user who committed the code containing the secret
- **Assignment Summary**: Provides detailed statistics about alert distribution across committers
- **Flexible Output**: Supports both console display and CSV export
- **Dry-run Mode**: Allows testing without making actual API calls

## Prerequisites

1. **Commit Enrichment Enabled**: Ensure that the `fetch_secret_scanning_alerts.py` script is configured to collect committer information:
   ```bash
   export ENABLE_COMMIT_ENRICHMENT=true
   ```

2. **Updated CSV Data**: Run the fetch script to generate CSV data with committer information:
   ```bash
   python ../fetch_secret_scanning_alerts.py
   ```

## Usage

### Basic Usage
```bash
python assign_alerts.py --csv-file ../output/secret_scanning_secret_scanning_report.csv --dry-run
```

### With Custom Output File
```bash
python assign_alerts.py --csv-file ../output/secret_scanning_secret_scanning_report.csv --output my_assignments.csv
```

## Command Line Arguments

- `--csv-file`: Path to the secret scanning CSV file (required)
- `--dry-run`: Show assignments without making API calls
- `--output`: Custom output file for assignment report (CSV format)

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
```

### CSV Report Columns

| Column | Description |
|--------|-------------|
| `Committer_Id` | GitHub handle of the committer |
| `Alert_Number` | Secret scanning alert number |
| `Repository_Name` | Repository where secret was found |
| `Secret_Type` | Type of secret detected |
| `State` | Alert state (open/resolved) |
| `URL` | Direct link to the alert |
| `Total_Alerts_For_Committer` | Total alerts for this committer |
| `Open_Alerts_For_Committer` | Number of open alerts for this committer |

## Integration with GitHub API

This script provides the foundation for automated alert assignment. To implement actual GitHub API assignment, you would extend the script with:

1. **GitHub API Client**: Use PyGithub or requests to make API calls
2. **Assignment Logic**: Implement the actual alert assignment via GitHub API
3. **Error Handling**: Handle API rate limits and permissions
4. **Batch Processing**: Process assignments in batches for efficiency

### Example API Integration (Pseudocode)
```python
def assign_alert_to_user(repo_full_name: str, alert_number: int, assignee: str, github_token: str):
    """Assign a secret scanning alert to a user via GitHub API"""
    url = f"https://api.github.com/repos/{repo_full_name}/secret-scanning/alerts/{alert_number}"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json"
    }
    
    # Note: GitHub API for assigning secret scanning alerts may vary
    # Check the latest GitHub API documentation for the correct endpoint
    payload = {"assignees": [assignee]}
    
    response = requests.patch(url, json=payload, headers=headers)
    return response.status_code == 200
```

## Error Handling

The script handles common scenarios:

- **Missing committer data**: Alerts without `Committer_Id` are filtered out
- **CSV file errors**: Clear error messages for file access issues
- **Empty results**: Guidance on enabling commit enrichment if no data found

## Performance Considerations

- **API Rate Limits**: The parent fetch script respects GitHub API rate limits
- **Commit Enrichment**: Can be disabled via `ENABLE_COMMIT_ENRICHMENT=false` to save API quota
- **Batch Processing**: Consider processing assignments in batches for large datasets

## Troubleshooting

### No Committer Information Found
If the script shows no alerts with committer information:

1. Ensure `ENABLE_COMMIT_ENRICHMENT=true` in your environment
2. Re-run `fetch_secret_scanning_alerts.py` to collect the data
3. Check that your GitHub PAT has sufficient permissions to access commit information

### Rate Limiting
If you encounter API rate limit errors:

1. Use multiple GitHub PATs in the fetch script
2. Add delays between API calls
3. Process in smaller batches
4. Consider disabling commit enrichment for very large datasets

## Future Enhancements

- **Automatic Assignment**: Direct integration with GitHub API for automatic assignment
- **Assignment Rules**: Configurable rules for assignment logic (e.g., assign to repo admin if committer unavailable)
- **Notification System**: Email or Slack notifications for assigned users
- **Progress Tracking**: Track assignment progress and follow-up actions
- **Bulk Operations**: Support for bulk assignment operations via GitHub API
