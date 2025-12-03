# Secret Scanning Alerts Inventory

A Python tool for fetching and analyzing GitHub Enterprise secret scanning alerts. This tool provides comprehensive reporting on secret scanning findings across your entire GitHub Enterprise organization.

## Features

- **Enterprise-wide Coverage**: Fetches secret scanning alerts from all repositories within your GitHub Enterprise
- **Flexible Filtering**: Support for different alert states (open, resolved, all)
- **Multiple Output Formats**: Export results as Excel (.xlsx) or CSV files
- **Detailed Analytics**: Includes summary statistics and validity analysis
- **Rate Limit Handling**: Smart retry logic with exponential backoff
- **Multi-token Support**: Uses multiple GitHub tokens in round-robin for better rate limits
- **GitHub Actions Integration**: Automated scheduled runs with workflow dispatch

## Prerequisites

- Python 3.9+
- GitHub Personal Access Tokens with `admin:enterprise` scope
- Access to GitHub Enterprise organization

## Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd GHAS_Inventory
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

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

## Usage

### Local Execution

Run the script locally:

```bash
cd scripts
python fetch_secret_scanning_alerts.py
```

### GitHub Actions

The repository includes a GitHub Actions workflow for automated execution:

1. **Set up secrets** in your GitHub repository:
   - `GH_ENTERPRISE_SLUG`: Your enterprise slug
   - `GH_PATS`: Comma-separated GitHub tokens

2. **Manual trigger**: Go to Actions → "Fetch Secret Scanning Alerts" → "Run workflow"

3. **Scheduled runs**: The workflow runs daily at 6 AM UTC automatically

## Configuration Options

| Environment Variable | Description | Default | Valid Values |
|---------------------|-------------|---------|--------------|
| `GH_ENTERPRISE_SLUG` | GitHub Enterprise organization slug | *(required)* | String |
| `GH_PATS` | Comma-separated GitHub tokens | *(required)* | String |
| `ALERT_STATE` | Alert state filter | `open` | `open`, `resolved`, `all` |
| `OUTPUT_FORMAT` | Export format | `xlsx` | `xlsx`, `csv`, `both` |
| `OUTPUT_FILENAME` | Custom filename (without extension) | Auto-generated | String |

## Output Files

The tool generates the following files in the `scripts/output/` directory:

- **Excel file** (`secret_scanning_alerts_TIMESTAMP.xlsx`):
  - **Summary** sheet: Query metadata and statistics
  - **Secret_Scanning** sheet: Detailed alert data

- **CSV files** (when CSV format is selected):
  - `summary_TIMESTAMP.csv`: Summary statistics
  - `secret_scanning_TIMESTAMP.csv`: Detailed alert data

## Secret Scanning Alert Data

Each alert record includes:

- Alert number and URLs
- Repository and organization information
- Secret type and validity status
- Creation and update timestamps
- Resolution information
- Location details
- Public leak status

## GitHub Token Setup

1. **Generate Personal Access Tokens**:
   - Go to GitHub Settings → Developer settings → Personal access tokens
   - Create tokens with `admin:enterprise`, `admin:org`, `repo`, `workflow`, `user` scope
   - Store tokens securely

2. **Multiple Token Benefits**:
   - Higher rate limits through round-robin usage
   - Improved reliability and performance
   - Better handling of rate limit resets

## Troubleshooting

### Common Issues

1. **Authentication Error**: Verify your tokens have the correct `admin:enterprise` scope
2. **Rate Limit Issues**: Add more tokens to `GH_PATS` for better limits
3. **Permission Errors**: Ensure write permissions to the output directory
4. **Network Timeouts**: Check network connectivity and GitHub API status

### Logging

The tool provides comprehensive logging:
- Console output for real-time monitoring
- Log files in `scripts/output/logs/` for detailed debugging

## Security Considerations

- Store GitHub tokens securely using environment variables or secrets
- Regularly rotate access tokens
- Monitor token usage and permissions
- Restrict access to generated reports containing sensitive data

## License

This project is licensed under the MIT License - see the LICENSE file for details.
